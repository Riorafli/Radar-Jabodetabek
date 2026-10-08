"""Food promo collector (every 3 h).  python -m collectors.promo

For each page in sources.yaml -> promo:
  1. respect robots.txt (skip if disallowed)
  2. download, take the text of `selector`
  3. if the text hash is unchanged since last run -> skip (saves LLM quota)
  4. LLM -> JSON -> validate; invalid entries are logged and dropped
  5. store in item (tipe='promo') + promo
Never scrapes GoFood / GrabFood / ShopeeFood (ToS).
"""
import urllib.robotparser
from functools import lru_cache
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from pipeline import extract_llm
from pipeline.common import db, http, load_config, log, sha1, user_agent
from pipeline.entities import BrandMatcher
from pipeline.geocode import Matcher
from pipeline.items import brand_mentions, insert_item

BLOCKED_HOSTS = ("gofood", "gojek.com", "grab.com", "shopeefood", "food.shopee")
MIN_TEXT = 200  # pages with less text are JS-rendered / empty


@lru_cache(maxsize=None)
def robots_for(base):
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = http().get(f"{base}/robots.txt", timeout=15)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except Exception:
        rp.parse([])
    return rp


def allowed(url):
    p = urlparse(url)
    if any(b in p.netloc for b in BLOCKED_HOSTS):
        return False
    return robots_for(f"{p.scheme}://{p.netloc}").can_fetch(user_agent(), url)


def page_text(html, selector=""):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    nodes = soup.select(selector) if selector else [soup.body or soup]
    return "\n".join(n.get_text("\n", strip=True) for n in nodes)


def promo_judul(p):
    parts = [p["brand"], p["judul"]]
    if p["harga_teks"]:
        parts.append(p["harga_teks"])
    return " - ".join(dict.fromkeys(x for x in parts if x))


def main():
    sources = [s for s in load_config("sources").get("promo", []) if s.get("aktif")]
    if not extract_llm.available():
        log("promo: GEMINI_API_KEY / GROQ_API_KEY belum diisi, dilewati")
        return
    matcher, brands = Matcher(), BrandMatcher()
    with db() as cur:
        for s in sources:
            url = s["url"]
            if not allowed(url):
                log(f"promo {s['nama']}: dilarang robots.txt/ToS, pindahkan ke kurasi manual")
                continue
            try:
                r = http().get(url, timeout=30)
                r.raise_for_status()
            except Exception as e:
                log(f"promo {s['nama']}: gagal unduh ({e})")
                continue
            text = page_text(r.text, s.get("selector", ""))
            if len(text) < MIN_TEXT:
                log(f"promo {s['nama']}: teks terlalu sedikit ({len(text)}), kemungkinan butuh JavaScript")
                continue
            h = sha1(text)
            cur.execute("select hash from halaman_cache where url=%s", (url,))
            row = cur.fetchone()
            if row and row[0] == h:
                log(f"promo {s['nama']}: tidak berubah")
                continue

            promos = extract_llm.extract_promos(text, s.get("brand", ""), matcher)
            if promos is None:
                log(f"promo {s['nama']}: LLM gagal, dicoba lagi run berikutnya")
                continue
            baru = 0
            for p in promos:
                key = f"promo:{p['brand']}:{p['judul']}:{p['selesai']}".lower()
                item_id = insert_item(
                    cur, "promo", promo_judul(p), url, s["nama"], p["syarat"],
                    kode_wilayah=p["kota_berlaku"][0] if len(p["kota_berlaku"]) == 1 else None,
                    meta={"halaman": s["nama"]}, label_status="teks", hash_key=key)
                if not item_id:
                    continue
                cur.execute(
                    """insert into promo (item_id, brand, menu, harga, harga_teks, mulai, selesai, syarat, kota_berlaku)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (item_id, p["brand"], p["menu"], p["harga"], p["harga_teks"], p["mulai"], p["selesai"],
                     p["syarat"], p["kota_berlaku"]))
                brand_mentions(cur, item_id, brands.find(p["brand"]), "promo", None, None)
                baru += 1
            # remember the hash only after a successful extraction
            cur.execute("""insert into halaman_cache (url, hash) values (%s,%s)
                           on conflict (url) do update set hash=excluded.hash, diambil=now()""", (url, h))
            cur.connection.commit()
            log(f"promo {s['nama']}: {len(promos)} promo valid, {baru} baru")


if __name__ == "__main__":
    main()
