"""Shared helpers: config loading, DB connection, HTTP session, logging."""
import functools
import hashlib
import html
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
WIB = timezone(timedelta(hours=7))


def _load_dotenv():
    """Tiny .env loader for local runs (GitHub Actions uses real env vars)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@functools.lru_cache(maxsize=None)
def load_config(name):
    with open(ROOT / "config" / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def log(*args):
    print(datetime.now(WIB).strftime("%H:%M:%S"), *args, flush=True)


def connect():
    import psycopg2

    url = env("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (see .env.example)")
    return psycopg2.connect(url, connect_timeout=20)


@contextmanager
def db():
    """Connection + cursor; commits on success, rolls back on error."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def user_agent():
    contact = env("CONTACT_EMAIL", "https://github.com/")
    return f"RadarJabodetabek/1.0 (+{contact})"


@functools.lru_cache(maxsize=None)
def http():
    s = requests.Session()
    s.headers["User-Agent"] = user_agent()
    return s


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def clean_html(text, limit=300):
    """Strip tags and whitespace; cut to `limit` chars (copyright: summary only)."""
    if not text:
        return ""
    from bs4 import BeautifulSoup

    t = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    t = re.sub(r"amp;(?=#?[a-z0-9]+;)", "&", t)  # Okezone sends "JPUamp;nbsp;"
    for _ in range(3):  # some feeds double-escape ("&amp;nbsp;")
        t = html.unescape(t)
    t = re.sub(r"&[a-z]+;", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[: limit - 1].rsplit(" ", 1)[0] + "…"
    return t


def now_utc():
    return datetime.now(timezone.utc)


def today_wib():
    return datetime.now(WIB).date()
