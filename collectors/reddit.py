"""Reddit r/indonesia + r/jakarta (optional).  python -m collectors.reddit

Needs an app-only OAuth app (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET). Check
Reddit's current Data API terms before enabling. Skipped when not configured.
"""
from datetime import datetime, timezone

from pipeline import extract_llm
from pipeline.common import clean_html, db, env, http, load_config, log
from pipeline.entities import BrandMatcher, add_signal, find_or_create
from pipeline.geocode import Matcher, zona_ids
from pipeline.items import insert_item

FOOD_WORDS = ("makan", "kuliner", "resto", "restoran", "cafe", "kafe", "kopi", "warung", "food",
              "enak", "viral", "antri", "jajan", "bakso", "mie", "sate", "nongkrong")


def token():
    cid, secret = env("REDDIT_CLIENT_ID"), env("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        return None
    r = http().post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                    data={"grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    try:
        tok = token()
    except Exception as e:
        log(f"reddit: token gagal ({e})")
        return
    if not tok:
        log("reddit: REDDIT_CLIENT_ID/SECRET belum diisi, dilewati")
        return
    cfg = load_config("sources").get("reddit", {})
    posts = []
    for sub in cfg.get("subreddits", []):
        try:
            r = http().get(f"https://oauth.reddit.com/r/{sub}/new", params={"limit": cfg.get("limit", 50)},
                           headers={"Authorization": f"Bearer {tok}"}, timeout=20)
            r.raise_for_status()
            posts += [c["data"] for c in r.json()["data"]["children"]]
        except Exception as e:
            log(f"reddit r/{sub}: gagal ({e})")

    matcher, brands = Matcher(), BrandMatcher()
    relevant = []
    for p in posts:
        judul = clean_html(p.get("title"), 300)
        body = clean_html(p.get("selftext"), 300)
        low = f"{judul} {body}".lower()
        m = matcher.match(judul, body)
        if m.ok and (any(w in low for w in FOOD_WORDS) or brands.find(judul, body)):
            relevant.append((p, judul, body, m))
    if not relevant:
        log(f"reddit: {len(posts)} post, 0 relevan")
        return
    places = extract_llm.extract_places([j for _, j, _, _ in relevant])
    n = 0
    with db() as cur:
        zid = zona_ids(cur)
        for (p, judul, body, m), pl in zip(relevant, places):
            zona_id = zid.get(m.zona)
            waktu = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
            eng = int(p.get("score", 0)) + 5 * int(p.get("num_comments", 0))
            item_id = insert_item(cur, "post", judul, f"https://www.reddit.com{p.get('permalink', '')}",
                                  f"Reddit r/{p.get('subreddit')}", body, waktu, m.kode_wilayah, zona_id,
                                  label_status="teks", hash_key=f"reddit:{p.get('id')}")
            for nama in dict.fromkeys(brands.find(judul, body) + pl["tempat"]):
                ent = find_or_create(cur, nama, zona_id, m.kode_wilayah, brands=brands)
                add_signal(cur, ent, "reddit", p.get("id", ""), zona_id, m.kode_wilayah, 1, eng, waktu)
                n += 1
                if item_id:
                    cur.execute("update item set entitas_id=coalesce(entitas_id,%s) where id=%s", (ent, item_id))
    log(f"reddit: {len(posts)} post, {len(relevant)} relevan, {n} sinyal")


if __name__ == "__main__":
    main()
