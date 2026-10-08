"""Check that accounts, keys and the database are ready.  python scripts/check_setup.py
Prints OK / MISSING / FAIL per item. Read-only: it writes nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import env  # noqa: E402

TABLES = ["wilayah", "kawasan", "zona", "entitas", "item", "promo", "sinyal", "skor", "laporan",
          "geocode_cache", "halaman_cache", "langganan", "notif_log", "zona_statistik"]
ok = True


def show(status, what, detail=""):
    global ok
    ok &= status in ("OK", "OPTIONAL")
    print(f"[{status:8s}] {what}" + (f" - {detail}" if detail else ""))


def main():
    url = env("DATABASE_URL")
    if not url:
        show("MISSING", "DATABASE_URL")
    else:
        if "pooler.supabase.com" not in url:
            show("WARN", "DATABASE_URL", "not a Session pooler URL; GitHub Actions may fail (IPv6)")
        try:
            from pipeline.common import connect
            conn = connect()
            cur = conn.cursor()
            cur.execute("select extname from pg_extension")
            ext = {r[0] for r in cur.fetchall()}
            for e in ("postgis", "pg_trgm"):
                show("OK" if e in ext else "FAIL", f"extension {e}", "" if e in ext else "run db/schema.sql")
            cur.execute("select tablename, rowsecurity from pg_tables where schemaname='public'")
            tabs = dict(cur.fetchall())
            for t in TABLES:
                if t not in tabs:
                    show("FAIL", f"table {t}", "run db/schema.sql")
                elif not tabs[t]:
                    show("FAIL", f"table {t}", "RLS is off")
            if all(t in tabs for t in TABLES):
                show("OK", "tables + RLS")
            cur.execute("select (select count(*) from wilayah), (select count(*) from zona), "
                        "(select count(*) from item), (select count(*) from skor)")
            w, z, i, s = cur.fetchone()
            show("OK" if w and z else "FAIL", "config synced", f"{w} wilayah, {z} zona" + ("" if w else " - run python -m pipeline.sync_config"))
            show("OK", "data", f"{i} item, {s} skor")
            conn.close()
        except Exception as e:
            show("FAIL", "database connection", str(e).splitlines()[0])

    from pipeline import extract_llm
    if extract_llm.available():
        res = extract_llm.ask_json('Balas JSON {"ok": true}', retries=0)
        show("OK" if res else "FAIL", "LLM (Gemini/Groq)", "" if res else "key invalid or rate limited")
    else:
        show("MISSING", "GEMINI_API_KEY or GROQ_API_KEY", "needed for promo + place extraction")

    if env("YOUTUBE_API_KEY"):
        from pipeline.common import http
        r = http().get("https://www.googleapis.com/youtube/v3/videos",
                       params={"key": env("YOUTUBE_API_KEY"), "part": "id", "id": "dQw4w9WgXcQ"}, timeout=20)
        show("OK" if r.ok else "FAIL", "YOUTUBE_API_KEY", "" if r.ok else r.text[:120])
    else:
        show("MISSING", "YOUTUBE_API_KEY", "viral signals will rely on news/Reddit/reports only")

    for k, why in [("TELEGRAM_BOT_TOKEN", "notifications"), ("REDDIT_CLIENT_ID", "Reddit signal"),
                   ("CONTACT_EMAIL", "polite User-Agent for Nominatim/Overpass")]:
        show("OK" if env(k) else "OPTIONAL", k, "" if env(k) else why)

    print("\nAll required items OK." if ok else "\nFix the items above, then run again.")


if __name__ == "__main__":
    main()
