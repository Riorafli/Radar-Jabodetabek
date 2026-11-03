"""Key points ("inti berita") for news cards.  python -m pipeline.inti

For new news items: fetch the article page, extract its text, and let the LLM
write 2-4 short points in its own words, so readers get the gist on the site
and can still open the source. Only the points are stored, never the article.

Sites are skipped when robots.txt disallows our bot or any AI crawler
(Google-Extended, GPTBot, ClaudeBot, CCBot, ...): those publishers opted out of
AI use, so their cards keep the RSS lead only.
"""
import json
import re
import urllib.robotparser
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from pipeline import extract_llm
from pipeline.common import db, env, http, log, user_agent

AI_BOTS = ("Google-Extended", "GPTBot", "ClaudeBot", "anthropic-ai", "CCBot")
MAKS_TEKS = 4000          # characters of article text sent to the LLM
BUANG = re.compile(r"baca juga|simak juga|lihat juga|ikuti (kami|berita)|whatsapp|google news|copyright|©", re.I)

PROMPT = """Buat inti dari setiap berita berikut untuk pembaca yang tidak membuka artikelnya.
Untuk setiap berita tulis 2-4 poin singkat (masing-masing maksimal 160 karakter) dalam Bahasa Indonesia:
- dengan kata-kata sendiri, JANGAN menyalin kalimat dari artikel
- hanya fakta yang ada di teks: siapa, apa, di mana, kapan, angka penting, dan dampaknya bagi warga
- jangan menambah opini, tebakan, atau fakta dari luar teks; salin angka, nama, dan tanggal persis
- lewati iklan, ajakan "baca juga", dan info redaksi
Kembalikan JSON: {{"hasil": [{{"no": 1, "poin": ["...", "..."]}}]}}

{lines}"""


def boleh_ai(robots_txt, url):
    """True if robots.txt lets our bot AND every AI crawler fetch this URL."""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse((robots_txt or "").splitlines())
    return all(rp.can_fetch(ua, url) for ua in (user_agent(), *AI_BOTS))


def ekstrak_teks(html):
    """Article body text: JSON-LD articleBody when present, else the article's paragraphs."""
    s = BeautifulSoup(html or "", "html.parser")
    for tag in s.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(tag.string or "")
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            if isinstance(x, dict) and isinstance(x.get("articleBody"), str) and len(x["articleBody"]) > 300:
                return " ".join(x["articleBody"].split())[:MAKS_TEKS]
    for t in s(["script", "style", "nav", "header", "footer", "aside", "figure", "form"]):
        t.decompose()
    root = s.find("article") or s.body or s
    ps = [" ".join(p.get_text(" ", strip=True).split()) for p in root.find_all("p")]
    return " ".join(p for p in ps if len(p) > 50 and not BUANG.search(p))[:MAKS_TEKS]


def rapikan_poin(v):
    """LLM output -> list of 2-4 clean points, or [] when unusable."""
    if not isinstance(v, list):
        return []
    out = [" ".join(str(p).split()).lstrip("-•* ")[:200] for p in v if isinstance(p, (str, int, float))]
    out = [p for p in out if len(p) >= 15][:4]
    return out if len(out) >= 2 else []


def ringkas(rows):
    """rows: [(id, judul, teks)] -> {id: [poin, ...]}; {} if the LLM failed."""
    lines = "\n\n".join(f"### {n + 1}. {j}\n{t}" for n, (_, j, t) in enumerate(rows))
    data = extract_llm.ask_json(PROMPT.format(lines=lines))
    out = {}
    for h in (data.get("hasil", []) if isinstance(data, dict) else []):
        try:
            n = int(h.get("no")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        poin = rapikan_poin(h.get("poin"))
        if 0 <= n < len(rows) and poin:
            out[rows[n][0]] = poin
    return out


def main():
    if not extract_llm.available():
        log("inti: GEMINI_API_KEY / GROQ_API_KEY belum diisi, dilewati")
        return
    s, robots = http(), {}
    with db() as cur:
        cur.execute("""select id, judul, url from item where tipe = 'berita' and inti_at is null and url like 'http%%'
                       and published_at > now() - interval '2 days' order by published_at desc limit %s""",
                    (int(env("INTI_PER_RUN", 20)),))
        todo, siap = cur.fetchall(), []
        for rid, judul, url in todo:
            host = urlparse(url).netloc
            if host not in robots:
                try:
                    r = s.get(f"https://{host}/robots.txt", timeout=10)
                    robots[host] = r.text if r.status_code == 200 else ""
                except Exception:
                    robots[host] = ""
            teks = ""
            if boleh_ai(robots[host], url):
                try:
                    r = s.get(url, timeout=15)
                    if r.status_code == 200:
                        teks = ekstrak_teks(r.text)
                except Exception as e:
                    log(f"inti: gagal ambil {url[:80]}: {e}")
            if len(teks) < 300:   # opted out, blocked, or no article text: keep the RSS lead
                cur.execute("update item set inti_at = now() where id = %s", (rid,))
            else:
                siap.append((rid, judul, teks))
        cur.connection.commit()
        ok = 0
        for i in range(0, len(siap), 5):
            part = siap[i:i + 5]
            hasil = ringkas(part)
            if not hasil:
                log("inti: LLM gagal/kuota, sisa dicoba run berikutnya")
                break
            for rid, _, _ in part:   # items the LLM skipped are not retried
                cur.execute("update item set inti = %s, inti_at = now() where id = %s",
                            ("\n".join(hasil[rid]) if rid in hasil else None, rid))
                ok += rid in hasil
            cur.connection.commit()
        log(f"inti: {ok} diringkas, {len(todo) - len(siap)} dilewati (tanpa teks/opt-out), dari {len(todo)}")


if __name__ == "__main__":
    main()
