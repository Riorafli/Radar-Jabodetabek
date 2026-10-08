"""Insert news/promo/post items + their brand mention signals."""
from psycopg2.extras import Json

from pipeline.common import sha1
from pipeline.entities import add_signal, brand_id


def insert_item(cur, tipe, judul, url, sumber, ringkasan=None, published_at=None,
                kode_wilayah=None, zona_id=None, entitas_id=None, lat=None, lon=None,
                meta=None, label_status="baru", hash_key=None):
    """Returns the new item id, or None when it already existed (dedup)."""
    h = sha1(hash_key or url or f"{sumber}:{judul}")
    cur.execute(
        """insert into item (tipe, judul, url, sumber, ringkasan, published_at, kode_wilayah, zona_id,
                             entitas_id, lat, lon, meta, label_status, hash_dedup)
           values (%s,%s,%s,%s,%s, coalesce(%s, now()), %s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (hash_dedup) do nothing returning id""",
        (tipe, judul[:300], url, sumber, ringkasan, published_at, kode_wilayah, zona_id,
         entitas_id, lat, lon, Json(meta or {}), label_status, h),
    )
    row = cur.fetchone()
    return row[0] if row else None


def brand_mentions(cur, item_id, brands_found, sumber, zona_id, kode_wilayah, waktu=None, engagement=0):
    """Every brand named in a new item becomes a mention signal. Returns first brand id."""
    first = None
    for nama in brands_found:
        eid = brand_id(cur, nama)
        first = first or eid
        add_signal(cur, eid, sumber, f"item{item_id}", zona_id, kode_wilayah, 1, engagement, waktu)
    if first:
        cur.execute("update item set entitas_id=%s where id=%s and entitas_id is null", (first, item_id))
    return first
