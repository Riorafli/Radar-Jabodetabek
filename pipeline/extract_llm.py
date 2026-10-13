"""Free-tier LLM helpers (Gemini first, Groq as fallback).

Everything returns parsed + validated Python data or None/[] on failure, so
callers never store half-finished data.
"""
import json
import re
import time
from datetime import date, timedelta

from pipeline.common import env, http, log, today_wib


def available():
    return bool(env("GEMINI_API_KEY") or env("GROQ_API_KEY"))


def _gemini(prompt):
    key = env("GEMINI_API_KEY")
    if not key:
        return None
    model = env("GEMINI_MODEL", "gemini-flash-lite-latest")
    r = http().post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    if r.status_code == 429:
        log("gemini: rate limited")
        return None
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def _groq(prompt):
    key = env("GROQ_API_KEY")
    if not key:
        return None
    r = http().post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": env("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Reply with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60,
    )
    if r.status_code == 429:
        log("groq: rate limited")
        return None
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask_json(prompt, retries=1):
    """Send prompt, return parsed JSON (dict/list) or None."""
    for attempt in range(retries + 1):
        for fn in (_gemini, _groq):
            try:
                out = fn(prompt)
            except Exception as e:
                log(f"{fn.__name__} error: {e}")
                out = None
            if out:
                data = parse_json(out)
                if data is not None:
                    return data
                log(f"{fn.__name__}: invalid JSON, skipped")
        if attempt < retries:
            time.sleep(5)
    return None


def parse_json(text):
    """Parse JSON from an LLM reply, tolerating ``` fences and leading prose."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    end = max(t.rfind("}"), t.rfind("]"))
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None


# --- promo -------------------------------------------------------------------
PROMO_PROMPT = """Kamu mengekstrak promo MAKANAN/MINUMAN dari teks halaman web Indonesia.
Tanggal hari ini: {today}. Brand halaman (jika diketahui): {brand}.
Kembalikan JSON: {{"promo": [ {{
  "brand": "nama brand/restoran",
  "judul": "judul promo singkat",
  "menu": "menu yang dipromokan atau null",
  "harga": angka rupiah tanpa titik atau null,
  "harga_teks": "teks harga/diskon asli, mis. 'Diskon 50%' atau null",
  "periode_mulai": "YYYY-MM-DD atau null",
  "periode_selesai": "YYYY-MM-DD atau null",
  "syarat": "syarat singkat (maks 200 karakter) atau null",
  "kota_berlaku": ["nama kota"]  (kosong jika berlaku nasional/semua kota)
}} ] }}
Aturan: hanya promo makanan/minuman. Jangan mengarang data yang tidak ada di teks.
Jika tidak ada promo makanan, kembalikan {{"promo": []}}.

TEKS:
{text}"""


def _parse_date(v):
    if not v or not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _parse_harga(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if 0 < v < 50_000_000 else None
    digits = re.sub(r"[^\d]", "", str(v))
    return _parse_harga(int(digits)) if digits else None


def _short(v, n):
    if not v or not isinstance(v, str):
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v[:n] or None


def validate_promo(p, brand_hint="", today=None, matcher=None):
    """Return a clean promo dict, or None if it is unusable."""
    today = today or today_wib()
    if not isinstance(p, dict):
        return None
    brand = _short(p.get("brand"), 80) or _short(brand_hint, 80)
    judul = _short(p.get("judul"), 160) or _short(p.get("menu"), 160)
    if not brand or not judul:
        return None
    mulai, selesai = _parse_date(p.get("periode_mulai")), _parse_date(p.get("periode_selesai"))
    if selesai and selesai < today:
        return None  # already over
    if selesai and mulai and selesai < mulai:
        return None
    if selesai and selesai > today + timedelta(days=400):
        selesai = None  # implausible, treat as unknown
    if mulai and mulai > today + timedelta(days=120):
        return None
    kota = p.get("kota_berlaku") or []
    if not isinstance(kota, list):
        kota = [kota]
    kota_kode = matcher.kode_from_names([str(k) for k in kota]) if matcher else []
    return {
        "brand": brand,
        "judul": judul,
        "menu": _short(p.get("menu"), 120),
        "harga": _parse_harga(p.get("harga")),
        "harga_teks": _short(p.get("harga_teks"), 80),
        "mulai": mulai,
        "selesai": selesai,
        "syarat": _short(p.get("syarat"), 200),
        "kota_berlaku": kota_kode,
    }


def extract_promos(text, brand_hint="", matcher=None):
    """List of valid promos ([] = page has none), or None if the LLM failed."""
    data = ask_json(PROMO_PROMPT.format(today=today_wib().isoformat(), brand=brand_hint or "-", text=text[:12000]))
    if data is None:
        return None
    items = data.get("promo", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out = []
    for p in items:
        v = validate_promo(p, brand_hint, matcher=matcher)
        if v:
            out.append(v)
        else:
            log("promo invalid, skipped:", str(p)[:120])
    return out


# --- places / locations -----------------------------------------------------
PLACES_PROMPT = """Untuk setiap judul konten kuliner Indonesia di bawah, sebutkan nama TEMPAT MAKAN
atau BRAND spesifik yang dibahas (bukan nama makanan umum seperti "bakso" atau "kopi"),
dan lokasinya (nama daerah/kota) jika disebut.
Kembalikan JSON: {{"hasil": [ {{"no": 1, "tempat": ["Nama Tempat"], "lokasi": "Kemang" atau null}} ]}}
Jika tidak ada tempat spesifik, "tempat": []. Jangan mengarang.

{lines}"""


def extract_places(titles):
    """titles -> list (same length) of {"tempat": [...], "lokasi": str|None}."""
    empty = [{"tempat": [], "lokasi": None} for _ in titles]
    if not titles or not available():
        return empty
    lines = "\n".join(f"{i + 1}. {t[:300]}" for i, t in enumerate(titles))
    data = ask_json(PLACES_PROMPT.format(lines=lines))
    rows = data.get("hasil", []) if isinstance(data, dict) else []
    for r in rows:
        try:
            i = int(r.get("no")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(titles):
            tempat = [_short(t, 80) for t in (r.get("tempat") or []) if isinstance(t, str)]
            empty[i] = {"tempat": [t for t in tempat if t and len(t) >= 3], "lokasi": _short(r.get("lokasi"), 80)}
    return empty


LOC_PROMPT = """Untuk setiap teks berita di bawah, sebutkan lokasi paling spesifik di wilayah
Jabodetabek (Jakarta, Bogor, Depok, Tangerang, Bekasi) yang menjadi tempat kejadian:
nama jalan/kelurahan/kecamatan/kota. Jika bukan di Jabodetabek atau tidak jelas, null.
Kembalikan JSON: {{"hasil": [ {{"no": 1, "lokasi": "Jalan Margonda, Depok" atau null}} ]}}

{lines}"""


def extract_locations(texts):
    out = [None] * len(texts)
    if not texts:
        return out
    lines = "\n".join(f"{i + 1}. {t[:350]}" for i, t in enumerate(texts))
    data = ask_json(LOC_PROMPT.format(lines=lines))
    for r in (data.get("hasil", []) if isinstance(data, dict) else []):
        try:
            i = int(r.get("no")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(texts):
            out[i] = _short(r.get("lokasi"), 120)
    return out


# --- shopping promos (marketplace / cuci gudang) ------------------------------
KATEGORI_BELANJA = ("marketplace", "cuci_gudang", "lainnya")
PLATFORM = {"shopee": "Shopee", "tokopedia": "Tokopedia", "lazada": "Lazada", "blibli": "Blibli",
            "tiktok shop": "TikTok Shop", "tiktokshop": "TikTok Shop", "tiktok": "TikTok Shop",
            "bukalapak": "Bukalapak", "zalora": "Zalora", "jd.id": "JD.ID"}
UMUR_TANPA_TANGGAL = {"marketplace": 5, "cuci_gudang": 3, "lainnya": 3}  # assumed run time when no end date

BELANJA_PROMPT = """Kamu memilah berita Indonesia tentang PROMO BELANJA. Tanggal hari ini: {today}.
Untuk setiap artikel (tanggal terbit, judul, ringkasan), tentukan kategori:
- "marketplace": promo/diskon/flash sale/voucher/cashback di toko online (Shopee, Tokopedia, Lazada, Blibli, TikTok Shop, Bukalapak, Zalora, dll),
  termasuk video/artikel rekomendasi produk murah atau "racun" marketplace yang menyebut produk tertentu
- "cuci_gudang": SALE DI LOKASI FISIK: cuci gudang, warehouse sale, clearance sale, obral, bazar diskon, midnight sale,
  big sale, full day sale, mega sale di toko, supermarket, hypermarket, department store, mal, atau gedung acara
- "lainnya": promo belanja lain tanpa lokasi fisik atau platform online tertentu (mis. promo kartu kredit/bank)
- "bukan": bukan info promo yang bisa dimanfaatkan (berita bisnis, PHK, regulasi, gosip, ulasan produk tanpa promo,
  tutorial, challenge, vlog, atau konten hiburan yang tidak menyebut produk spesifik yang bisa dibeli)
Untuk "marketplace", "produk" wajib berisi nama produk spesifik (merek/jenis barang), bukan kategori umum seperti "makeup".
Kembalikan JSON: {{"hasil": [{{"no": 1, "kategori": "...", "judul": "judul promo singkat",
 "acara": "nama acara/kampanye promo, sama persis untuk artikel tentang acara yang sama (mis. 'Transmart Full Day Sale', 'Shopee 10.10 Brand Festival') atau null",
 "platform": ["Shopee"], "penyelenggara": "brand/toko/mal penyelenggara atau null",
 "produk": "produk utama yang didiskon atau null", "diskon_teks": "mis. 'Diskon hingga 70%' atau null",
 "diskon_persen": angka 1-99 atau null, "harga": angka rupiah tanpa titik atau null,
 "mulai": "YYYY-MM-DD" atau null, "selesai": "YYYY-MM-DD" atau null,
 "lokasi": "nama tempat/mal (untuk cuci_gudang) atau null", "kota": "nama kota atau null"}}]}}
Aturan: jangan mengarang, isi null jika tidak disebut. Hitung tanggal relatif ("hari ini", "besok", "akhir pekan ini")
dari tanggal terbit artikel. Acara satu hari (mis. "Full Day Sale hari ini/besok"): mulai = selesai = tanggal acara itu.

{lines}"""


def _platforms(v):
    out = []
    for x in (v if isinstance(v, list) else [v] if v else []):
        if not isinstance(x, str):
            continue
        k = x.strip().lower()
        name = PLATFORM.get(k) or next((n for key, n in PLATFORM.items() if key in k), None)
        if name and name not in out:
            out.append(name)
    return out[:3]


def validate_belanja(r, terbit, today=None, matcher=None):
    """Clean one LLM row for a shopping promo, or None if unusable/expired."""
    today = today or today_wib()
    if not isinstance(r, dict) or r.get("kategori") not in KATEGORI_BELANJA:
        return None
    kat = r["kategori"]
    judul = _short(r.get("judul"), 160)
    if not judul:
        return None
    platform = _platforms(r.get("platform"))
    if kat == "marketplace" and not platform:
        platform = _platforms([judul])
    mulai, selesai = _parse_date(r.get("mulai")), _parse_date(r.get("selesai"))
    if selesai and selesai > today + timedelta(days=120):
        selesai = None
    perkiraan = False
    if not selesai:
        selesai = max(terbit, mulai or terbit) + timedelta(days=UMUR_TANPA_TANGGAL[kat])
        perkiraan = True
    if selesai < today or (mulai and selesai < mulai):
        return None
    try:
        diskon = int(float(r.get("diskon_persen")))
        diskon = diskon if 1 <= diskon <= 99 else None
    except (TypeError, ValueError):
        diskon = None
    lokasi, kota = _short(r.get("lokasi"), 120), _short(r.get("kota"), 60)
    kota_kode = matcher.kode_from_names([x for x in (kota, lokasi) if x]) if matcher and kat != "marketplace" else []
    return {
        "kategori": kat, "judul": judul, "acara": _short(r.get("acara"), 120), "platform": platform,
        "brand": _short(r.get("penyelenggara"), 80) or (platform[0] if platform else None) or "Promo",
        "produk": _short(r.get("produk"), 120), "diskon_teks": _short(r.get("diskon_teks"), 80),
        "diskon_persen": diskon, "harga": _parse_harga(r.get("harga")),
        "mulai": mulai, "selesai": selesai, "selesai_perkiraan": perkiraan,
        "lokasi": lokasi if kat != "marketplace" else None, "kota": kota, "kota_berlaku": kota_kode,
    }


def extract_belanja(articles, matcher=None, chunk=12):
    """articles: [{judul, ringkasan, terbit(datetime)}] -> list of validated
    dicts / None (not a promo), one per article processed. Stops at the first
    chunk the LLM fails on (callers retry the rest later). None if nothing ran."""
    out = []
    for i in range(0, len(articles), chunk):
        part = articles[i:i + chunk]
        lines = "\n".join(f"{n + 1}. [terbit {a['terbit'].date().isoformat()}] {a['judul']} -- {a['ringkasan'][:500]}"
                          for n, a in enumerate(part))
        data = ask_json(BELANJA_PROMPT.format(today=today_wib().isoformat(), lines=lines))
        if data is None:
            break
        rows = [None] * len(part)
        for r in (data.get("hasil", []) if isinstance(data, dict) else []):
            try:
                n = int(r.get("no")) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            if 0 <= n < len(part):
                rows[n] = validate_belanja(r, part[n]["terbit"].date(), matcher=matcher)
        out += rows
    return out if out else None
