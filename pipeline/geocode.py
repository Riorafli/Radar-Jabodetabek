"""Location labelling.

1. Text matching against zones.yaml / wilayah.yaml aliases (free, instant).
2. For items still unlabelled: ask the LLM which place the text is about,
   then geocode that place with Nominatim (cached, max 1 req/s, biased to
   the Jabodetabek bounding box).

Run as a job:  python -m pipeline.geocode   (labels items with label_status='baru')
"""
import math
import re
import time
from dataclasses import dataclass

from pipeline.common import env, load_config, log

# Jabodetabek bounding box (lon/lat), excluding Kepulauan Seribu
BBOX = (106.35, -6.85, 107.35, -5.95)  # min_lon, min_lat, max_lon, max_lat


def normalize(text):
    t = (text or "").lower().replace("'", "")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return f" {t.strip()} "


_DATELINE = re.compile(
    r"^\s*(?:[A-Za-z]+\.(?:com|co\.id|id),?\s*)?"      # "REPUBLIKA.CO.ID, "
    r"[A-Za-z][A-Za-z .]{1,30}?"                         # "Jakarta" / "JAKARTA"
    r"(?:\s*\([A-Za-z ]{2,20}\))?"                       # " (ANTARA)"
    r"(?:\s*,\s*[A-Za-z][A-Za-z .]{1,30}?)?"             # ", CNN Indonesia" / ", KOMPAS.com"
    r"\s*(?:-{1,2}|–|—)\s+")


def strip_dateline(text):
    """'Jakarta, CNN Indonesia -- Pesawat batal...' -> 'Pesawat batal...'.
    Datelines name the newsroom city, not where the story happened."""
    return _DATELINE.sub("", text or "", count=1)


def _has(norm_text, phrase):
    return f" {phrase} " in norm_text


@dataclass
class Match:
    zona: str | None = None          # zone name
    kode_wilayah: str | None = None  # kode of kota/kabupaten (or "31" for generic Jakarta)
    alias: str | None = None         # the phrase that matched

    @property
    def ok(self):
        return bool(self.zona or self.kode_wilayah)


class Matcher:
    """Finds zone and city mentioned in a piece of text."""

    def __init__(self, wilayah_cfg=None, zones_cfg=None):
        wilayah_cfg = wilayah_cfg or load_config("wilayah")
        zones_cfg = zones_cfg or load_config("zones")
        self.wilayah = {}
        self.kota_alias = []  # (alias, kode)
        for w in wilayah_cfg.get("provinsi", []) + wilayah_cfg.get("wilayah", []):
            self.wilayah[w["kode"]] = w
            names = set(w.get("alias", []))
            if w.get("level") in ("kota", "kabupaten"):
                names.add(w["nama"].lower())
            for a in names:
                self.kota_alias.append((normalize(a).strip(), w["kode"]))
        self.kota_alias.sort(key=lambda x: -len(x[0]))

        self.zones = zones_cfg.get("zona", [])
        self.zona_by_name = {z["nama"]: z for z in self.zones}
        self.zona_alias = []  # (alias, zone_name, kecuali)
        for z in self.zones:
            kec = [normalize(k).strip() for k in z.get("kecuali", [])]
            for a in set(z.get("alias", []) + [z["nama"].lower()]):
                self.zona_alias.append((normalize(a).strip(), z["nama"], kec))
        self.zona_alias.sort(key=lambda x: -len(x[0]))

    def match(self, *texts):
        t = normalize(" ".join(x or "" for x in texts))
        m = Match()
        for alias, nama, kecuali in self.zona_alias:
            if _has(t, alias) and not any(_has(t, k) for k in kecuali):
                m.zona, m.alias = nama, alias
                m.kode_wilayah = self.zona_by_name[nama]["kota"]
                return m
        for alias, kode in self.kota_alias:
            if _has(t, alias):
                m.kode_wilayah, m.alias = kode, alias
                return m
        return m

    def kode_from_names(self, names):
        """Map free-text city names (e.g. from the LLM) to kode list."""
        out = []
        for n in names or []:
            m = self.match(n)
            if m.kode_wilayah and m.kode_wilayah not in out:
                out.append(m.kode_wilayah)
        return out

    # --- coordinates -------------------------------------------------------
    def zone_at(self, lat, lon):
        """Zone whose radius contains the point (closest center wins)."""
        best = None
        for z in self.zones:
            d = haversine_m(lat, lon, z["lat"], z["lon"])
            if d <= z.get("radius_m", 1500) and (best is None or d < best[0]):
                best = (d, z)
        return best[1] if best else None

    def kota_at(self, lat, lon):
        """Nearest kota/kabupaten center, only inside the Jabodetabek bbox."""
        if not in_bbox(lat, lon):
            return None
        cands = [w for w in self.wilayah.values() if w.get("level") in ("kota", "kabupaten") and w.get("lat")]
        if not cands:
            return None
        return min(cands, key=lambda w: haversine_m(lat, lon, w["lat"], w["lon"]))["kode"]


def in_bbox(lat, lon):
    return BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lon <= BBOX[2]


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def zona_ids(cur):
    cur.execute("select nama, id from zona")
    return dict(cur.fetchall())


# --- Nominatim ---------------------------------------------------------------
_last_call = [0.0]


def nominatim(cur, query, matcher):
    """Geocode `query` inside Jabodetabek. Cached forever in geocode_cache.
    Returns (lat, lon, kode_wilayah) or None."""
    from psycopg2.extras import Json
    from pipeline.common import http

    q = normalize(query).strip()
    if not q:
        return None
    cur.execute("select lat, lon, kode_wilayah from geocode_cache where query = %s", (q,))
    row = cur.fetchone()
    if row:
        return row if row[0] is not None else None

    wait = 1.1 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    try:
        r = http().get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query, "format": "jsonv2", "countrycodes": "id", "limit": 1,
                "addressdetails": 1, "bounded": 1,
                "viewbox": f"{BBOX[0]},{BBOX[3]},{BBOX[2]},{BBOX[1]}",
            },
            timeout=20,
        )
        r.raise_for_status()
        res = r.json()
    except Exception as e:  # network error: do not cache, try again next run
        log("nominatim error", query, e)
        return None

    lat = lon = kode = None
    raw = res[0] if res else None
    if raw:
        lat, lon = float(raw["lat"]), float(raw["lon"])
        addr = raw.get("address", {})
        addr_text = " ".join(str(addr.get(k, "")) for k in
                             ("city", "county", "state_district", "municipality", "suburb", "city_district"))
        kode = matcher.match(addr_text).kode_wilayah or matcher.kota_at(lat, lon)
    cur.execute(
        "insert into geocode_cache (query, lat, lon, kode_wilayah, raw) values (%s,%s,%s,%s,%s) "
        "on conflict (query) do nothing",
        (q, lat, lon, kode, Json(raw)),
    )
    return (lat, lon, kode) if lat is not None else None


# --- job ---------------------------------------------------------------------
def main(limit_text=500, limit_llm=None):
    from pipeline.common import db
    from pipeline import extract_llm

    limit_llm = int(limit_llm or env("GEOCODE_LLM_LIMIT", 15))
    m = Matcher()
    with db() as cur:
        zid = zona_ids(cur)
        cur.execute(
            "select id, judul, coalesce(ringkasan,'') from item where label_status='baru' "
            "order by published_at desc limit %s", (limit_text,))
        rows = cur.fetchall()
        sisa = []
        for item_id, judul, ringkasan in rows:
            r = m.match(judul, ringkasan)
            if r.ok:
                cur.execute("update item set kode_wilayah=coalesce(kode_wilayah,%s), zona_id=%s, label_status='teks' where id=%s",
                            (r.kode_wilayah, zid.get(r.zona), item_id))
            else:
                sisa.append((item_id, judul, ringkasan))
        log(f"label teks: {len(rows) - len(sisa)}/{len(rows)}")

        batch = sisa[:limit_llm]
        if batch and extract_llm.available():
            places = extract_llm.extract_locations([f"{j}. {s[:200]}" for _, j, s in batch])
            done = 0
            for (item_id, _, _), place in zip(batch, places):
                status, kode, zona, lat, lon = "gagal", None, None, None, None
                if place:
                    r = m.match(place)
                    if r.ok:
                        kode, zona, status = r.kode_wilayah, r.zona, "llm"
                    else:
                        g = nominatim(cur, place, m)
                        if g:
                            lat, lon, kode = g
                            z = m.zone_at(lat, lon)
                            zona = z["nama"] if z else None
                            status = "geocode"
                cur.execute(
                    "update item set kode_wilayah=coalesce(kode_wilayah,%s), zona_id=coalesce(zona_id,%s), "
                    "lat=coalesce(lat,%s), lon=coalesce(lon,%s), label_status=%s where id=%s",
                    (kode, zid.get(zona), lat, lon, status, item_id))
                done += status != "gagal"
            log(f"label llm/geocode: {done}/{len(batch)}")
        # items from local feeds that already have a default wilayah but no
        # better match should not stay in the queue forever
        cur.execute("update item set label_status='gagal' where label_status='baru' "
                    "and dibuat < now() - interval '1 day'")


if __name__ == "__main__":
    main()
