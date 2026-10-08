"""Unit tests for the parts that do not need a database or network."""
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from collectors.bmkg import relevan
from collectors.promo import page_text, promo_judul
from collectors.rss import parse_entry
from collectors.trends import ratio
from collectors.youtube import engagement, pick_queries
from pipeline.common import clean_html, load_config
from pipeline.entities import BrandMatcher
from pipeline.extract_llm import parse_json, validate_promo
from pipeline.geocode import Matcher, haversine_m, in_bbox, normalize, strip_dateline
from pipeline.score import hitung_skor


@pytest.fixture(scope="module")
def m():
    return Matcher()


# --- config sanity -------------------------------------------------------------
def test_config_consistent(m):
    kode = {w["kode"] for w in load_config("wilayah")["wilayah"]}
    assert kode == {"31.71", "31.72", "31.73", "31.74", "31.75", "31.01", "32.71", "32.01",
                    "32.76", "36.71", "36.74", "36.03", "32.75", "32.16"}
    for z in load_config("zones")["zona"]:
        assert z["kota"] in kode, z["nama"]
        assert in_bbox(z["lat"], z["lon"]), z["nama"]
        # the zone centre should be closest to (or near) its own city
        assert z["radius_m"] > 0


# --- text location matching ---------------------------------------------------------
@pytest.mark.parametrize("text, zona, kode", [
    ("Antrean mengular di kedai kopi baru Kemang Raya", "Kemang", "31.74"),
    ("Kuliner viral di Kemang, Bogor bikin penasaran", None, "32.71"),
    ("Banjir rendam Jalan Margonda Raya Depok", "Margonda", "32.76"),
    ("Kebakaran di Tangerang Selatan, 3 rumah hangus", None, "36.74"),
    ("Kemacetan parah di Tangerang pagi ini", None, "36.71"),
    ("Cafe baru di BSD jadi incaran anak muda", "BSD City", "36.74"),
    ("Pembangunan jalan di PIK 2 dikebut", "PIK 2", "36.03"),
    ("Pemprov DKI Jakarta umumkan tarif baru", None, "31"),
    ("Polisi tangkap pelaku di Cikarang", "Cikarang", "32.16"),
    ("Harga cabai naik di Surabaya", None, None),
    ("Banjir di Bandung selatan", None, None),
])
def test_matcher(m, text, zona, kode):
    r = m.match(text)
    assert r.zona == zona
    assert r.kode_wilayah == kode


@pytest.mark.parametrize("raw, expected", [
    ("Jakarta, CNN Indonesia -- Pesawat batal mendarat", "Pesawat batal mendarat"),
    ("Jakarta (ANTARA) - PSSI berharap", "PSSI berharap"),
    ("REPUBLIKA.CO.ID, JAKARTA -- Ustaz menjelaskan", "Ustaz menjelaskan"),
    ("JAKARTA, KOMPAS.com - Warga antre", "Warga antre"),
    ("Jakarta - Polisi menangkap", "Polisi menangkap"),
    ("Banjir merendam rumah warga", "Banjir merendam rumah warga"),
])
def test_strip_dateline(raw, expected):
    assert strip_dateline(raw) == expected


def test_dateline_does_not_make_national_news_local(m):
    e = _entry("Sejumlah Pesawat Batal Mendarat di Pekanbaru", "Jakarta, CNN Indonesia -- Asap pekat karhutla")
    assert parse_entry(e, {"filter_wilayah": True}, m) is None


def test_normalize():
    assert normalize("McDonald's Blok-M!") == " mcdonalds blok m "


def test_kode_from_names(m):
    assert m.kode_from_names(["Jakarta Selatan", "Depok", "Paris"]) == ["31.74", "32.76"]


def test_zone_at_and_kota_at(m):
    assert m.zone_at(-6.2615, 106.8137)["nama"] == "Kemang"
    assert m.zone_at(-6.0, 106.0) is None
    assert m.kota_at(-6.40, 106.80) == "32.76"        # Depok
    assert m.kota_at(-7.25, 112.75) is None            # Surabaya


def test_haversine():
    d = haversine_m(-6.2615, 106.8137, -6.2441, 106.8001)  # Kemang -> Blok M
    assert 2000 < d < 3000


# --- brands -----------------------------------------------------------------------------
def test_brands():
    b = BrandMatcher()
    assert b.canonical("kokenang") == "Kopi Kenangan"
    assert b.canonical("Kopken") == "Kopi Kenangan"
    assert b.find("Antre Mixue dan McD di Margonda") == ["McDonald's", "Mixue"] or \
        set(b.find("Antre Mixue dan McD di Margonda")) == {"McDonald's", "Mixue"}
    assert b.find("Bakso enak di Depok") == []


# --- LLM output handling --------------------------------------------------------------
def test_parse_json_variants():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Berikut hasilnya: {"promo": []} semoga membantu') == {"promo": []}
    assert parse_json("[1, 2]") == [1, 2]
    assert parse_json("bukan json") is None
    assert parse_json("") is None


def test_validate_promo(m):
    today = date(2026, 10, 8)
    ok = validate_promo({"brand": "HokBen", "judul": "Paket Hemat", "harga": "Rp35.000",
                         "periode_mulai": "2026-10-01", "periode_selesai": "2026-10-31",
                         "kota_berlaku": ["Jakarta Selatan", "Depok"]}, today=today, matcher=m)
    assert ok["harga"] == 35000
    assert ok["selesai"] == date(2026, 10, 31)
    assert ok["kota_berlaku"] == ["31.74", "32.76"]
    # expired
    assert validate_promo({"brand": "X", "judul": "Y", "periode_selesai": "2026-09-01"}, today=today) is None
    # end before start
    assert validate_promo({"brand": "X", "judul": "Y", "periode_mulai": "2026-11-01",
                           "periode_selesai": "2026-10-20"}, today=today) is None
    # brand from page hint, garbage date ignored, absurd price dropped
    p = validate_promo({"judul": "Diskon", "periode_selesai": "besok", "harga": 10**12}, "McDonald's", today=today)
    assert p["brand"] == "McDonald's" and p["selesai"] is None and p["harga"] is None
    # missing title -> unusable
    assert validate_promo({"brand": "X"}, today=today) is None
    assert validate_promo("not a dict", today=today) is None


# --- RSS ------------------------------------------------------------------------------------
def _entry(title, summary="", link="https://x.id/a"):
    return {"title": title, "summary": summary, "link": link,
            "published_parsed": time.gmtime(time.time() - 600)}


def test_parse_entry_filters_national_feeds(m):
    national = {"filter_wilayah": True}
    assert parse_entry(_entry("Harga cabai naik di Surabaya"), national, m) is None
    it = parse_entry(_entry("Banjir di <b>Bekasi Timur</b>", "<p>Air setinggi 50 cm</p>"), national, m)
    assert it["kode_wilayah"] == "32.75" and it["judul"] == "Banjir di Bekasi Timur"
    assert it["ringkasan"] == "Air setinggi 50 cm"
    assert it["label_status"] == "teks"


def test_parse_entry_local_feed_default(m):
    local = {"filter_wilayah": False, "default_wilayah": "36.71"}
    it = parse_entry(_entry("Warga gelar kerja bakti"), local, m)
    assert it["kode_wilayah"] == "36.71" and it["label_status"] == "baru"
    assert parse_entry({"title": "tanpa link"}, local, m) is None


def test_parse_entry_skips_entries_older_than_retention(m):
    old = _entry("Banjir di Bekasi Timur")
    old["published_parsed"] = time.gmtime(time.time() - 20 * 86400)
    assert parse_entry(old, {"filter_wilayah": True}, m) is None


def test_clean_html_broken_entities():
    assert clean_html("Saksi dari JPUamp;nbsp;") == "Saksi dari JPU"
    assert clean_html("A &amp;amp; B&amp;nbsp;C") == "A & B C"


def test_clean_html_limits_length():
    long = "<p>" + "kata " * 200 + "</p>"
    out = clean_html(long, 300)
    assert len(out) <= 300 and out.endswith("…")


# --- BMKG ----------------------------------------------------------------------------
def test_bmkg_relevance(m):
    prov = ["DKI Jakarta", "Jawa Barat", "Banten"]
    assert relevan("Hujan Lebat di Jawa Barat", "khususnya di CIBINONG, CILEUNGSI dan GARUT", m, prov).kode_wilayah == "32.01"
    assert relevan("Hujan Lebat di Jawa Barat", "khususnya di GARUT, TASIKMALAYA", m, prov) is None
    assert relevan("Hujan Lebat di DKI Jakarta", "di sebagian wilayah", m, prov).kode_wilayah == "31"
    assert relevan("Hujan Lebat di Jawa Timur", "khususnya di BEJI", m, prov) is None


# --- promo page handling ----------------------------------------------------------------
def test_page_text_strips_scripts():
    html = "<html><body><nav>menu</nav><div class='p'>Promo A</div><script>x=1</script></body></html>"
    assert page_text(html) == "Promo A"
    assert page_text(html, ".p") == "Promo A"


def test_promo_judul():
    assert promo_judul({"brand": "KFC", "judul": "Paket Kenyang", "harga_teks": "Rp25.000"}) == "KFC - Paket Kenyang - Rp25.000"
    assert promo_judul({"brand": "KFC", "judul": "KFC", "harga_teks": None}) == "KFC"


# --- YouTube / Trends ------------------------------------------------------------------
def test_pick_queries_rotates():
    qs = [f"q{i}" for i in range(10)]
    a = pick_queries(qs, 4, datetime(2026, 1, 1, 0, tzinfo=timezone.utc))
    b = pick_queries(qs, 4, datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
    assert a == ["q0", "q1", "q2", "q3"] and b == ["q4", "q5", "q6", "q7"]
    assert pick_queries([], 4, datetime.now(timezone.utc)) == []
    assert len(pick_queries(["a"], 4, datetime.now(timezone.utc))) == 1


def test_engagement():
    assert engagement({"viewCount": "100", "likeCount": "5", "commentCount": "1"}) == 170
    assert engagement({}) == 0


def test_trends_ratio():
    assert ratio([10] * 21 + [30] * 3) == 3.0
    assert ratio([0] * 24) is None
    assert ratio([1, 2]) is None


# --- scoring --------------------------------------------------------------------------------
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def _sig(ent, zona, sumber, hours_ago, eng=0):
    return (ent, zona, sumber, NOW - timedelta(hours=hours_ago), 1, eng)


def test_score_threshold_blocks_single_post():
    s = [_sig(1, 10, "youtube", 1, 50000)]
    assert hitung_skor(s, NOW) == []


def test_score_spike_beats_steady():
    spike = [_sig(1, 10, "youtube", h, 5000) for h in (1, 2, 3, 4)] + [_sig(1, 10, "berita", 5)]
    steady = []
    for d in range(0, 14):  # entity 2 gets 4 mentions every day incl. today
        steady += [_sig(2, 10, "youtube", d * 24 + h, 5000) for h in (1, 2, 3)] + [_sig(2, 10, "berita", d * 24 + 4)]
    res = hitung_skor(spike + steady, NOW)
    order = [r["entitas_id"] for r in res]
    assert order[0] == 1
    top = res[0]
    assert top["mention_24j"] == 5 and top["platform"] == 2 and top["detail"]["z"] > 0


def test_score_baseline_is_per_zone():
    # same entity: busy history in zone 10, nothing before in zone 20
    s = []
    for d in range(1, 14):
        s += [_sig(1, 10, "youtube", d * 24 + h) for h in range(5)]
    for z in (10, 20):
        s += [_sig(1, z, "youtube", 1), _sig(1, z, "youtube", 2), _sig(1, z, "berita", 3)]
    res = {r["zona_id"]: r["skor"] for r in hitung_skor(s, NOW)}
    assert res[20] > res[10]


def test_score_trends_and_reports():
    s = [_sig(1, 10, "youtube", h) for h in (1, 2, 3)]
    assert hitung_skor(s, NOW) == []                       # only one platform
    with_trends = hitung_skor(s, NOW, trends_up=frozenset({1}))
    assert len(with_trends) == 1 and with_trends[0]["platform"] == 2
    with_reports = hitung_skor(s, NOW, trends_up=frozenset({1}), laporan={(1, 10): 20})
    assert with_reports[0]["skor"] == pytest.approx(with_trends[0]["skor"] + 0.5)  # capped bonus


def test_score_ignores_old_and_unknown_sources():
    s = [_sig(1, 10, "youtube", 24 * 20)] * 5 + [_sig(1, 10, "osm_baru", 1)] * 5
    assert hitung_skor(s, NOW) == []


def test_trending_fills_list_when_nothing_is_viral():
    from pipeline.score import hitung_trending
    s = [_sig(1, 10, "youtube", 30, 100000), _sig(2, 10, "youtube", 100, 50), _sig(3, 10, "berita", 200)]  # 3 is > 7 days
    assert hitung_skor(s, NOW) == []
    res = hitung_trending(s, NOW)
    assert [r["entitas_id"] for r in res] == [1, 2]          # newer + more watched first, old one dropped
    assert all(r["tier"] == 2 for r in res)
    assert res[0]["detail"]["mention_7h"] == 1 and res[0]["mention_24j"] == 0


def test_trending_excludes_entries_already_viral():
    from pipeline.score import hitung_trending
    s = [_sig(1, 10, "youtube", h) for h in (1, 2, 3)] + [_sig(1, 10, "berita", 4), _sig(2, 10, "youtube", 5)]
    viral = hitung_skor(s, NOW)
    assert [r["entitas_id"] for r in viral] == [1] and viral[0]["tier"] == 1
    trending = hitung_trending(s, NOW, {(r["entitas_id"], r["zona_id"]) for r in viral})
    assert [r["entitas_id"] for r in trending] == [2]