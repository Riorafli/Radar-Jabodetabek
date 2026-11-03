"""Hoax check for the Berita tab (every news run).  python -m pipeline.cekfakta

1. Press verification: config/media.yaml (Dewan Pers list) -> table media_verif;
   v_berita shows each item's status ("pers"), unlisted sources stay null.
2. Fact-check feed: recent claims rated false / fraud by Indonesian
   fact-checkers (TurnBackHoax by Mafindo, CekFakta.com) -> table hoaks.
3. Matching: the LLM compares new headlines (+ key points) with those claims and
   flags news that REPEATS a debunked claim. News that refutes or clarifies a
   hoax is not flagged. Flags are shown on the card with the fact-check link.
"""
import re
from datetime import datetime, timezone

import feedparser

from pipeline import extract_llm
from pipeline.common import clean_html, db, env, http, load_config, log

# label at the start of a fact-check title: "[SALAH] ..." (TurnBackHoax) or "Salah, ..." (CekFakta)
LABEL = re.compile(r"^\s*(?:\[([^\]]{2,30})\]|(salah|keliru|hoaks|hoax|menyesatkan|penipuan|disinformasi|misinformasi)\s*[,:])\s*", re.I)
BENAR = {"benar", "fakta", "klarifikasi", "edukasi", "fakta/edukasi"}

PROMPT = """Kamu pemeriksa fakta. Di bawah ada daftar KLAIM yang sudah dinyatakan salah/hoaks/penipuan oleh lembaga
cek fakta, dan daftar BERITA dari media. Tandai berita yang MENGULANG atau MENDUKUNG salah satu klaim itu sebagai fakta.
JANGAN tandai berita yang membantah, meluruskan, atau memperingatkan tentang hoaks tersebut, dan jangan tandai berita
yang hanya membahas topik yang sama (mis. sama-sama soal lowongan kerja atau bansos) tanpa memuat klaim palsunya.
Kalau ragu, jangan tandai.
Kembalikan JSON: {{"cocok": [{{"berita": 3, "klaim": 12}}]}} (kosongkan list kalau tidak ada)

KLAIM:
{klaim}

BERITA:
{berita}"""


def pisah_label(judul):
    """'[SALAH] Gaji Guru Naik' -> ('SALAH', 'Gaji Guru Naik'); no label -> (None, judul)."""
    judul = " ".join((judul or "").split())
    m = LABEL.match(judul)
    if not m:
        return None, judul
    return (m.group(1) or m.group(2)).strip().upper(), judul[m.end():].strip()


def sync_media(cur):
    rows = load_config("media").get("media", [])
    for m in rows:
        cur.execute("""insert into media_verif (domain, nama, status, badan, sertifikat) values (%s,%s,%s,%s,%s)
                       on conflict (domain) do update set nama=excluded.nama, status=excluded.status,
                         badan=excluded.badan, sertifikat=excluded.sertifikat""",
                    (m["domain"].lower(), m.get("nama"), m["status"], m.get("badan"), m.get("sertifikat")))
    cur.execute("delete from media_verif where not (domain = any(%s))", ([m["domain"].lower() for m in rows],))
    return len(rows)


def ambil_hoaks(cur, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    s, baru = http(), 0
    for src in cfg.get("feeds", []):
        for url in src["url"] if isinstance(src["url"], list) else [src["url"]]:
            try:
                f = feedparser.parse(s.get(url, timeout=20).content)
            except Exception as e:
                log(f"cekfakta: gagal ambil {url}: {e}")
                continue
            for e in f.entries:
                label, judul = pisah_label(e.get("title"))
                if not label or label.lower() in BENAR or len(judul) < 10 or not e.get("link"):
                    continue
                t = e.get("published_parsed") or e.get("updated_parsed")
                terbit = datetime(*t[:6], tzinfo=timezone.utc) if t else now
                cur.execute("""insert into hoaks (url, judul, label, ringkasan, sumber, terbit) values (%s,%s,%s,%s,%s,%s)
                               on conflict (url) do nothing""",
                            (e.link, judul[:300], label, clean_html(e.get("summary"), 300), src["nama"], terbit))
                baru += cur.rowcount
    return baru


def cocokkan(berita, klaim):
    """berita: [(id, judul, inti)], klaim: [(id, judul)] -> {berita_id: klaim_id}; None if the LLM failed."""
    data = extract_llm.ask_json(PROMPT.format(
        klaim="\n".join(f"{n + 1}. {j}" for n, (_, j) in enumerate(klaim)),
        berita="\n".join(f"{n + 1}. {j}" + (f" -- {(i or '').replace(chr(10), ' ')[:300]}" if i else "")
                         for n, (_, j, i) in enumerate(berita))))
    if not isinstance(data, dict):
        return None
    out = {}
    for c in data.get("cocok") or []:
        try:
            b, k = int(c.get("berita")) - 1, int(c.get("klaim")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= b < len(berita) and 0 <= k < len(klaim):
            out[berita[b][0]] = klaim[k][0]
    return out


def main():
    cfg = load_config("sources").get("cekfakta", {})
    with db() as cur:
        n_media = sync_media(cur)
        baru = ambil_hoaks(cur, cfg)
        cur.connection.commit()
        log(f"cekfakta: {n_media} media terverifikasi, {baru} klaim hoaks baru")
        if not extract_llm.available():
            log("cekfakta: GEMINI_API_KEY / GROQ_API_KEY belum diisi, pencocokan dilewati")
            return
        cur.execute("select id, judul from hoaks where terbit > now() - interval '60 days' order by terbit desc limit 80")
        klaim = cur.fetchall()
        # wait for key points (pipeline/inti.py) for up to an hour so the check sees more than the headline
        cur.execute("""select id, judul, inti from item where tipe = 'berita' and cek_at is null
                       and published_at > now() - interval '2 days'
                       and (inti_at is not null or dibuat < now() - interval '1 hour')
                       order by published_at desc limit %s""", (int(env("CEKFAKTA_PER_RUN", 60)),))
        todo = cur.fetchall()
        tanda = 0
        for i in range(0, len(todo), 20):
            part = todo[i:i + 20]
            hasil = cocokkan(part, klaim) if klaim else {}
            if hasil is None:
                log("cekfakta: LLM gagal/kuota, sisa dicek run berikutnya")
                break
            for rid, _, _ in part:
                kid = hasil.get(rid)
                cur.execute("update item set cek_at = now(), hoaks_id = %s where id = %s", (kid, rid))
                tanda += kid is not None
            cur.connection.commit()
        log(f"cekfakta: {len(todo)} berita dicek, {tanda} mirip klaim hoaks")


if __name__ == "__main__":
    main()
