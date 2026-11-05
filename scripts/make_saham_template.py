"""Write templates/saham.csv and templates/riwayat.csv for Google Sheets.
python scripts/make_saham_template.py

Import both into ONE Google Sheet (two tabs) with locale "United States",
then publish each tab as CSV - see README "Saham".
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collectors.saham import daftar_saham  # noqa: E402

IHSG = ("IHSG", "IDX:COMPOSITE")
KURS = ("USDIDR", "CURRENCY:USDIDR")   # GOOGLEFINANCE gives currencies a price only; the site derives the change from history


def main():
    saham = [(s["kode"], f"IDX:{s['kode']}") for s in daftar_saham()]
    rows = [IHSG, KURS] + saham
    out = ROOT / "templates"
    out.mkdir(exist_ok=True)
    kolom = [("nama", "name"), ("harga", "price"), ("perubahan", "change"), ("persen", "changepct"),
             ("volume", "volume"), ("tertinggi", "high"), ("terendah", "low"), ("buka", "priceopen"),
             ("tutup_kemarin", "closeyest")]
    with open(out / "saham.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kode", "simbol"] + [k for k, _ in kolom] + ["waktu"])
        for i, (kode, simbol) in enumerate(rows, start=2):
            if simbol.startswith("CURRENCY:"):   # currencies only answer the bare call (no attributes)
                w.writerow([kode, simbol, "Dolar AS ke Rupiah", f'=IFERROR(GOOGLEFINANCE(B{i}),"")'] + [""] * (len(kolom) - 1))
                continue
            w.writerow([kode, simbol] + [f'=IFERROR(GOOGLEFINANCE(B{i},"{a}"),"")' for _, a in kolom]
                       + [f'=IFERROR(TEXT(GOOGLEFINANCE(B{i},"tradetime"),"yyyy-mm-dd hh:mm"),"")'])
    # history: one 3-column block per stock; row 1 = code, row 2 = spilling formula
    head, form = [], []
    for kode, simbol in rows:
        head += [kode, "", ""]
        form += [f'=IFERROR(GOOGLEFINANCE("{simbol}","close",TODAY()-70,TODAY(),"DAILY"),"")', "", ""]
    with open(out / "riwayat.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerow(form)
    print(f"templates/saham.csv + templates/riwayat.csv: {len(rows)} baris (IHSG + USD/IDR + {len(saham)} saham)")


if __name__ == "__main__":
    main()
