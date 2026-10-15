"""IDX stock prices + related news (every 30 min on trading days).
python -m collectors.saham

Prices: a Google Sheet that uses GOOGLEFINANCE (free, ~20 min delayed),
published as CSV (see templates/ and README). Two published sheets:
  saham.csv_kutipan   one row per stock: price, change, %, volume, ...
  saham.csv_riwayat   daily closes of the last ~70 days, one block per stock
News: official market RSS feeds; headlines that name a watched stock are kept,
"rekomendasi"/target-price style headlines are skipped (this site gives no advice).
"""
import csv
import io
import re
from datetime import datetime, timedelta, timezone

import feedparser
import yaml

from pipeline.common import ROOT, WIB, clean_html, db, http, load_config, log, now_utc

KOSONG = ("", "#n/a", "#value!", "#ref!", "#error!", "loading...", "n/a", "-")


def angka(s):
    """'9,875.00' / '1.23' / '#N/A' -> float or None (sheet locale must be United States)."""
    t = (s or "").strip()
    if t.lower() in KOSONG or t.startswith("#"):
        return None
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def waktu(s):
    t = (s or "").strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(t, f).replace(tzinfo=WIB)
        except ValueError:
            pass
    return None


def tanggal(s):
    t = (s or "").strip()
    for f in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def parse_kutipan(text):
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        kode = (row.get("kode") or "").strip().upper()
        harga = angka(row.get("harga"))
        if not kode or harga is None:
            continue
        out.append({
            "kode": kode, "nama": (row.get("nama") or "").strip() or None, "harga": harga,
            "perubahan": angka(row.get("perubahan")), "persen": angka(row.get("persen")),
            "volume": angka(row.get("volume")), "tertinggi": angka(row.get("tertinggi")),
            "terendah": angka(row.get("terendah")), "buka": angka(row.get("buka")),
            "tutup_kemarin": angka(row.get("tutup_kemarin")), "waktu": waktu(row.get("waktu")),
        })
    return out


def parse_riwayat(text):
    """Row 1 holds the stock code above each 3-column block; GOOGLEFINANCE spills
    'Date','Close' + rows below it. -> [(kode, date, close)]"""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    out = []
    for c, kode in enumerate(rows[0]):
        kode = kode.strip().upper()
        if not kode:
            continue
        for r in rows[1:]:
            if len(r) <= c + 1:
                continue
            d, v = tanggal(r[c]), angka(r[c + 1])
            if d and v is not None:
                out.append((kode, d, v))
    return out


def pola_saham(daftar):
    """Matchers: tickers and all-caps keywords are case-sensitive ('BUKA' != 'buka'),
    other keywords ('Telkom') are case-insensitive whole words."""
    out = []
    for s in daftar:
        kata = [s["kode"]] + list(s.get("kata_kunci") or [])
        for k in kata:
            flags = 0 if k.isupper() else re.I
            out.append((s["kode"], re.compile(rf"(?<![\w-]){re.escape(k)}(?![\w-])", flags)))
    return out


def kode_disebut(teks, pola):
    found = []
    for kode, rx in pola:
        if kode not in found and rx.search(teks):
            found.append(kode)
    return found


def daftar_saham():
    with open(ROOT / "config" / "saham.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f).get("saham", [])


def ambil_csv(url):
    r = http().get(url, timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def main():
    cfg = load_config("sources").get("saham", {})
    daftar = daftar_saham()
    info = {s["kode"]: s for s in daftar}
    with db() as cur:
        if cfg.get("csv_kutipan"):
            try:
                rows = parse_kutipan(ambil_csv(cfg["csv_kutipan"]))
            except Exception as e:
                log(f"saham kutipan: gagal ({e})")
                rows = []
            for r in rows:
                s = info.get(r["kode"], {})
                cur.execute(
                    """insert into saham (kode, nama, sektor, harga, perubahan, persen, volume, tertinggi, terendah,
                                          buka, tutup_kemarin, waktu_data, diperbarui)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                       on conflict (kode) do update set nama=excluded.nama, sektor=excluded.sektor, harga=excluded.harga,
                         perubahan=excluded.perubahan, persen=excluded.persen, volume=excluded.volume,
                         tertinggi=excluded.tertinggi, terendah=excluded.terendah, buka=excluded.buka,
                         tutup_kemarin=excluded.tutup_kemarin, waktu_data=excluded.waktu_data, diperbarui=now()""",
                    (r["kode"], s.get("nama") or r["nama"] or r["kode"], s.get("sektor"), r["harga"], r["perubahan"],
                     r["persen"], r["volume"], r["tertinggi"], r["terendah"], r["buka"], r["tutup_kemarin"], r["waktu"]))
                hari = (r["waktu"] or now_utc().astimezone(WIB)).date()
                cur.execute("""insert into saham_harian (kode, tanggal, close) values (%s,%s,%s)
                               on conflict (kode, tanggal) do update set close=excluded.close""", (r["kode"], hari, r["harga"]))
            log(f"saham kutipan: {len(rows)} saham diperbarui")
        else:
            log("saham: csv_kutipan belum diisi di config/sources.yaml, harga dilewati")

        if cfg.get("csv_riwayat"):
            try:
                hist = parse_riwayat(ambil_csv(cfg["csv_riwayat"]))
            except Exception as e:
                log(f"saham riwayat: gagal ({e})")
                hist = []
            for kode, d, v in hist:
                cur.execute("""insert into saham_harian (kode, tanggal, close) values (%s,%s,%s)
                               on conflict (kode, tanggal) do update set close=excluded.close""", (kode, d, v))
            log(f"saham riwayat: {len(hist)} titik harga")

        pola = pola_saham(daftar + [{"kode": "IHSG", "kata_kunci": ["Indeks Harga Saham Gabungan"]}])
        larangan = re.compile(cfg.get("judul_dilewati", r"rekomendasi|target harga|layak (dibeli|dikoleksi)"), re.I)
        batas = now_utc() - timedelta(days=7)
        baru = 0
        for f in cfg.get("rss", []):
            try:
                r = http().get(f["url"], timeout=45)
                r.raise_for_status()
                entries = feedparser.parse(r.content).entries
            except Exception as e:
                log(f"saham berita {f['nama']}: gagal ({e})")
                continue
            for e in entries:
                judul, url = clean_html(e.get("title"), 300), e.get("link")
                if not judul or not url or larangan.search(judul):
                    continue
                kode = kode_disebut(f"{judul} {clean_html(e.get('summary'), 400)}", pola)
                if not kode:
                    continue
                t = e.get("published_parsed")
                terbit = datetime(*t[:6], tzinfo=timezone.utc) if t else None
                if terbit and terbit < batas:
                    continue
                cur.execute("""insert into saham_berita (url, judul, sumber, terbit, kode) values (%s,%s,%s,coalesce(%s, now()),%s)
                               on conflict (url) do nothing""", (url, judul, f["nama"], terbit, kode))
                baru += cur.rowcount
        log(f"saham berita: {baru} baru")


if __name__ == "__main__":
    main()
