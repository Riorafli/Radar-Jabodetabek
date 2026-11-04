"""Merchant logos for promo cards (the site shows initials when there is none).
    python -m pipeline.logo

For each brand with an active promo:
1. find its own website: `situs:` in brands.yaml, else the promo link when its host
   carries the brand name (mcdonalds.co.id for McDonald's), else a domain the LLM is
   confident about, kept only when the homepage title or host names the brand;
2. take the site's own icon from its homepage (apple-touch-icon, then the largest
   <link rel=icon>, then /favicon.ico), after robots.txt allows our bot.
`logo:` in brands.yaml overrides everything. Results are cached in brand_logo and
brands without a logo are retried after LAGI_HARI days.
"""
import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from pipeline import extract_llm
from pipeline.common import db, env, http, load_config, log, user_agent

LAGI_HARI = 30
STOP = {"the", "dan", "and", "resto", "restaurant", "cafe", "coffee", "kopi", "grup", "group", "express",
        "official", "store", "indonesia", "pasar", "dealer", "promo", "kitchen", "factory"}

PROMPT = """For each business below (brands with promotions in Jakarta, Indonesia), give the domain of its own
official website, e.g. "mcdonalds.co.id". Prefer the Indonesian site. Use null when you are not sure the
business has its own website (social media pages, marketplaces and banks do not count).
Return JSON: {{"hasil": [{{"no": 1, "domain": "example.co.id"}}]}}

{lines}"""


def kata(s):
    """Distinctive lowercase tokens of a brand name: 'Ulivo Ristorante Italiano' -> ['ulivo', 'ristorante', 'italiano']."""
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower().replace("'", "")) if len(w) >= 3 and w not in STOP]


def host_milik(brand, host):
    """True when the host itself carries the brand name (mcdonalds.co.id for McDonald's)."""
    h = re.sub(r"[^a-z0-9]", "", (host or "").lower())
    rapat = re.sub(r"[^a-z0-9]", "", (brand or "").lower())
    return bool(h) and ((len(rapat) >= 4 and rapat in h) or any(len(w) >= 4 and w in h for w in kata(brand)[:2]))


def ikon_dari_html(html, base):
    """Best icon URL in a homepage: apple-touch-icon, then the largest rel=icon. None if none is declared."""
    s = BeautifulSoup(html or "", "html.parser")
    calon = []
    for l in s.find_all("link", href=True):
        rel = " ".join(l.get("rel") or []).lower()
        if "mask-icon" in rel or "icon" not in rel:
            continue
        ukuran = max([int(a) for a in re.findall(r"(\d+)x\d+", l.get("sizes") or "")] or [0])
        mutu = 2 if "apple-touch-icon" in rel else 1
        if (l.get("type") or "").endswith("svg") or l["href"].lower().split("?")[0].endswith(".svg"):
            ukuran = max(ukuran, 512)
        calon.append((mutu, ukuran, urljoin(base, l["href"].strip())))
    calon = [c for c in calon if c[2].startswith(("http://", "https://"))]
    return max(calon)[2] if calon else None


PARKIR = re.compile(r"for sale|buy this domain|domain (is )?(parked|dijual)|domain dijual|parked free|spaceship|\bsedo\b|hugedomains|dan\.com|afternic", re.I)


def judul_milik(brand, html):
    """The homepage title names the brand (and the page is not a parked or for-sale domain)."""
    if PARKIR.search((html or "")[:20000]):
        return False
    s = BeautifulSoup(html or "", "html.parser")
    teks = " ".join(filter(None, [s.title.get_text(" ") if s.title else "",
                                  *(m.get("content", "") for m in s.find_all("meta", property="og:site_name"))])).lower()
    ks = kata(brand)
    return bool(ks) and sum(k in teks for k in ks) >= min(2, len(ks))


def boleh(s, robots, url):
    host = urlparse(url).netloc
    if host not in robots:
        try:
            r = s.get(f"https://{host}/robots.txt", timeout=10)
            robots[host] = r.text if r.status_code == 200 else ""
        except Exception:
            robots[host] = ""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(robots[host].splitlines())
    return rp.can_fetch(user_agent(), url)


def gambar_ok(s, url):
    """The icon answers 200 with an image over https."""
    url = re.sub(r"^http://", "https://", url)
    try:
        r = s.get(url, timeout=10, stream=True)
        ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
        r.close()
        return url if ok else None
    except Exception:
        return None


def logo_situs(s, robots, brand, domain, cek):
    """Icon URL from the brand's homepage, or None.
    cek: 0 = trusted domain, 1 = host or title must name the brand, 2 = title must name it."""
    home = f"https://{domain}/"
    if not boleh(s, robots, home):
        return None
    try:
        r = s.get(home, timeout=15)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    akhir = urlparse(r.url).netloc
    if (cek == 1 and not (host_milik(brand, akhir) or judul_milik(brand, r.text))) or (cek == 2 and not judul_milik(brand, r.text)):
        log(f"logo: {domain} bukan situs {brand}, dilewati")
        return None
    if PARKIR.search(r.text[:20000]):
        return None
    ikon = ikon_dari_html(r.text, r.url)
    return (ikon and gambar_ok(s, ikon)) or gambar_ok(s, urljoin(r.url, "/favicon.ico"))


def tebak_sendiri(brand):
    """'Pepper Lunch' -> ['pepperlunch.co.id', 'pepperlunch.com', 'pepperlunch.id']."""
    rapat = re.sub(r"[^a-z0-9]", "", (brand or "").lower())
    return [f"{rapat}.{t}" for t in ("co.id", "com", "id")] if 4 <= len(rapat) <= 24 else []


def tebak_domain(brands):
    """LLM guesses {brand: domain}; {} when unavailable."""
    if not brands or not extract_llm.available():
        return {}
    data = extract_llm.ask_json(PROMPT.format(lines="\n".join(f"{n + 1}. {b}" for n, b in enumerate(brands))))
    out = {}
    for h in (data.get("hasil", []) if isinstance(data, dict) else []):
        try:
            n, d = int(h.get("no")) - 1, h.get("domain")
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= n < len(brands) and isinstance(d, str) and re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d.strip().lower()):
            out[brands[n]] = re.sub(r"^www\.", "", d.strip().lower())
    return out


def main():
    cfg = {b["nama"]: b for b in load_config("brands").get("brand", [])}
    s, robots = http(), {}
    with db() as cur:
        cur.execute("""select p.brand, array_agg(distinct split_part(i.url, '/', 3)) from promo p join item i on i.id = p.item_id
                       where p.brand is not null and (p.selesai is null or p.selesai >= current_date)
                         and not exists (select 1 from brand_logo b where b.brand = p.brand
                                         and (b.logo <> '' or b.dicek > now() - make_interval(days => %s)))
                       group by p.brand limit %s""", (LAGI_HARI, int(env("LOGO_PER_RUN", 40))))
        todo = cur.fetchall()
        domain, tebakan = {}, []
        for brand, hosts in todo:
            c = cfg.get(brand, {})
            sendiri = [h for h in hosts if host_milik(brand, h)]
            if c.get("situs"):
                domain[brand] = (c["situs"], 0)
            elif sendiri:
                domain[brand] = (sendiri[0], 0)
            elif not c.get("logo"):
                tebakan.append(brand)
        for b, d in tebak_domain(tebakan).items():
            domain[b] = (d, 1)
        ok = 0
        for brand, _ in todo:
            c = cfg.get(brand, {})
            d, cek = domain.get(brand, (None, 0))
            logo = c.get("logo") or (logo_situs(s, robots, brand, d, cek) if d else None)
            if not logo and not c.get("logo"):
                # last try: the obvious domains, kept only when the homepage title names the brand
                for calon in tebak_sendiri(brand):
                    if calon != d and (logo := logo_situs(s, robots, brand, calon, 2)):
                        d = calon
                        break
            cur.execute("""insert into brand_logo (brand, domain, logo, dicek) values (%s, %s, %s, now())
                           on conflict (brand) do update set domain = excluded.domain, logo = excluded.logo, dicek = now()""",
                        (brand, d, logo or ""))
            ok += bool(logo)
        cur.connection.commit()
        log(f"logo: {ok} logo dari {len(todo)} brand")


if __name__ == "__main__":
    main()
