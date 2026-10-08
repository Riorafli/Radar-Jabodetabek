"""Google Trends "Trending Now" for Indonesia (public RSS, no key).
python -m collectors.trends_now

Each trending search is stored once per day as item tipe='post',
sumber='Google Trends' (title = the search, summary = top news headline).
Searches that name a known food brand also become a 'gtrends' mention signal.
"""
import re
from datetime import datetime, timezone

import feedparser
from psycopg2.extras import Json

from pipeline.common import clean_html, db, http, load_config, log, sha1, today_wib
from pipeline.entities import BrandMatcher
from pipeline.geocode import Matcher, zona_ids
from pipeline.items import brand_mentions, insert_item

SUMBER = "Google Trends"


def traffic(text):
    """'10,000+' / '10000+' / '2K+' -> 10000 / 2000 (0 if unknown)."""
    t = (text or "").strip().upper().replace(",", "").replace(".", "").rstrip("+")
    m = re.match(r"^(\d+)\s*([KM]?)", t)
    if not m:
        return 0
    return int(m.group(1)) * {"": 1, "K": 1000, "M": 1000000}[m.group(2)]


def parse(entry):
    judul = clean_html(entry.get("title"), 200)
    if not judul:
        return None
    t = entry.get("published_parsed")
    return {
        "judul": judul,
        "traffic": traffic(entry.get("ht_approx_traffic")),
        "traffic_teks": entry.get("ht_approx_traffic") or "",
        "berita": clean_html(entry.get("ht_news_item_title"), 200),
        "url": entry.get("ht_news_item_url") or f"https://www.google.com/search?q={judul}",
        "sumber_berita": clean_html(entry.get("ht_news_item_source"), 80),
        "gambar": entry.get("ht_picture") or "",
        "waktu": datetime(*t[:6], tzinfo=timezone.utc) if t else None,
    }


def main():
    cfg = load_config("sources").get("google_trends_now", {})
    url = cfg.get("url", "https://trends.google.com/trending/rss?geo=ID")
    try:
        r = http().get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log(f"google trends now: gagal ({e})")
        return
    entries = [p for p in (parse(e) for e in feedparser.parse(r.content).entries) if p]
    matcher, brands = Matcher(), BrandMatcher()
    hari = today_wib().isoformat()
    baru = 0
    with db() as cur:
        zid = zona_ids(cur)
        for p in entries:
            m = matcher.match(p["judul"], p["berita"])
            item_id = insert_item(
                cur, "post", p["judul"], p["url"], SUMBER, p["berita"], p["waktu"], m.kode_wilayah, zid.get(m.zona),
                meta={"traffic": p["traffic"], "traffic_teks": p["traffic_teks"], "sumber_berita": p["sumber_berita"],
                      "gambar": p["gambar"]},
                label_status="teks", hash_key=f"gtrends:{hari}:{p['judul'].lower()}")
            if item_id:
                baru += 1
                brand_mentions(cur, item_id, brands.find(p["judul"], p["berita"]), "gtrends",
                               zid.get(m.zona), m.kode_wilayah, p["waktu"], p["traffic"])
            else:  # seen today already: keep the latest traffic estimate
                cur.execute("update item set meta = meta || %s where hash_dedup = %s",
                            (Json({"traffic": p["traffic"], "traffic_teks": p["traffic_teks"]}),
                             sha1(f"gtrends:{hari}:{p['judul'].lower()}")))
    log(f"google trends now: {len(entries)} trending, {baru} baru")


if __name__ == "__main__":
    main()
