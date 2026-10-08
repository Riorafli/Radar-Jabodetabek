"""GDELT DOC API: extra news coverage, free, no key.  python -m collectors.gdelt
Rate limit: max 1 request / 5 s - this collector makes exactly one per run.
Only articles whose title names a Jabodetabek place are kept.
"""
from datetime import datetime, timezone

from pipeline.common import clean_html, db, http, load_config, log
from pipeline.entities import BrandMatcher
from pipeline.geocode import Matcher, zona_ids
from pipeline.items import brand_mentions, insert_item


def main():
    cfg = load_config("sources").get("gdelt", {})
    if not cfg.get("aktif"):
        return
    try:
        r = http().get("https://api.gdeltproject.org/api/v2/doc/doc", params={
            "query": cfg["query"], "mode": "artlist", "format": "json",
            "maxrecords": cfg.get("maxrecords", 75), "timespan": cfg.get("timespan", "2h"),
            "sort": "datedesc"}, timeout=40)
        if r.status_code == 429:
            log("gdelt: rate limited, dilewati")
            return
        r.raise_for_status()
        arts = r.json().get("articles", []) if r.text.strip().startswith("{") else []
    except Exception as e:
        log(f"gdelt: gagal ({e})")
        return
    matcher, brands = Matcher(), BrandMatcher()
    baru = 0
    with db() as cur:
        zid = zona_ids(cur)
        for a in arts:
            judul = clean_html(a.get("title"), 300)
            m = matcher.match(judul)
            if not judul or not m.ok:
                continue
            try:
                waktu = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                waktu = None
            item_id = insert_item(cur, "berita", judul, a.get("url"), a.get("domain", "GDELT"), None, waktu,
                                  m.kode_wilayah, zid.get(m.zona), label_status="teks")
            if item_id:
                baru += 1
                brand_mentions(cur, item_id, brands.find(judul), "berita", zid.get(m.zona), m.kode_wilayah, waktu)
    log(f"gdelt: {len(arts)} artikel, {baru} baru")


if __name__ == "__main__":
    main()
