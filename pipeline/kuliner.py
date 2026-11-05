"""Food places named in the news become viral mention signals.  python -m pipeline.kuliner

Every RSS feed (detikFood, lifestyle sections, local outlets...) lands in `item`.
This step takes recent food stories, asks the LLM which places they name, and
records one "berita" signal per place, so a place covered by both YouTube and
the news counts as seen on two platforms in pipeline/score.py.
Only the headline and the short RSS summary are used, never the article.
"""
import re

from pipeline import extract_llm
from pipeline.common import db, env, log
from pipeline.entities import BrandMatcher, add_signal, find_or_create
from pipeline.geocode import Matcher

# cheap pre-filter, the LLM still decides whether a story is about food
POLA = re.compile(
    r"kuliner|makan|resto|restoran|kafe|cafe|kedai|warung|bakso|mi(e)? |ramen|sate|soto|nasi |"
    r"kopi|coffee|roti|bakery|dessert|seafood|jajan|street ?food|menu|rumah makan|food ?court|"
    r"es krim|boba|martabak|seblak|ayam|bebek|dimsum|sushi|pecel|gultik|angkringan",
    re.I)
BATCH = 15


def kuliner(judul, ringkasan=""):
    return bool(POLA.search(f"{judul} {ringkasan or ''}"))


def main():
    hari = int(env("KULINER_HARI", "3"))
    per_run = int(env("KULINER_PER_RUN", "90"))
    with db() as cur:
        cur.execute(
            """select id, judul, coalesce(ringkasan, ''), zona_id, kode_wilayah, published_at from item
               where tipe = 'berita' and kuliner_at is null and published_at > now() - make_interval(days => %s)
               order by published_at desc limit %s""", (hari, per_run * 4))
        rows = cur.fetchall()
        if not rows:
            log("kuliner: tidak ada berita baru")
            return
        cur.execute("update item set kuliner_at = now() where id = any(%s)",
                    ([r[0] for r in rows if not kuliner(r[1], r[2])],))
        rows = [r for r in rows if kuliner(r[1], r[2])][:per_run]
        if not rows or not extract_llm.available():
            log(f"kuliner: {len(rows)} berita makanan, LLM {'siap' if extract_llm.available() else 'belum diisi'}")
            return

        matcher, brands = Matcher(), BrandMatcher()
        cur.execute("select nama, id from zona")
        zid = dict(cur.fetchall())
        n_sig = 0
        for i in range(0, len(rows), BATCH):
            part = rows[i:i + BATCH]
            places = extract_llm.extract_places([f"{r[1]}. {r[2][:200]}" for r in part])
            for (item_id, judul, ring, zona, kode, waktu), pl in zip(part, places):
                m = matcher.match(judul, ring, pl["lokasi"] or "")
                zona_id = zid.get(m.zona) if m.ok else zona
                kode_w = m.kode_wilayah if m.ok else kode
                names = brands.find(judul) + [p for p in pl["tempat"] if not matcher.is_area_name(p)]
                seen = set()
                for nama in names:
                    ent = find_or_create(cur, nama, zona_id, kode_w, brands=brands)
                    if ent in seen:
                        continue
                    seen.add(ent)
                    add_signal(cur, ent, "berita", f"item{item_id}", zona_id, kode_w, 1, 0, waktu)
                    n_sig += 1
                    cur.execute("update item set entitas_id = coalesce(entitas_id, %s) where id = %s", (ent, item_id))
            cur.execute("update item set kuliner_at = now() where id = any(%s)", ([r[0] for r in part],))
    log(f"kuliner: {len(rows)} berita makanan, {n_sig} sinyal tempat")


if __name__ == "__main__":
    main()
