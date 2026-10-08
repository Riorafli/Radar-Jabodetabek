"""YouTube viral-food signal (every 2 h).  python -m collectors.youtube

Quota: search.list = 100 units, videos.list = 1 unit per call (up to 50 ids).
With per_run=4 and 12 runs/day -> ~4,900 units/day of the 10,000 free.
"""
from datetime import timedelta

from psycopg2.extras import Json

from pipeline import extract_llm
from pipeline.common import clean_html, db, env, http, load_config, log, now_utc, sha1
from pipeline.entities import BrandMatcher, add_signal, find_or_create
from pipeline.geocode import Matcher, zona_ids
from pipeline.items import insert_item

API = "https://www.googleapis.com/youtube/v3"


def pick_queries(queries, per_run, now):
    """Rotate through the query list so every query runs a few times a day."""
    if not queries:
        return []
    slot = (now.hour // 2) * per_run
    return [queries[(slot + i) % len(queries)] for i in range(min(per_run, len(queries)))]


def engagement(stats):
    views = int(stats.get("viewCount", 0) or 0)
    likes = int(stats.get("likeCount", 0) or 0)
    comments = int(stats.get("commentCount", 0) or 0)
    return views + 10 * likes + 20 * comments


def main():
    key = env("YOUTUBE_API_KEY")
    if not key:
        log("youtube: YOUTUBE_API_KEY belum diisi, dilewati")
        return
    cfg = load_config("sources").get("youtube", {})
    now = now_utc()
    after = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    videos = {}
    for q in pick_queries(cfg.get("queries", []), cfg.get("per_run", 4), now):
        try:
            r = http().get(f"{API}/search", params={
                "key": key, "q": q, "part": "snippet", "type": "video", "regionCode": "ID",
                "relevanceLanguage": "id", "order": "date", "publishedAfter": after,
                "maxResults": cfg.get("max_results", 25)}, timeout=30)
            if r.status_code == 403:
                log("youtube: kuota habis / key ditolak, berhenti")
                break
            r.raise_for_status()
        except Exception as e:
            log(f"youtube search '{q}': gagal ({e})")
            continue
        for it in r.json().get("items", []):
            vid = it["id"].get("videoId")
            if vid:
                videos[vid] = {"snippet": it["snippet"], "query": q}
        log(f"youtube '{q}': {len(r.json().get('items', []))} video")

    # statistics, 50 ids per call (1 unit each)
    ids = list(videos)
    for i in range(0, len(ids), 50):
        try:
            r = http().get(f"{API}/videos", params={"key": key, "part": "statistics", "id": ",".join(ids[i:i + 50])}, timeout=30)
            r.raise_for_status()
            for v in r.json().get("items", []):
                videos[v["id"]]["stats"] = v.get("statistics", {})
        except Exception as e:
            log(f"youtube stats: gagal ({e})")

    if not videos:
        return
    matcher, brands = Matcher(), BrandMatcher()
    titles = [clean_html(v["snippet"]["title"], 300) for v in videos.values()]
    places = extract_llm.extract_places(titles) if extract_llm.available() else [{"tempat": [], "lokasi": None}] * len(titles)

    n_signal = 0
    with db() as cur:
        zid = zona_ids(cur)
        for (vid, v), judul, pl in zip(videos.items(), titles, places):
            sn = v["snippet"]
            desc = clean_html(sn.get("description"), 300)
            m = matcher.match(judul, desc, pl["lokasi"] or "")
            if not m.ok:
                m = matcher.match(v["query"])  # fall back to the area in the search query
            zona_id = zid.get(m.zona)
            eng = engagement(v.get("stats", {}))
            item_id = insert_item(
                cur, "post", judul, f"https://www.youtube.com/watch?v={vid}", "YouTube", desc,
                sn.get("publishedAt"), m.kode_wilayah, zona_id, label_status="teks" if m.ok else "baru",
                meta={"channel": sn.get("channelTitle"), "stats": v.get("stats", {}), "query": v["query"]},
                hash_key=f"yt:{vid}")
            if not item_id:  # seen before: refresh view/like counts
                cur.execute("update item set meta = jsonb_set(meta, '{stats}', %s) where hash_dedup = %s",
                            (Json(v.get("stats", {})), sha1(f"yt:{vid}")))

            names = brands.find(judul, desc) + [p for p in pl["tempat"]]
            seen = set()
            for nama in names:
                ent = find_or_create(cur, nama, zona_id, m.kode_wilayah, brands=brands)
                if ent in seen:
                    continue
                seen.add(ent)
                add_signal(cur, ent, "youtube", vid, zona_id, m.kode_wilayah, 1, eng, sn.get("publishedAt"))
                n_signal += 1
                if item_id:
                    cur.execute("update item set entitas_id=coalesce(entitas_id,%s) where id=%s", (ent, item_id))
    log(f"youtube: {len(videos)} video, {n_signal} sinyal")


if __name__ == "__main__":
    main()
