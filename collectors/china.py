"""China news mirror (hourly).  python -m collectors.china

Reads China tech / business / policy feeds (English and Mandarin), stores the
original headline + a short summary + link, and lets the LLM translate them to
Indonesian. Only headline and a 1-2 sentence summary are kept (copyright): the
reader follows the link for the full article.
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup

from pipeline import extract_llm
from pipeline.common import clean_html, db, http, load_config, log
from pipeline.gambar import dari_entri

KATEGORI = ("teknologi", "bisnis", "kebijakan", "sosial", "fnb", "lainnya")
JENIS_SUMBER = ("negara", "swasta", "agregator")

PROMPT = """Terjemahkan berita berikut ke Bahasa Indonesia yang natural (sumber: media China atau media yang
meliput China; bahasa Inggris atau Mandarin). Untuk setiap berita:
- "judul": terjemahan judul, maksimal 120 karakter
- "ringkasan": 1-2 kalimat (maks 240 karakter) HANYA dari judul + ringkasan yang diberikan, jangan menambah fakta
- "kategori": "teknologi" (AI, chip, gadget, EV, internet, sains), "bisnis" (perusahaan, pasar, saham, ekonomi, perdagangan),
  "kebijakan" (pemerintah, regulasi, politik, hubungan internasional), "sosial" (masyarakat, budaya, gaya hidup),
  "fnb" (restoran, makanan/minuman, brand F&B, franchise/waralaba, pembukaan gerai), atau "lainnya"
- berita bertanda [SARING]: kategori "fnb" HANYA jika tentang industri F&B China atau brand F&B asal China (termasuk
  ekspansinya ke luar negeri, mis. Mixue, Chagee, Luckin); selain itu (mis. restoran Jepang, startup teknologi) "buang"
Nama perusahaan, orang, dan produk jangan diterjemahkan; untuk nama Mandarin tulis nama Latinnya (mis. 美团 -> Meituan).
Selalu tulis "China" (bukan "Tiongkok"). Istilah teknis/keuangan tanpa padanan baku biarkan dalam bahasa Inggris
(mis. "tokenised deposit", "large language model", "chip foundry").
PENTING: salin angka, harga, tanggal, nomor model, dan nama produk PERSIS seperti teks asli - jangan diubah, ditebak,
atau "dikoreksi" ke produk lain (mis. "ROG 术士 98 X" tetap "ROG 术士 98 X" atau "ROG Shushi 98 X", bukan model lain).
Satuan angka Mandarin: 万 = 10.000 dan 亿 = 100.000.000, jadi 80万 = 800 ribu, 1.5万 = 15 ribu, 3亿 = 300 juta,
2万家门店 = 20 ribu gerai. Hitung dengan teliti; jangan menulis "juta" untuk 万.
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


def terjemahkan(rows, saring=()):
    """rows: [(id, judul, ringkasan)] -> {id: (judul_id, ringkasan_id, kategori)}; {} if the LLM failed.
    Ids in `saring` may come back as "buang" (not China F&B): the caller marks those so they are not
    fetched again. The LLM often just leaves such rows out, so a [SARING] row missing from a valid
    answer counts as "buang" too."""
    lines = "\n".join(f"{n + 1}. {'[SARING] ' if i in saring else ''}{j} -- {(r or '')[:400]}"
                      for n, (i, j, r) in enumerate(rows))
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
            if rows[n][0] in saring and h.get("kategori") != "fnb":
                kat = "buang"
            out[rows[n][0]] = (judul, extract_llm._short(h.get("ringkasan"), 300), kat)
    if isinstance(data, dict) and isinstance(data.get("hasil"), list):
        for i in saring:
            out.setdefault(i, (None, None, "buang"))
    return out


def dari_halaman(html, base, pola, now):
    """Article links on a listing page -> [(terbit, {"link", "title"})], newest first.
    The date comes from the URL (/2026/11/04/ or /2026/1104/) when present, else now."""
    s, seen, out = BeautifulSoup(html or "", "html.parser"), {}, []
    host = urlparse(base).netloc
    for a in s.find_all("a", href=True):
        u, judul = urlparse(urljoin(base, a["href"])), " ".join(a.get_text(" ", strip=True).split())
        path = u.path
        if u.netloc == host and re.match(pola, path) and len(judul) >= 8 and len(judul) > len(seen.get(path, "")):
            seen[path] = judul                              # the same link often appears twice, keep the longer text
    for path, judul in seen.items():
        m = re.search(r"/(\d{4})/(\d{2})/?(\d{2})/", path)
        terbit = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc) if m else now
        out.append((min(terbit, now), {"link": urljoin(base, path), "title": judul.rstrip("…").rstrip(".") if judul.endswith(("…", "...")) else judul,
                                       "potong": judul.endswith(("…", "..."))}))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def judul_lengkap(url):
    """Full headline from the article page (listing pages cut long titles with "…")."""
    try:
        r = http().get(url, timeout=20)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        s = BeautifulSoup(r.text, "html.parser")
        og = s.find("meta", property="og:title")
        t = (og and og.get("content")) or (s.h1 and s.h1.get_text(" ", strip=True)) or ""
        return " ".join(t.split())[:300] or None
    except Exception:
        return None


def main():
    cfg = load_config("sources").get("china", {})
    halaman = cfg.get("halaman", [])
    mode_fnb = {f["nama"]: f.get("fnb") for f in cfg.get("rss", []) + halaman}
    now = datetime.now(timezone.utc)
    baru = 0
    with db() as cur:
        # keep the source-type label in sync with config (also fixes rows stored earlier)
        for f in cfg.get("rss", []) + halaman:
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
                    """insert into berita_china (url, sumber, bahasa, judul_asli, ringkasan_asli, kategori, jenis_sumber, terbit, gambar)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (url) do nothing""",
                    (e["link"], f["nama"], f.get("bahasa", "en"), clean_html(e.get("title"), 300),
                     clean_html(e.get("summary") or e.get("description"), 400), f.get("kategori"), f.get("jenis"), terbit,
                     dari_entri(e)))
                baru += cur.rowcount
        for f in halaman:
            try:
                r = http().get(f["url"], timeout=40)
                r.raise_for_status()
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                items = dari_halaman(r.text, f["url"], f["pola"], now)
            except Exception as ex:
                log(f"china {f['nama']}: gagal ({ex})")
                continue
            batas = now - timedelta(days=int(cfg.get("max_hari", 3)))
            for terbit, e in [x for x in items if x[0] >= batas][:int(f.get("maks", cfg.get("maks_per_feed", 6)))]:
                cur.execute("select 1 from berita_china where url = %s", (e["link"],))
                if cur.fetchone():
                    continue
                judul = (judul_lengkap(e["link"]) if e["potong"] else None) or e["title"]
                cur.execute(
                    """insert into berita_china (url, sumber, bahasa, judul_asli, kategori, jenis_sumber, terbit)
                       values (%s,%s,%s,%s,%s,%s,%s) on conflict (url) do nothing""",
                    (e["link"], f["nama"], f.get("bahasa", "zh"), judul[:300], f.get("kategori"), f.get("jenis"), terbit))
                baru += cur.rowcount
        log(f"china: {baru} berita baru")

        if not extract_llm.available():
            log("china: GEMINI_API_KEY / GROQ_API_KEY belum diisi, terjemahan dilewati")
            return
        cur.execute("""select id, judul_asli, ringkasan_asli, sumber from berita_china where judul_id is null
                       and kategori is distinct from 'buang'
                       and terbit > now() - interval '3 days' order by terbit desc limit %s""",
                    (int(cfg.get("terjemah_per_run", 40)),))
        todo = cur.fetchall()
        ok = buang = 0
        for i in range(0, len(todo), 8):
            part = todo[i:i + 8]
            hasil = terjemahkan([r[:3] for r in part], {r[0] for r in part if mode_fnb.get(r[3]) == "saring"})
            if not hasil:
                log("china: LLM gagal/kuota, sisa diterjemahkan run berikutnya")
                break
            sumber = {r[0]: r[3] for r in part}
            for rid, (judul, ringkas, kat) in hasil.items():
                if kat == "buang":                          # not China F&B: keep as a marker so it is not fetched again
                    cur.execute("update berita_china set kategori = 'buang' where id = %s", (rid,))
                    buang += 1
                    continue
                if mode_fnb.get(sumber[rid]) == "semua":    # F&B-only site
                    kat = "fnb"
                cur.execute("update berita_china set judul_id=%s, ringkasan_id=%s, kategori=%s where id=%s",
                            (judul, ringkas, kat, rid))
                ok += 1
            cur.connection.commit()
        log(f"china: {ok}/{len(todo)} diterjemahkan, {buang} dibuang (bukan F&B China)")


if __name__ == "__main__":
    main()
