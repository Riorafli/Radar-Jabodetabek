"""News photos (every news / china run).  python -m pipeline.gambar [china]

Only the URL of the publisher's own picture is stored, never the image: the RSS
entry's media/enclosure image, else the article's og:image (fetched only when
robots.txt allows our bot). The web page loads it from the publisher, next to
the link to the article. gambar = '' means tried, nothing usable.
"""
import re
import sys
import urllib.robotparser
from html import unescape
from urllib.parse import urljoin, urlparse

from pipeline.common import db, env, http, log, user_agent

# logos, icons, tracking pixels and placeholders are not news photos
BUKAN_FOTO = re.compile(r"logo|favicon|icon|sprite|placeholder|default[-_]?(?:image|img|thumb)|blank|pixel|1x1|\.svg(?:$|\?)|\.gif(?:$|\?)", re.I)
IMG_TAG = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.I)
META = re.compile(r"<meta\s[^>]*>", re.I)
ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")

TARGET = {
    "berita": ("""select id, url from item where tipe in ('berita','info') and gambar is null and url like 'http%%'
                  and published_at > now() - interval '2 days' order by published_at desc limit %s""",
               "update item set gambar = %s where id = %s"),
    "china": ("""select id, url from berita_china where gambar is null and url like 'http%%'
                 and kategori is distinct from 'buang' and terbit > now() - interval '2 days' order by terbit desc limit %s""",
              "update berita_china set gambar = %s where id = %s"),
}


def rapikan(url, base=None):
    """Absolute https URL of a likely photo, or None."""
    url = unescape((url or "").strip())
    if not url or url.startswith("data:"):
        return None
    url = urljoin(base or "", url)
    if url.startswith("http://"):
        url = "https://" + url[7:]   # the site is https: an http picture would be blocked as mixed content
    if not url.startswith("https://") or len(url) > 600 or BUKAN_FOTO.search(urlparse(url).path):
        return None
    return url


def dari_entri(e):
    """Picture URL from a feedparser entry (media:content, media:thumbnail, enclosure, first <img>)."""
    calon = []
    for m in e.get("media_content") or []:
        if m.get("medium") in (None, "image") and not str(m.get("type", "image")).startswith(("video", "audio")):
            calon.append(m.get("url"))
    calon += [m.get("url") for m in e.get("media_thumbnail") or []]
    calon += [ln.get("href") for ln in e.get("links") or []
              if ln.get("rel") == "enclosure" and str(ln.get("type", "")).startswith("image")]
    for teks in [e.get("summary") or ""] + [c.get("value", "") for c in e.get("content") or []]:
        calon += IMG_TAG.findall(teks)[:1]
    for u in calon:
        if (u := rapikan(u, e.get("link"))):
            return u
    return None


def dari_html(html, base):
    """og:image / twitter:image of an article page, or None."""
    for tag in META.findall(html[:200_000]):
        a = {k.lower(): v for k, v in ATTR.findall(tag)}
        if (a.get("property") or a.get("name") or "").lower() in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image"):
            if (u := rapikan(a.get("content"), base)):
                return u
    return None


def main(target="berita"):
    pilih, simpan = TARGET[target]
    s, robots, ok = http(), {}, 0
    with db() as cur:
        cur.execute(pilih, (int(env("GAMBAR_PER_RUN", 40)),))
        todo = cur.fetchall()
        for rid, url in todo:
            host = urlparse(url).netloc
            if host not in robots:
                rp = urllib.robotparser.RobotFileParser()
                try:
                    r = s.get(f"https://{host}/robots.txt", timeout=10)
                    rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                except Exception:
                    rp.parse([])
                robots[host] = rp
            foto = None
            if robots[host].can_fetch(user_agent(), url):
                try:
                    r = s.get(url, timeout=15)
                    if r.status_code == 200:
                        foto = dari_html(r.text, r.url)
                except Exception as e:
                    log(f"gambar: gagal ambil {url[:80]}: {e}")
            cur.execute(simpan, (foto or "", rid))
            ok += foto is not None
        cur.connection.commit()
    log(f"gambar {target}: {ok} foto dari {len(todo)} berita")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "berita")
