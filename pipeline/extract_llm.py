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
