"""News RSS collector (every 15 min).  python -m collectors.rss

Stores title, a short summary (max 300 chars) and the link only - never the
full article (copyright).
"""
from datetime import datetime, timedelta, timezone

import feedparser

from pipeline.common import clean_html, db, env, http, load_config, log
from pipeline.entities import BrandMatcher
from pipeline.geocode import Matcher, strip_dateline, zona_ids
from pipeline.items import brand_mentions, insert_item


def parse_entry(e, feed, matcher):
    """Turn one feed entry into an item dict, or None if it should be skipped."""
    link = e.get("link")
    judul = clean_html(e.get("title"), 300)
    if not link or not judul:
        return None
    ringkasan = strip_dateline(clean_html(e.get("summary") or e.get("description"), 300))
    m = matcher.match(judul, ringkasan)
    if feed.get("filter_wilayah") and not m.ok:
        return None
    t = e.get("published_parsed") or e.get("updated_parsed")
    waktu = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
    waktu = min(waktu, datetime.now(timezone.utc))  # some feeds publish future timestamps
    if waktu < datetime.now(timezone.utc) - timedelta(days=int(env("RETENSI_BERITA_HARI", 14))):
        return None  # older than retention: cleanup would delete it again
    return {
        "judul": judul, "url": link, "ringkasan": ringkasan, "published_at": waktu,
        "zona": m.zona, "kode_wilayah": m.kode_wilayah or feed.get("default_wilayah"),
        "label_status": "teks" if m.ok else "baru",
    }


def main():
    cfg = load_config("sources")
    matcher, brands = Matcher(), BrandMatcher()
    total = 0
    with db() as cur:
        zid = zona_ids(cur)
        for feed in cfg.get("rss", []):
            url = feed.get("url", "")
            if not url or "ISI_URL" in url:
                continue
            try:
                r = http().get(url, timeout=45)
                r.raise_for_status()
                parsed = feedparser.parse(r.content)
            except Exception as ex:
                log(f"rss {feed['nama']}: gagal ({ex})")
                continue
            baru = 0
            for e in parsed.entries:
                it = parse_entry(e, feed, matcher)
                if not it:
                    continue
                zona_id = zid.get(it["zona"])
                item_id = insert_item(cur, feed.get("tipe", "berita"), it["judul"], it["url"], feed["nama"],
                                      it["ringkasan"], it["published_at"], it["kode_wilayah"], zona_id,
                                      label_status=it["label_status"])
                if item_id:
                    baru += 1
                    brand_mentions(cur, item_id, brands.find(it["judul"], it["ringkasan"]), "berita",
                                   zona_id, it["kode_wilayah"], it["published_at"])
            cur.connection.commit()
            log(f"rss {feed['nama']}: {len(parsed.entries)} entri, {baru} baru")
            total += baru
    log(f"rss selesai: {total} item baru")


if __name__ == "__main__":
    main()
