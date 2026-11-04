"""English versions of news cards, for the site's EN language switch.
    python -m pipeline.terjemah          # Berita tab (item)
    python -m pipeline.terjemah china    # China tab (berita_china)
    python -m pipeline.terjemah saham    # Saham tab (saham_berita)

Translates what the card already shows (headline, key points, or the RSS lead
when there are no key points) from our stored Indonesian text into English,
once per story. Nothing is fetched from publishers here. Stories the LLM skips
keep en_at set and show in Indonesian; a failed call (quota) is retried next run.
"""
import re
import sys

from pipeline import extract_llm
from pipeline.common import db, env, log

PER_CALL = 10
MAKS_LEAD = 300
# a reply still in Indonesian, or with stray non-Latin script, is not used
ASING = re.compile(r"[Ѐ-ӿ֐-ۿऀ-෿฀-໿ᄀ-ᇿ가-힯]")
INDO = re.compile(r"\b(yang|dengan|untuk|dari|tidak|akan|sudah|adalah|ini|itu|dan)\b", re.I)

PROMPT = """Translate these Indonesian news card texts into natural, concise British English for an international reader.
Rules:
- translate faithfully; do not add, drop or explain facts; keep the values of numbers, dates and money exactly
- write numbers the English way: decimal point and thousands comma (Rp 520,5 juta -> Rp520.5 million, 20.980 -> 20,980, Rp330 ribu -> Rp330,000)
- police and military ranks: keep the Indonesian rank (Irjen, Kombes, Mayjen) rather than guessing an English one
- keep names of people, places, companies, products and institutions as written (e.g. Jalan Sudirman, Pemprov DKI -> "the Jakarta provincial government" is fine, BMKG stays BMKG)
- "poin" must have the same number of items as the input, in the same order
- write "China" (never "Tiongkok")
Return JSON: {{"hasil": [{{"no": 1, "judul": "...", "poin": ["..."], "ringkasan": "..."}}]}}
Leave out "poin" or "ringkasan" when the input has none.

{lines}"""

# per target: rows to do (id, judul, ringkasan, inti) in Indonesian, and where the English goes
TARGET = {
    "berita": (
        """select id, judul, case when inti is null then ringkasan end, inti from item
           where tipe in ('berita','info') and en_at is null and published_at > now() - make_interval(days => %s)
             and (inti_at is not null or tipe = 'info' or url not like 'http%%' or published_at < now() - interval '3 hours')
           order by published_at desc limit %s""",
        "update item set judul_en = %s, ringkasan_en = %s, inti_en = %s, en_at = now() where id = %s"),
    "china": (
        """select id, judul_id, case when inti is null then ringkasan_id end, inti from berita_china
           where en_at is null and judul_id is not null and terbit > now() - make_interval(days => %s)
             and (inti_at is not null or terbit < now() - interval '3 hours')
           order by terbit desc limit %s""",
        "update berita_china set judul_en = coalesce(judul_en, %s), ringkasan_en = coalesce(ringkasan_en, %s), inti_en = %s, en_at = now() where id = %s"),
    "saham": (
        """select id, judul, null, null from saham_berita
           where en_at is null and terbit > now() - make_interval(days => %s)
           order by terbit desc limit %s""",
        "update saham_berita set judul_en = %s, en_at = now() where id = %s"),
}
# English-language China sources: the original headline and lead are already English
CHINA_ASLI = """update berita_china set judul_en = judul_asli, ringkasan_en = left(ringkasan_asli, 400)
                where bahasa = 'en' and judul_en is null and judul_id is not null"""


def bersih(v, n):
    """One clean English line, or None when empty, too long, or still Indonesian/garbled."""
    if not isinstance(v, str):
        return None
    t = " ".join(v.split())[:n]
    if len(t) < 3 or ASING.search(t) or len(INDO.findall(t)) >= 2:
        return None
    return t


def terjemah(rows):
    """rows: [(id, judul, ringkasan, inti)] -> {id: (judul, ringkasan, inti)}; None if the LLM failed."""
    blok = []
    for n, (_, judul, lead, inti) in enumerate(rows):
        s = f"### {n + 1}\njudul: {judul}"
        if inti:
            s += "\npoin:\n" + "\n".join(f"- {p}" for p in inti.split("\n"))
        elif lead:
            s += f"\nringkasan: {lead[:MAKS_LEAD]}"
        blok.append(s)
    data = extract_llm.ask_json(PROMPT.format(lines="\n\n".join(blok)))
    if not isinstance(data, dict):
        return None
    out = {}
    for h in data.get("hasil", []):
        try:
            n = int(h.get("no")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= n < len(rows):
            continue
        _, judul, lead, inti = rows[n]
        j = bersih(h.get("judul"), 300)
        if not j:
            continue
        poin = None
        if inti and isinstance(h.get("poin"), list):
            ps = [bersih(p, 220) for p in h["poin"]]
            if len(ps) == len(inti.split("\n")) and all(ps):
                poin = "\n".join(ps)
        r = bersih(h.get("ringkasan"), 400) if lead and not inti else None
        out[rows[n][0]] = (j, r, poin)
    return out


def main(target="berita"):
    pilih, simpan = TARGET[target]
    with db() as cur:
        if target == "china":
            cur.execute(CHINA_ASLI)
            cur.connection.commit()
        if not extract_llm.available():
            log("terjemah: GEMINI_API_KEY / GROQ_API_KEY belum diisi, dilewati")
            return
        cur.execute(pilih, (int(env("TERJEMAH_HARI", 3)), int(env("TERJEMAH_PER_RUN", 60))))
        todo, ok = cur.fetchall(), 0
        for i in range(0, len(todo), PER_CALL):
            part = todo[i:i + PER_CALL]
            hasil = terjemah(part)
            if hasil is None:
                log("terjemah: LLM gagal/kuota, sisa dicoba run berikutnya")
                break
            for row in part:
                j, r, p = hasil.get(row[0], (None, None, None))
                cur.execute(simpan, (j, row[0]) if target == "saham" else (j, r, p, row[0]))
                ok += bool(j)
            cur.connection.commit()
        log(f"terjemah {target}: {ok} diterjemahkan dari {len(todo)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "berita")
