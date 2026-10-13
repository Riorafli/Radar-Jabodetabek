"""Brand outlets from OpenStreetMap, for "promo terdekat" (daily).
python -m collectors.outlet

One Overpass query over the whole Jabodetabek bounding box for food places
whose name or brand tag matches a brand from brands.yaml or a recent food
promo. Stored as entitas (tipe 'tempat', osm_id) - the web finds the outlet
nearest to the visitor for each promo brand.
"""
import re

from pipeline.common import db, http, load_config, log
from pipeline.geocode import BBOX, Matcher

AMENITY = "fast_food|restaurant|cafe|food_court|ice_cream"


def nama_brand(cur):
    names = [b["nama"] for b in load_config("brands").get("brand", [])]
    cur.execute("""select p.brand, count(*) from promo p join item i on i.id = p.item_id
                   where p.kategori = 'makanan' and i.published_at > now() - interval '90 days'
                   group by 1 order by 2 desc limit 60""")
    for b, _ in cur.fetchall():
        if b and len(b.strip()) >= 3 and b not in names:
            names.append(b.strip())
    return names


def pola(names):
    """Overpass-safe regex: letters/digits/spaces kept, anything else -> '.'"""
    return "|".join(re.sub(r"[^\w\s&-]", ".", n) for n in names if n)


def query(names):
    rx = pola(names)
    w, s, e, n = BBOX
    box = f"({s},{w},{n},{e})"
    return (f'[out:json][timeout:180];('
            f'nwr["amenity"~"^({AMENITY})$"]["name"~"{rx}",i]{box};'
            f'nwr["amenity"~"^({AMENITY})$"]["brand"~"{rx}",i]{box};'
            f');out center tags;')


def main():
    cfg = load_config("sources").get("osm", {})
    matcher = Matcher()
    with db() as cur:
        names = nama_brand(cur)
    try:
        r = http().post(cfg.get("endpoint", "https://overpass-api.de/api/interpreter"), data={"data": query(names)}, timeout=240)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception as ex:
        log(f"outlet: gagal ({ex})")
        return
    baru = 0
    with db() as cur:
        for el in elements:
            tags = el.get("tags", {})
            name, brand = tags.get("name"), tags.get("brand")
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if not (name or brand) or lat is None:
                continue
            nama = name or brand
            if brand and brand.lower() not in nama.lower():
                nama = f"{brand} {nama}"
            z = matcher.zone_at(lat, lon)
            cur.execute("""insert into entitas (tipe, nama, zona_id, kode_wilayah, lat, lon, osm_id)
                           values ('tempat', %s, (select id from zona where nama = %s), %s, %s, %s, %s)
                           on conflict (osm_id) do nothing""",
                        (nama[:120], z["nama"] if z else None, matcher.kota_at(lat, lon), lat, lon, f"{el['type']}/{el['id']}"))
            baru += cur.rowcount
    log(f"outlet: {len(names)} brand dicari, {len(elements)} outlet ditemukan, {baru} baru")


if __name__ == "__main__":
    main()
