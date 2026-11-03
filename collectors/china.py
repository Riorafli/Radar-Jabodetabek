"""China news mirror (hourly).  python -m collectors.china

Reads China tech / business / policy feeds (English and Mandarin), stores the
original headline + a short summary + link, and lets the LLM translate them to
Indonesian. Only headline and a 1-2 sentence summary are kept (copyright): the
reader follows the link for the full article.
"""
from datetime import datetime, timedelta, timezone

import feedparser

from pipeline import extract_llm
from pipeline.common import clean_html, db, http, load_config, log

KATEGORI = ("teknologi", "bisnis", "kebijakan", "sosial", "lainnya")
JENIS_SUMBER = ("negara", "swasta", "agregator")

PROMPT = """Terjemahkan berita berikut ke Bahasa Indonesia yang natural (sumber: media China atau media yang
meliput China; bahasa Inggris atau Mandarin). Untuk setiap berita:
- "judul": terjemahan judul, maksimal 120 karakter
- "ringkasan": 1-2 kalimat (maks 240 karakter) HANYA dari judul + ringkasan yang diberikan, jangan menambah fakta
- "kategori": "teknologi" (AI, chip, gadget, EV, internet, sains), "bisnis" (perusahaan, pasar, saham, ekonomi, perdagangan),
  "kebijakan" (pemerintah, regulasi, politik, hubungan internasional), "sosial" (masyarakat, budaya, gaya hidup), atau "lainnya"
Nama perusahaan, orang, dan produk jangan diterjemahkan; untuk nama Mandarin tulis nama Latinnya (mis. 美团 -> Meituan).
Selalu tulis "China" (bukan "Tiongkok"). Istilah teknis/keuangan tanpa padanan baku biarkan dalam bahasa Inggris
(mis. "tokenised deposit", "large language model", "chip foundry").
PENTING: salin angka, harga, tanggal, nomor model, dan nama produk PERSIS seperti teks asli - jangan diubah, ditebak,
atau "dikoreksi" ke produk lain (mis. "ROG 术士 98 X" tetap "ROG 术士 98 X" atau "ROG Shushi 98 X", bukan model lain).
Kembalikan JSON: {{"hasil": [{{"no": 1, "judul": "...", "ringkasan": "...", "kategori": "teknologi"}}]}}

{lines}"""


def terbaru(entries, now, max_hari=3, maks=6):
    """Newest entries first, only the last `max_hari` days, at most `maks`."""
    out = []
    for e in entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        terbit = datetime(*t[:6], tzinfo=timezone.utc) if t else now
        if terbit > now:
            terbit = now
        if terbit >= now - timedelta(days=max_hari) and e.get("link") and e.get("title"):
            out.append((terbit, e))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:maks]


def terjemahkan(rows):
    """rows: [(id, judul, ringkasan)] -> {id: (judul_id, ringkasan_id, kategori)}; {} if the LLM failed."""
    lines = "\n".join(f"{n + 1}. {j} -- {(r or '')[:400]}" for n, (_, j, r) in enumerate(rows))
    data = extract_llm.ask_json(PROMPT.format(lines=lines))
    out = {}
    for h in (data.get("hasil", []) if isinstance(data, dict) else []):
        try:
            n = int(h.get("no")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        judul = extract_llm._short(h.get("judul"), 160)
        if 0 <= n < len(rows) and judul:
            kat = h.get("kategori") if h.get("kategori") in KATEGORI else "lainnya"
            out[rows[n][0]] = (judul, extract_llm._short(h.get("ringkasan"), 300), kat)
    return out


def main():
    cfg = load_config("sources").get("china", {})
    now = datetime.now(timezone.utc)
    baru = 0
    with db() as cur:
        # keep the source-type label in sync with config (also fixes rows stored earlier)
        for f in cfg.get("rss", []):
            cur.execute("update berita_china set jenis_sumber = %s where sumber = %s and jenis_sumber is distinct from %s",
                        (f.get("jenis"), f["nama"], f.get("jenis")))
        for f in cfg.get("rss", []):
            try:
                r = http().get(f["url"], timeout=40)
                r.raise_for_status()
                entries = feedparser.parse(r.content).entries
            except Exception as ex:
                log(f"china {f['nama']}: gagal ({ex})")
                continue
            for terbit, e in terbaru(entries, now, int(cfg.get("max_hari", 3)), int(f.get("maks", cfg.get("maks_per_feed", 6)))):
                cur.execute(
                    """insert into berita_china (url, sumber, bahasa, judul_asli, ringkasan_asli, kategori, jenis_sumber, terbit)
                       values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict (url) do nothing""",
                    (e["link"], f["nama"], f.get("bahasa", "en"), clean_html(e.get("title"), 300),
                     clean_html(e.get("summary") or e.get("description"), 400), f.get("kategori"), f.get("jenis"), terbit))
                baru += cur.rowcount
        log(f"china: {baru} berita baru")

        if not extract_llm.available():
            log("china: GEMINI_API_KEY / GROQ_API_KEY belum diisi, terjemahan dilewati")
            return
        cur.execute("""select id, judul_asli, ringkasan_asli from berita_china where judul_id is null
                       and terbit > now() - interval '3 days' order by terbit desc limit %s""",
                    (int(cfg.get("terjemah_per_run", 40)),))
        todo = cur.fetchall()
        ok = 0
        for i in range(0, len(todo), 8):
            part = todo[i:i + 8]
            hasil = terjemahkan(part)
            if not hasil:
                log("china: LLM gagal/kuota, sisa diterjemahkan run berikutnya")
                break
            for rid, (judul, ringkas, kat) in hasil.items():
                cur.execute("update berita_china set judul_id=%s, ringkasan_id=%s, kategori=%s where id=%s",
                            (judul, ringkas, kat, rid))
                ok += 1
            cur.connection.commit()
        log(f"china: {ok}/{len(todo)} diterjemahkan")


if __name__ == "__main__":
    main()
