"""Entity normalisation (brands.yaml + pg_trgm) and signal storage."""
from pipeline.common import load_config
from pipeline.geocode import normalize

SIMILARITY = 0.55  # pg_trgm similarity needed to treat two place names as the same


class BrandMatcher:
    def __init__(self, cfg=None):
        cfg = cfg or load_config("brands")
        self.brands = cfg.get("brand", [])
        self.alias = []
        for b in self.brands:
            for a in set(b.get("alias", []) + [b["nama"].lower()]):
                self.alias.append((normalize(a).strip(), b["nama"]))
        self.alias.sort(key=lambda x: -len(x[0]))

    def find(self, *texts):
        """All brand names mentioned in the text (canonical names, no dupes)."""
        t = normalize(" ".join(x or "" for x in texts))
        found = []
        for alias, nama in self.alias:
            if f" {alias} " in t and nama not in found:
                found.append(nama)
        return found

    def canonical(self, name):
        """'kokenang' -> 'Kopi Kenangan'; None if not a known brand."""
        t = normalize(name).strip()
        for alias, nama in self.alias:
            if t == alias:
                return nama
        return None


def brand_id(cur, nama):
    cur.execute("select id from entitas where tipe='brand' and lower(nama)=lower(%s) limit 1", (nama,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("insert into entitas (tipe, nama) values ('brand', %s) returning id", (nama,))
    return cur.fetchone()[0]


def find_or_create(cur, nama, zona_id=None, kode_wilayah=None, lat=None, lon=None,
                   brands=None, osm_id=None):
    """Return entitas id for a place name, merging near-duplicates in the same zone."""
    brands = brands or BrandMatcher()
    b = brands.canonical(nama) or (brands.find(nama)[:1] or [None])[0]
    if b:
        return brand_id(cur, b)
    if osm_id:
        cur.execute("select id from entitas where osm_id=%s", (osm_id,))
        row = cur.fetchone()
        if row:
            return row[0]
    else:
        cur.execute(
            """select id from entitas
               where tipe='tempat' and similarity(lower(nama), lower(%s)) >= %s
                 and (zona_id is not distinct from %s or zona_id is null or %s is null)
               order by similarity(lower(nama), lower(%s)) desc,
                        (zona_id is not distinct from %s) desc
               limit 1""",
            (nama, SIMILARITY, zona_id, zona_id, nama, zona_id),
        )
        row = cur.fetchone()
        if row:
            # fill in coordinates / zone we did not know before
            cur.execute("update entitas set lat=coalesce(lat,%s), lon=coalesce(lon,%s), "
                        "zona_id=coalesce(zona_id,%s), kode_wilayah=coalesce(kode_wilayah,%s) where id=%s",
                        (lat, lon, zona_id, kode_wilayah, row[0]))
            return row[0]
    cur.execute(
        "insert into entitas (tipe, nama, zona_id, kode_wilayah, lat, lon, osm_id) "
        "values ('tempat', %s, %s, %s, %s, %s, %s) returning id",
        (nama[:120], zona_id, kode_wilayah, lat, lon, osm_id),
    )
    return cur.fetchone()[0]


def add_signal(cur, entitas_id, sumber, ref="", zona_id=None, kode_wilayah=None,
               nilai=1.0, engagement=0.0, waktu=None):
    """Store one measurement. Same (entity, source, ref, zone) is stored once;
    a repeat only refreshes the engagement number (e.g. video views)."""
    cur.execute(
        """insert into sinyal (entitas_id, zona_id, kode_wilayah, sumber, ref, nilai, engagement, waktu)
           values (%s,%s,%s,%s,%s,%s,%s, coalesce(%s, now()))
           on conflict (entitas_id, sumber, ref, coalesce(zona_id, 0))
           do update set engagement = greatest(sinyal.engagement, excluded.engagement)""",
        (entitas_id, zona_id, kode_wilayah, sumber, ref, nilai, engagement, waktu),
    )
