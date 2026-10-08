"""Remove near-duplicate news (same story from several outlets).

Exact duplicates are already blocked by item.hash_dedup (URL hash). This step
uses pg_trgm on titles of the last 2 days and keeps the oldest copy.
python -m pipeline.dedup
"""
from pipeline.common import db, log

THRESHOLD = 0.75


def main():
    with db() as cur:
        cur.execute("select set_limit(%s)", (THRESHOLD,))
        cur.execute(
            """delete from item a using item b
               where a.tipe in ('berita','info') and b.tipe = a.tipe
                 and a.id > b.id
                 and a.published_at > now() - interval '2 days'
                 and b.published_at > now() - interval '3 days'
                 and a.judul %% b.judul
                 and similarity(a.judul, b.judul) >= %s""",
            (THRESHOLD,))
        log(f"dedup: {cur.rowcount} duplikat dihapus")


if __name__ == "__main__":
    main()
