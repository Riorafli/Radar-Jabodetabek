"""News topics for the Berita tab filter (keyword based: free, instant, no LLM).
python -m pipeline.topik   (runs after the news collectors)

Each item gets up to 2 topics, best match first; no match -> 'umum'.
Re-tags the last 3 days every run, so keyword edits apply to recent news.
"""
from pipeline.common import db, load_config, log
from pipeline.geocode import normalize

TOPIK = {
    "lalu_lintas": ["macet", "kemacetan", "lalu lintas", "lalin", "tol", "jalan tol", "krl", "commuter line", "transjakarta",
                    "busway", "mrt", "lrt", "ganjil genap", "rekayasa lalu lintas", "penutupan jalan", "angkot", "ojol",
                    "bandara", "soetta", "penerbangan", "stasiun", "terminal", "jalur", "parkir", "kendaraan", "pengendara",
                    "jabodebek", "whoosh", "kereta"],
    "cuaca_bencana": ["banjir", "genangan", "hujan", "cuaca", "bmkg", "longsor", "angin kencang", "puting beliung", "gempa",
                      "polusi", "kualitas udara", "kekeringan", "rob", "pohon tumbang", "petir", "siaga", "bencana", "bpbd"],
    "peristiwa": ["kecelakaan", "kebakaran", "terbakar", "tewas", "tenggelam", "korban jiwa", "ambruk", "roboh", "tabrakan",
                  "tertabrak", "tersengat", "meninggal", "damkar", "evakuasi", "sar", "basarnas", "hanyut", "dibakar"],
    "kriminal": ["polisi", "polda", "polres", "polsek", "ditangkap", "tersangka", "terdakwa", "pencurian", "maling", "begal",
                 "jambret", "penipuan", "narkoba", "sabu", "korupsi", "kpk", "sidang", "pengadilan", "vonis", "dituntut",
                 "pembunuhan", "dibunuh", "penganiayaan", "dikeroyok", "tawuran", "pelecehan", "kejaksaan", "jaksa", "ditahan",
                 "buron", "penjara", "dakwaan", "kriminal", "pelaku", "pungli", "diamankan", "curi", "mencuri"],
    "pemerintahan": ["gubernur", "wakil gubernur", "pemprov", "pemkot", "pemkab", "wali kota", "walikota", "bupati", "dprd",
                     "pramono", "rano karno", "apbd", "anggaran", "pilkada", "camat", "lurah", "satpol pp", "kebijakan",
                     "peraturan", "perda", "pergub", "pelayanan publik", "dinas", "bansos", "kartu layanan", "menteri", "presiden",
                     "sekda", "pejabat", "pelantikan", "dilantik", "asn", "pns", "revitalisasi"],
    "ekonomi": ["harga", "inflasi", "ekonomi", "umkm", "investasi", "lowongan", "loker", "pekerja", "buruh", "umr", "ump",
                "phk", "pajak", "bisnis", "usaha", "perdagangan", "pasar induk", "bapok", "sembako", "emas", "rupiah", "properti",
                "pedagang", "gulung tikar", "pasar", "toko"],
    "kesehatan": ["rumah sakit", "rsud", "puskesmas", "kesehatan", "bpjs kesehatan", "dbd", "demam berdarah", "vaksin",
                  "imunisasi", "penyakit", "pasien", "dokter", "stunting", "keracunan", "virus", "wabah", "gizi"],
    "pendidikan": ["sekolah", "siswa", "pelajar", "guru", "kampus", "universitas", "mahasiswa", "ppdb", "smk", "sma", "smp",
                   "sd", "madrasah", "pendidikan", "beasiswa", "ujian", "kuliah", "mbg", "makan bergizi gratis"],
    "gaya_hidup": ["kuliner", "makanan", "restoran", "kafe", "cafe", "kopi", "konser", "festival", "wisata", "liburan", "mal",
                   "mall", "film", "bioskop", "musik", "fashion", "pameran", "bazar", "event", "hiburan", "taman", "budaya",
                   "tradisi", "adat", "sejarah", "museum"],
    "olahraga": ["sepak bola", "persija", "persikabo", "timnas", "liga", "pertandingan", "laga", "stadion", "gbk", "jis",
                 "marathon", "maraton", "olahraga", "atlet", "motogp", "badminton", "bulu tangkis", "basket", "voli", "turnamen"],
}
_TOPIK_NORM = {k: [normalize(w).strip() for w in ws] for k, ws in TOPIK.items()}


def klasifikasi(judul, ringkasan="", tipe="berita", pola_saham=None):
    """-> up to 2 topics, title hits weigh double; ['umum'] when nothing matches.
    A HEADLINE about stocks/crypto -> ['pasar_modal'] only: it moves to the Saham tab."""
    from collectors.saham import jenis_pasar

    if tipe == "berita" and jenis_pasar(judul, pola_saham):
        return ["pasar_modal"]
    tj, tr = normalize(judul), normalize(ringkasan)
    skor = {}
    for k, ws in _TOPIK_NORM.items():
        s = sum(2 for w in ws if f" {w} " in tj) + sum(1 for w in ws if f" {w} " in tr)
        if s:
            skor[k] = s
    if tipe == "info" and "cuaca_bencana" not in skor and ("hujan" in tj or "cuaca" in tj):
        skor["cuaca_bencana"] = 1
    if not skor:
        return ["umum"]
    urut = sorted(skor, key=lambda k: (-skor[k], list(TOPIK).index(k)))
    return urut[:2]


def peta_jenis(cfg):
    """{source name: jenis} for the Berita tab (rss feeds + BMKG)."""
    peta = {f["nama"]: f.get("jenis", "lainnya") for f in cfg.get("rss", [])}
    peta["BMKG"] = cfg.get("bmkg", {}).get("jenis", "resmi")
    return peta


def sinkron_jenis(cur):
    """Label every news item with its source type; unknown sources (GDELT domains) -> lainnya."""
    n = 0
    for nama, jenis in peta_jenis(load_config("sources")).items():
        cur.execute("""update item set jenis_sumber = %s where tipe in ('berita', 'info') and sumber = %s
                       and jenis_sumber is distinct from %s""", (jenis, nama, jenis))
        n += cur.rowcount
    # GDELT items carry the outlet's domain as source
    dj = load_config("sources").get("gdelt", {}).get("domain_jenis", {})
    cur.execute("select distinct sumber from item where tipe in ('berita', 'info') and (jenis_sumber is null or jenis_sumber = 'lainnya')")
    for (sumber,) in cur.fetchall():
        jenis = jenis_domain(sumber, dj)
        if jenis:
            cur.execute("update item set jenis_sumber = %s where tipe in ('berita', 'info') and sumber = %s", (jenis, sumber))
            n += cur.rowcount
    cur.execute("update item set jenis_sumber = 'lainnya' where tipe in ('berita', 'info') and jenis_sumber is null")
    return n + cur.rowcount


def jenis_domain(sumber, domain_jenis):
    """'daerah.sindonews.com' -> 'swasta'; '*.go.id' -> 'resmi'; unknown -> None."""
    d = (sumber or "").lower().strip()
    if d.endswith(".go.id"):
        return "resmi"
    for jenis, domains in domain_jenis.items():
        if any(d == x or d.endswith("." + x) for x in domains):
            return jenis
    return None


def pindah_ke_saham(cur, pola):
    """Copy pasar_modal news into saham_berita (the Saham tab's news list)."""
    from collectors.saham import jenis_pasar, kode_disebut

    cur.execute("""select url, judul, sumber, published_at, coalesce(ringkasan, '') from item
                   where 'pasar_modal' = any(topik) and url is not null
                   and not exists (select 1 from saham_berita s where s.url = item.url)""")
    rows = cur.fetchall()
    for url, judul, sumber, terbit, ringkasan in rows:
        cur.execute("""insert into saham_berita (url, judul, sumber, terbit, kode, jenis) values (%s,%s,%s,%s,%s,%s)
                       on conflict (url) do nothing""",
                    (url, judul, sumber, terbit, kode_disebut(f"{judul} {ringkasan}", pola), jenis_pasar(judul, pola) or "saham"))
    return len(rows)


def pola_pindah():
    """Tickers only (BBCA, GOTO, IHSG): company-name keywords such as 'BRI' or
    'Summarecon' also appear in sports, court and event news, so they must not
    decide that a story is stock-market news."""
    from collectors.saham import daftar_saham, pola_saham

    return pola_saham([{"kode": s["kode"]} for s in daftar_saham()] + [{"kode": "IHSG"}])


def pola_kode():
    """Tickers + company keywords: used only to tag which stocks a moved story names."""
    from collectors.saham import daftar_saham, pola_saham

    return pola_saham(daftar_saham() + [{"kode": "IHSG", "kata_kunci": []}])


def main():
    pola = pola_pindah()
    with db() as cur:
        log(f"jenis sumber: {sinkron_jenis(cur)} berita diberi label")
        cur.execute("""select id, judul, coalesce(ringkasan, ''), tipe, topik from item where tipe in ('berita', 'info')
                       and (topik = '{}' or published_at > now() - interval '3 days')""")
        rows = cur.fetchall()
        n = 0
        for iid, judul, ringkasan, tipe, lama in rows:
            baru = klasifikasi(judul, ringkasan, tipe, pola)
            if baru != (lama or []):
                cur.execute("update item set topik = %s where id = %s", (baru, iid))
                n += 1
        pindah = pindah_ke_saham(cur, pola_kode())
    log(f"topik: {len(rows)} berita dicek, {n} diperbarui, {pindah} berita saham/kripto dipindah ke tab Saham")


if __name__ == "__main__":
    main()
