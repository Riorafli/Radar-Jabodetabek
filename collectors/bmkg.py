"""BMKG nowcast weather warnings for Jabodetabek.  python -m collectors.bmkg

Source: BMKG Open Data nowcast feed (CAP alerts per province). A warning is
kept when it is for DKI Jakarta, or when its text names a Jabodetabek area.
"""
from datetime import datetime, timezone

import feedparser

from pipeline.common import clean_html, db, http, load_config, log
from pipeline.geocode import Matcher, zona_ids
from pipeline.items import insert_item


def relevan(judul, ringkasan, matcher, provinsi):
    """Match for a Jabodetabek warning, else None. The province check comes
    first so a same-named kecamatan elsewhere (e.g. Beji, Jatim) is ignored."""
    teks = f"{judul} {ringkasan}".lower()
    if not any(p.lower() in teks for p in provinsi):
        return None
    m = matcher.match(ringkasan)
    if m.ok:
        return m
    return matcher.match("dki jakarta") if "dki jakarta" in teks else None


def main():
    cfg = load_config("sources").get("bmkg", {})
    matcher = Matcher()
    try:
        r = http().get(cfg["nowcast_url"], timeout=25)
        r.raise_for_status()
    except Exception as e:
        log(f"bmkg: gagal ({e})")
        return
    feed = feedparser.parse(r.content)
    baru = 0
    with db() as cur:
        zid = zona_ids(cur)
        for e in feed.entries:
            judul = clean_html(e.get("title"), 200)
            penuh = clean_html(e.get("summary") or e.get("description"), 5000)  # full kecamatan list
            m = relevan(judul, penuh, matcher, cfg.get("provinsi", []))
            if not m:
                continue
            ringkasan = clean_html(penuh, 300)
            t = e.get("published_parsed")
            waktu = datetime(*t[:6], tzinfo=timezone.utc) if t else None
            if insert_item(cur, "info", f"⚠️ {judul}", e.get("link"), "BMKG", ringkasan, waktu,
                           m.kode_wilayah, zid.get(m.zona), label_status="teks"):
                baru += 1
    log(f"bmkg: {len(feed.entries)} peringatan, {baru} baru untuk Jabodetabek")


if __name__ == "__main__":
    main()
