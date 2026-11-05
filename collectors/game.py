"""Game tab (hourly).  python -m collectors.game

- game news from Indonesian and English RSS feeds: headline + a short summary + link
  (copyright: never the article). The LLM sorts each story into a category and
  translates English ones to Indonesian.
- Steam store lists in rupiah: top sellers and current discounts.
"""
from datetime import datetime, timezone

import feedparser

from collectors.china import terbaru
from pipeline import extract_llm
from pipeline.common import clean_html, db, http, load_config, log
from pipeline.gambar import dari_entri

KATEGORI = ("pc", "konsol", "mobile", "esports", "hardware", "industri", "lainnya")

PROMPT = """Berikut berita seputar game. Untuk setiap berita:
- "judul": judul dalam Bahasa Indonesia yang natural, maksimal 120 karakter. Jika judul sudah berbahasa Indonesia, salin apa adanya.
- "ringkasan": 1-2 kalimat (maks 240 karakter) dalam Bahasa Indonesia HANYA dari judul + ringkasan yang diberikan, jangan menambah fakta
- "kategori": "pc" (game PC, Steam, Epic), "konsol" (PlayStation, Xbox, Nintendo), "mobile" (game Android/iOS, mis. Mobile Legends,
  Free Fire, Genshin), "esports" (turnamen, tim, atlet), "hardware" (GPU, CPU, laptop, perangkat gaming), "industri" (studio,
  penerbit, PHK, akuisisi, penjualan, regulasi), atau "lainnya" (film/anime/hiburan non-game). Game yang rilis di banyak platform:
  pilih platform yang paling ditekankan, atau "pc" jika setara.
Nama game, studio, orang, dan produk jangan diterjemahkan. Istilah game yang lazim (remake, DLC, early access, battle pass,
patch, update) biarkan dalam bahasa Inggris. Salin angka, harga, dan tanggal persis.
Kembalikan JSON: {{"hasil": [{{"no": 1, "judul": "...", "ringkasan": "...", "kategori": "pc"}}]}}

{lines}"""


def olah(rows):
    """rows: [(id, judul, ringkasan, bahasa)] -> {id: (judul_id, ringkasan_id, kategori)}; {} if the LLM failed."""
    lines = "\n".join(f"{n + 1}. {j} -- {(r or '')[:400]}" for n, (_, j, r, _b) in enumerate(rows))
    data = extract_llm.ask_json(PROMPT.format(lines=lines))
    out = {}
    for h in (data.get("hasil", []) if isinstance(data, dict) else []):
        try:
            n = int(h.get("no")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= n < len(rows):
            continue
        rid, judul_asli, _, bahasa = rows[n]
        judul = judul_asli if bahasa == "id" else extract_llm._short(h.get("judul"), 160)
        if judul:
            kat = h.get("kategori") if h.get("kategori") in KATEGORI else "lainnya"
            out[rid] = (judul, extract_llm._short(h.get("ringkasan"), 300), kat)
    return out


def harga(v):
    """Steam price in cents of a rupiah -> rupiah, None when absent."""
    return None if v is None else int(v) // 100


def steam_rows(data):
    """featuredcategories JSON -> [(daftar, app_id, urut, nama, harga_awal, harga, diskon, gambar, berakhir)]."""
    out = []
    for daftar, key in (("terlaris", "top_sellers"), ("diskon", "specials")):
        seen = set()
        for it in (data.get(key) or {}).get("items") or []:
            app, nama = it.get("id"), (it.get("name") or "").strip()
            if not app or not nama or app in seen:
                continue
            if daftar == "diskon" and not it.get("discount_percent"):
                continue
            seen.add(app)
            akhir = it.get("discount_expiration")
            out.append((daftar, int(app), len(seen), nama[:200], harga(it.get("original_price")), harga(it.get("final_price")),
                        int(it.get("discount_percent") or 0), it.get("large_capsule_image") or it.get("header_image"),
                        datetime.fromtimestamp(akhir, timezone.utc) if akhir else None))
    return out


def steam(cur, cfg):
    url = (cfg.get("steam") or {}).get("url")
    if not url:
        return
    try:
        r = http().get(url, timeout=30)
        r.raise_for_status()
        rows = steam_rows(r.json())
    except Exception as ex:
        log(f"game steam: gagal ({ex})")
        return
    if not rows:
        log("game steam: daftar kosong, data lama dipertahankan")
        return
    cur.execute("delete from game_steam")
    for row in rows:
        cur.execute("""insert into game_steam (daftar, app_id, urut, nama, harga_awal, harga, diskon, gambar, berakhir)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""", row)
    log(f"game steam: {len(rows)} game")


def main():
    cfg = load_config("sources").get("game", {})
    now = datetime.now(timezone.utc)
    baru = 0
    with db() as cur:
        steam(cur, cfg)
        cur.connection.commit()
        kat_feed = {f["nama"]: f.get("kategori") for f in cfg.get("rss", [])}
        for f in cfg.get("rss", []):
            try:
                r = http().get(f["url"], timeout=40)
                r.raise_for_status()
                entries = feedparser.parse(r.content).entries
            except Exception as ex:
                log(f"game {f['nama']}: gagal ({ex})")
                continue
            for terbit, e in terbaru(entries, now, int(cfg.get("max_hari", 3)), int(f.get("maks", cfg.get("maks_per_feed", 10)))):
                cur.execute(
                    """insert into game_berita (url, sumber, bahasa, judul_asli, ringkasan_asli, terbit, gambar)
                       values (%s,%s,%s,%s,%s,%s,%s) on conflict (url) do nothing""",
                    (e["link"], f["nama"], f.get("bahasa", "id"), clean_html(e.get("title"), 300),
                     clean_html(e.get("summary") or e.get("description"), 400), terbit, dari_entri(e)))
                baru += cur.rowcount
        cur.connection.commit()
        log(f"game: {baru} berita baru")

        if not extract_llm.available():
            log("game: GEMINI_API_KEY / GROQ_API_KEY belum diisi, kategori & terjemahan dilewati")
            return
        cur.execute("""select id, judul_asli, ringkasan_asli, bahasa, sumber from game_berita where judul_id is null
                       and terbit > now() - interval '3 days' order by terbit desc limit %s""",
                    (int(cfg.get("terjemah_per_run", 40)),))
        todo, ok = cur.fetchall(), 0
        for i in range(0, len(todo), 10):
            part = todo[i:i + 10]
            hasil = olah([r[:4] for r in part])
            if not hasil:
                log("game: LLM gagal/kuota, sisa diproses run berikutnya")
                break
            sumber = {r[0]: r[4] for r in part}
            for rid, (judul, ringkas, kat) in hasil.items():
                cur.execute("update game_berita set judul_id=%s, ringkasan_id=%s, kategori=%s where id=%s",
                            (judul, ringkas, kat_feed.get(sumber[rid]) or kat, rid))
                ok += 1
            cur.connection.commit()
        log(f"game: {ok}/{len(todo)} diberi kategori/diterjemahkan")


if __name__ == "__main__":
    main()
