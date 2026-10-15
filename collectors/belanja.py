"""Shopping promos (hourly).  python -m collectors.belanja

Marketplaces (Shopee, Tokopedia, ...) forbid scraping and have no public feed,
so this reads the official RSS feeds of news outlets (allowed by robots.txt)
and picks articles about:
  - marketplace   promo / flash sale / voucher on an online store
  - cuci_gudang   warehouse sale, clearance, obral, bazar, big sale at a place
  - lainnya       other usable shopping promos (supermarket, bank card, ...)
Gemini turns each article into structured data. Every article goes to the LLM
at most once (remembered in halaman_cache, also when rejected).

Marketplace products are also found automatically on YouTube ("racun shopee",
"flash sale shopee hari ini", ...) every `belanja.youtube.setiap_jam` hours:
recent, well-watched videos -> Gemini extracts product, platform, price.
"""
import re
from datetime import datetime, timedelta, timezone

import feedparser

from pipeline import extract_llm
from pipeline.common import clean_html, db, env, http, load_config, log, sha1
from pipeline.geocode import Match, Matcher, nominatim, rapikan_kode, zona_ids
from pipeline.items import insert_item

MARKETPLACE = re.compile(r"\b(shopee|tokopedia|lazada|blibli|tiktok ?shop|bukalapak|zalora|jd\.id)\b", re.I)
PROMO = re.compile(r"diskon|promo|voucher|cashback|flash sale|harbolnas|potongan harga|gratis ongkir|\bsale\b", re.I)
SALE_FISIK = re.compile(r"cuci gudang|warehouse sale|clearance|\bobral|bazar|bazaar|midnight sale|big sale|great sale|"
                        r"full day sale|mega sale|grand sale", re.I)
CACHE_TAG = "belanja"
MAX_UMUR_HARI = 10


def kandidat(judul, ringkasan):
    """Cheap keyword pre-filter before spending LLM quota."""
    t = f"{judul} {ringkasan}"
    return bool((MARKETPLACE.search(t) and PROMO.search(t)) or SALE_FISIK.search(t))


def feeds(cfg):
    """belanja.rss plus every regular news feed, without duplicates."""
    out, seen = [], set()
    for f in cfg.get("belanja", {}).get("rss", []) + cfg.get("rss", []):
        if f.get("url") and f["url"] not in seen and "ISI_URL" not in f["url"]:
            seen.add(f["url"])
            out.append(f)
    return out


def ambil_artikel(cfg, now):
    arts, seen = [], set()
    for f in feeds(cfg):
        try:
            r = http().get(f["url"], timeout=45)
            r.raise_for_status()
            entries = feedparser.parse(r.content).entries
        except Exception as e:
            log(f"belanja {f['nama']}: gagal ({e})")
            continue
        for e in entries:
            url, judul = e.get("link"), clean_html(e.get("title"), 300)
            if not url or not judul or url in seen:
                continue
            ringkasan = clean_html(e.get("summary") or e.get("description"), 1200)
            t = e.get("published_parsed") or e.get("updated_parsed")
            terbit = min(datetime(*t[:6], tzinfo=timezone.utc), now) if t else now
            if terbit < now - timedelta(days=MAX_UMUR_HARI) or not kandidat(judul, ringkasan):
                continue
            seen.add(url)
            arts.append({"url": url, "judul": judul, "ringkasan": ringkasan, "terbit": terbit, "sumber": f["nama"]})
    return arts


def gabung_produk(lama, baru, limit=240):
    """'TV, AC' + 'Kulkas' -> 'TV, AC, Kulkas' (no duplicates, capped)."""
    items = [x.strip() for x in (lama or "").split(",") if x.strip()]
    for x in (baru or "").split(","):
        x = x.strip()
        if x and x.lower() not in {i.lower() for i in items}:
            items.append(x)
    out = ""
    for x in items:
        nxt = f"{out}, {x}" if out else x
        if len(nxt) > limit:
            break
        out = nxt
    return out or None


def gabung(cur, p, judul):
    """Several articles about one event (e.g. 15 x 'Transmart Full Day Sale')
    become one card: add the product + best discount to the existing promo."""
    cur.execute(
        """select p.item_id, p.produk, p.diskon_persen, p.selesai, p.selesai_perkiraan
           from promo p join item i on i.id = p.item_id
           where p.kategori = %s and lower(i.judul) = lower(%s) and i.published_at > now() - interval '14 days'
           order by i.id limit 1""", (p["kategori"], judul))
    row = cur.fetchone()
    if not row:
        return False
    item_id, produk, diskon, selesai, perkiraan = row
    if perkiraan and not p["selesai_perkiraan"]:      # a real date beats an assumed one
        selesai, perkiraan = p["selesai"], False
    cur.execute("""update promo set produk = %s, diskon_persen = nullif(greatest(coalesce(diskon_persen, 0), %s), 0),
                   selesai = %s, selesai_perkiraan = %s, platform = (select array(select distinct unnest(platform || %s::text[])))
                   where item_id = %s""",
                (gabung_produk(produk, p["produk"]), p["diskon_persen"] or 0, selesai, perkiraan, p["platform"], item_id))
    return True


def giliran_youtube(now, setiap_jam):
    """Run the YouTube search only every N hours to stay inside the free quota."""
    return setiap_jam <= 1 or now.hour % setiap_jam == 0


def grup_youtube(yt):
    """Config groups; an old single-list config still works."""
    if yt.get("grup"):
        return yt["grup"]
    if not yt.get("queries"):
        return []
    return [{"nama": "marketplace", "queries": yt["queries"], "per_run": yt.get("per_run", 1),
             "urut": "viewCount", "hari": yt.get("hari", 3), "min_views": yt.get("min_views", 2000)}]


def ambil_youtube(cfg, now):
    """Recent shopping videos (marketplace finds, cuci gudang) as 'articles' for the same pipeline."""
    from collectors.youtube import pick_queries

    yt = cfg.get("belanja", {}).get("youtube", {})
    key = env("YOUTUBE_API_KEY")
    grup = grup_youtube(yt)
    if not key or not grup:
        return []
    if not (env("BELANJA_YT_PAKSA") or giliran_youtube(now, int(yt.get("setiap_jam", 3)))):
        return []
    api = "https://www.googleapis.com/youtube/v3"
    arts = []
    for g in grup:
        after = (now - timedelta(days=int(g.get("hari", 3)))).strftime("%Y-%m-%dT%H:%M:%SZ")
        videos = {}
        for q in pick_queries(g.get("queries", []), int(g.get("per_run", 1)), now):
            try:
                r = http().get(f"{api}/search", params={
                    "key": key, "q": q, "part": "snippet", "type": "video", "regionCode": "ID", "relevanceLanguage": "id",
                    "order": g.get("urut", "viewCount"), "publishedAfter": after,
                    "maxResults": int(yt.get("max_results", 15))}, timeout=30)
                r.raise_for_status()
            except Exception as ex:
                log(f"belanja youtube '{q}': gagal ({ex})")
                continue
            for it in r.json().get("items", []):
                if it["id"].get("videoId"):
                    videos[it["id"]["videoId"]] = it["snippet"]
            log(f"belanja youtube [{g.get('nama')}] '{q}': {len(r.json().get('items', []))} video")
        if not videos:
            continue
        views = {}
        try:
            r = http().get(f"{api}/videos", params={"key": key, "part": "statistics", "id": ",".join(list(videos)[:50])}, timeout=30)
            r.raise_for_status()
            views = {v["id"]: int(v.get("statistics", {}).get("viewCount", 0) or 0) for v in r.json().get("items", [])}
        except Exception as ex:
            log(f"belanja youtube stats: gagal ({ex})")
        min_views = int(g.get("min_views", 2000))
        n0 = len(arts)
        for vid, sn in videos.items():
            if views.get(vid, 0) < min_views:
                continue
            terbit = datetime.strptime(sn["publishedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            arts.append({"url": f"https://www.youtube.com/watch?v={vid}", "judul": clean_html(sn.get("title"), 300),
                         "ringkasan": clean_html(sn.get("description"), 1200), "terbit": min(terbit, now), "sumber": "YouTube",
                         "umur": g.get("berlaku_hari")})
        log(f"belanja youtube [{g.get('nama')}]: {len(arts) - n0} video >= {min_views} views")
    return arts


def main():
    if not extract_llm.available():
        log("belanja: GEMINI_API_KEY / GROQ_API_KEY belum diisi, dilewati")
        return
    cfg = load_config("sources")
    now = datetime.now(timezone.utc)
    arts = ambil_artikel(cfg, now) + ambil_youtube(cfg, now)
    max_llm = int(cfg.get("belanja", {}).get("max_artikel_per_run", 24))
    matcher = Matcher()
    with db() as cur:
        urls = [a["url"] for a in arts]
        cur.execute("select url from halaman_cache where url = any(%s) and hash = %s", (urls, CACHE_TAG))
        done = {r[0] for r in cur.fetchall()}
        cur.execute("select hash_dedup from item where hash_dedup = any(%s)", ([sha1(u) for u in urls],))
        ada = {r[0] for r in cur.fetchall()}
        done |= {u for u in urls if sha1(u) in ada}
        todo = [a for a in arts if a["url"] not in done][:max_llm]
        log(f"belanja: {len(arts)} kandidat, {len(todo)} baru untuk diproses")
        if not todo:
            return
        zid = zona_ids(cur)
        hasil = extract_llm.extract_belanja(todo, matcher)
        if hasil is None:
            log("belanja: LLM gagal, dicoba lagi run berikutnya")
            return
        geocode_sisa = int(env("BELANJA_GEOCODE_LIMIT", 5))
        jumlah = {"marketplace": 0, "cuci_gudang": 0, "lainnya": 0, "gabung": 0}
        for a, p in zip(todo, hasil):
            cur.execute("""insert into halaman_cache (url, hash) values (%s,%s)
                           on conflict (url) do update set hash=excluded.hash, diambil=now()""", (a["url"], CACHE_TAG))
            if not p:
                continue
            m = matcher.match(p["lokasi"] or "", p["kota"] or "") if p["kategori"] != "marketplace" else None
            lat = lon = None
            # a venue named like the organiser ("Transmart") means every branch: no single pin
            spesifik = p["lokasi"] and p["lokasi"].strip().lower() not in (p["brand"].lower(), (p["acara"] or "").lower())
            if p["kategori"] == "cuci_gudang" and spesifik and geocode_sisa > 0:
                geocode_sisa -= 1
                g = nominatim(cur, f"{p['lokasi']}, {p['kota'] or 'Jakarta'}", matcher)
                if g:
                    lat, lon = g[0], g[1]
                    z = matcher.zone_at(lat, lon)
                    if z and not (m and m.zona):
                        m = matcher.match(z["nama"])
                    elif g[2] and not (m and m.kode_wilayah):
                        m = Match(kode_wilayah=g[2])
            kota = p["kota_berlaku"]
            if m and m.kode_wilayah and m.kode_wilayah not in kota:
                kota = [m.kode_wilayah] + kota
            kota = rapikan_kode(kota)
            judul = p["acara"] or p["judul"]
            if gabung(cur, p, judul):
                jumlah["gabung"] += 1
                continue
            item_id = insert_item(
                cur, "promo", judul, a["url"], a["sumber"], clean_html(a["ringkasan"], 300), a["terbit"],
                kota[0] if len(kota) == 1 else None, zid.get(m.zona) if m else None, lat=lat, lon=lon,
                meta={"kategori": p["kategori"]}, label_status="teks")
            if not item_id:
                continue
            cur.execute(
                """insert into promo (item_id, brand, menu, harga, harga_teks, mulai, selesai, syarat, kota_berlaku,
                                      kategori, platform, produk, lokasi, diskon_persen, selesai_perkiraan)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (item_id, p["brand"], p["produk"], p["harga"], p["diskon_teks"], p["mulai"], p["selesai"], None, kota,
                 p["kategori"], p["platform"], p["produk"], p["lokasi"], p["diskon_persen"], p["selesai_perkiraan"]))
            jumlah[p["kategori"]] += 1
    log(f"belanja: {jumlah['marketplace']} marketplace, {jumlah['cuci_gudang']} cuci gudang/sale, "
        f"{jumlah['lainnya']} lainnya, {jumlah['gabung']} digabung ke acara yang sama")


if __name__ == "__main__":
    main()
