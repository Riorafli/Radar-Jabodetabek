"""OSM Overpass: cafes/restaurants per zone (daily).  python -m collectors.osm

- zona_statistik: POI count per zone per day ("area yang sedang tumbuh")
- a POI that was not there yesterday becomes an entity + 'osm_baru' signal
  (new place). The first run for a zone only seeds the list.
Public Overpass server: one query per zone, 5 s apart.
"""
import time

from pipeline.common import db, http, load_config, log
from pipeline.entities import add_signal

QUERY = """[out:json][timeout:90];
(
  node["amenity"~"^({am})$"](around:{r},{lat},{lon});
  way["amenity"~"^({am})$"](around:{r},{lat},{lon});
);
out center tags;"""


def fetch(endpoint, zone, amenity):
    q = QUERY.format(am="|".join(amenity), r=zone["radius_m"], lat=zone["lat"], lon=zone["lon"])
    r = http().post(endpoint, data={"data": q}, timeout=120)
    r.raise_for_status()
    out = []
    for el in r.json().get("elements", []):
        tags = el.get("tags", {})
        nama = tags.get("name")
        if not nama:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        out.append({"osm_id": f"{el['type']}/{el['id']}", "nama": nama[:120], "lat": lat, "lon": lon})
    return out


def main():
    cfg = load_config("sources").get("osm", {})
    with db() as cur:
        cur.execute("select id, nama, kode_wilayah, lat, lon, radius_m from zona order by id")
        zones = [dict(zip(("id", "nama", "kode", "lat", "lon", "radius_m"), z)) for z in cur.fetchall()]
    for z in zones:
        try:
            pois = fetch(cfg["endpoint"], z, cfg.get("amenity", ["cafe", "restaurant"]))
        except Exception as e:
            log(f"osm {z['nama']}: gagal ({e})")
            time.sleep(10)
            continue
        with db() as cur:
            cur.execute("select count(*) from zona_statistik where zona_id=%s", (z["id"],))
            seed = cur.fetchone()[0] == 0
            cur.execute("select osm_id from entitas where osm_id = any(%s)", ([p["osm_id"] for p in pois],))
            known = {r[0] for r in cur.fetchall()}
            baru = 0
            for p in pois:
                if p["osm_id"] in known:
                    continue
                cur.execute("""insert into entitas (tipe, nama, zona_id, kode_wilayah, lat, lon, osm_id, baru_sejak)
                               values ('tempat',%s,%s,%s,%s,%s,%s, case when %s then null else now() end)
                               on conflict (osm_id) do nothing returning id""",
                            (p["nama"], z["id"], z["kode"], p["lat"], p["lon"], p["osm_id"], seed))
                row = cur.fetchone()
                if row and not seed:
                    add_signal(cur, row[0], "osm_baru", p["osm_id"], z["id"], z["kode"])
                    baru += 1
            cur.execute("""insert into zona_statistik (zona_id, tanggal, jumlah_poi, poi_baru)
                           values (%s, (now() at time zone 'Asia/Jakarta')::date, %s, %s)
                           on conflict (zona_id, tanggal) do update set jumlah_poi=excluded.jumlah_poi,
                             poi_baru=zona_statistik.poi_baru + excluded.poi_baru""",
                        (z["id"], len(pois), baru))
        log(f"osm {z['nama']}: {len(pois)} POI, {baru} baru" + (" (seed)" if seed else ""))
        time.sleep(5)


if __name__ == "__main__":
    main()
