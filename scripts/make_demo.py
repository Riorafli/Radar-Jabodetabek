"""Regenerate web/demo.js (sample data for demo mode) from config/*.yaml.
python scripts/make_demo.py
All sample items are fictional and marked "Contoh".
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import ROOT, load_config  # noqa: E402

w = load_config("wilayah")["wilayah"]
z = load_config("zones")["zona"]
zona = [{"id": i + 1, "nama": x["nama"], "alias": x.get("alias", []), "kode_wilayah": x["kota"],
         "lat": x["lat"], "lon": x["lon"], "radius_m": x.get("radius_m", 1500)} for i, x in enumerate(z)]
zid = {x["nama"]: x for x in zona}
wilayah = [{"kode": x["kode"], "nama": x["nama"], "level": x["level"], "lat": x["lat"], "lon": x["lon"]} for x in w]
wn = {x["kode"]: x["nama"] for x in w}


def berita(judul, sumber, menit, zona_nama=None, kode=None, tipe="berita", ringkasan=""):
    zz = zid.get(zona_nama)
    kode = kode or (zz["kode_wilayah"] if zz else None)
    return {"tipe": tipe, "judul": f"[Contoh] {judul}", "url": "https://example.com/", "sumber": sumber,
            "ringkasan": ringkasan, "menit": menit, "zona_id": zz["id"] if zz else None,
            "zona": zona_nama, "kode_wilayah": kode, "wilayah": wn.get(kode)}


BERITA = [
    berita("Peringatan dini hujan lebat disertai petir di Jakarta Selatan dan Depok", "BMKG", 12, kode="31.74", tipe="info",
           ringkasan="Berlaku hingga pukul 18.00 WIB."),
    berita("Antrean panjang di kedai es kopi baru kawasan Blok M", "Contoh Media", 35, "Blok M",
           ringkasan="Pengunjung rela antre hingga satu jam pada akhir pekan."),
    berita("Genangan setinggi 30 cm di Jalan Margonda Raya", "Contoh Media", 50, "Margonda"),
    berita("KRL lintas Bogor alami gangguan, perjalanan tertahan 15 menit", "Contoh Media", 80, kode="32.71", tipe="info"),
    berita("Pasar kuliner malam dibuka di BSD City setiap Jumat-Minggu", "Contoh Media", 140, "BSD City"),
    berita("Rekayasa lalu lintas di sekitar Summarecon Bekasi selama acara akhir pekan", "Contoh Media", 200, "Summarecon Bekasi"),
    berita("Festival kuliner pecinan digelar di Suryakencana", "Contoh Media", 260, "Suryakencana Bogor"),
    berita("Pemkot Tangerang perluas jalur sepeda", "Contoh Media", 320, kode="36.71"),
    berita("Kafe-kafe baru bermunculan di Kemang, warga keluhkan parkir", "Contoh Media", 400, "Kemang"),
    berita("TransJakarta tambah rute ke PIK", "Contoh Media", 480, "PIK", tipe="info"),
]

PROMO = [
    {"brand": "Contoh Kopi", "judul": "Beli 1 gratis 1 semua varian es kopi susu", "menu": "Es kopi susu", "harga": None,
     "harga_teks": "Buy 1 Get 1", "selesai": "2026-10-31", "syarat": "Khusus pembelian via aplikasi, Senin-Jumat.",
     "kota_berlaku": [], "sumber": "Contoh", "sumber_input": "scrape"},
    {"brand": "Contoh Ayam Goreng", "judul": "Paket hemat 2 potong + nasi + minum", "menu": "Paket Hemat", "harga": 35000,
     "harga_teks": None, "selesai": "2026-10-20", "syarat": "Dine-in dan take away.", "kota_berlaku": ["31.74", "32.76"],
     "sumber": "Contoh", "sumber_input": "scrape"},
    {"brand": "Contoh Bank", "judul": "Diskon 30% di restoran Jepang pilihan", "menu": None, "harga": None,
     "harga_teks": "Diskon 30%", "selesai": "2026-11-30", "syarat": "Maks. diskon Rp100.000, kartu kredit.",
     "kota_berlaku": [], "sumber": "Contoh", "sumber_input": "scrape"},
    {"brand": "Contoh Bakmi", "judul": "Bakmi ayam Rp20 ribu saat grand opening", "menu": "Bakmi ayam", "harga": 20000,
     "harga_teks": "Rp20.000", "selesai": "2026-10-12", "syarat": "Hanya outlet BSD.", "kota_berlaku": ["36.74"],
     "sumber": "Kurasi manual", "sumber_input": "manual"},
]

VIRAL = [
    ("Contoh Es Kopi Viral", "Blok M", 3.4, 9, 3, ["berita", "youtube"], (0.003, -0.002)),
    ("Contoh Bakmi Antre", "BSD City", 2.8, 7, 2, ["youtube", "reddit"], (-0.004, 0.006)),
    ("Contoh Dessert Korea", "Kemang", 2.1, 5, 2, ["youtube", "berita"], (0.002, 0.001)),
    ("Contoh Sate Taichan", "Margonda", 1.9, 6, 2, ["youtube", "reddit"], (-0.003, 0.0)),
    ("Contoh Ramen Baru", "PIK", 1.6, 4, 2, ["youtube", "berita"], (0.004, 0.005)),
    ("Contoh Seblak Hits", "Summarecon Bekasi", 1.3, 4, 2, ["youtube", "berita"], (0.0, -0.004)),
    ("Contoh Kopi Pecinan", "Suryakencana Bogor", 1.1, 3, 2, ["berita", "youtube"], (0.001, 0.001)),
]
viral = []
for i, (nama, zn, skor, m, p, src, (dlat, dlon)) in enumerate(VIRAL):
    zz = zid[zn]
    viral.append({"entitas_id": 1000 + i, "nama": nama, "zona_id": zz["id"], "zona": zn, "kode_wilayah": zz["kode_wilayah"],
                  "skor": skor, "mention_24j": m, "platform": p, "detail": {"sumber": src},
                  "lat": zz["lat"] + dlat, "lon": zz["lon"] + dlon, "contoh_url": "https://example.com/"})

BARU = [("Contoh Kafe Taman", "Tebet", 1, (0.002, -0.001)), ("Contoh Warung Mie", "Bintaro", 2, (-0.003, 0.002)),
        ("Contoh Roti Bakar", "Kelapa Gading", 4, (0.001, 0.004))]
baru = []
for i, (nama, zn, hari, (dlat, dlon)) in enumerate(BARU):
    zz = zid[zn]
    baru.append({"id": 2000 + i, "nama": nama, "zona_id": zz["id"], "zona": zn, "kode_wilayah": zz["kode_wilayah"],
                 "lat": zz["lat"] + dlat, "lon": zz["lon"] + dlon, "hari": hari})

payload = {"zona": zona, "wilayah": wilayah, "berita": BERITA, "promo": PROMO, "viral": viral, "baru": baru}
js = f"""// Generated by scripts/make_demo.py - sample data for demo mode. Do not edit by hand.
(() => {{
  const d = {json.dumps(payload, ensure_ascii=False)};
  const now = Date.now();
  d.berita.forEach((b) => {{ b.published_at = new Date(now - b.menit * 60000).toISOString(); }});
  d.baru.forEach((b) => {{ b.baru_sejak = new Date(now - b.hari * 86400000).toISOString(); }});
  window.RADAR_DEMO = d;
}})();
"""
(ROOT / "web" / "demo.js").write_text(js, encoding="utf-8")
print("web/demo.js ditulis:", {k: len(v) for k, v in payload.items()})
