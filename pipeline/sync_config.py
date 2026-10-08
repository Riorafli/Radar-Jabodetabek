"""Push config/*.yaml (wilayah, zones, brands) into the database.

Run after editing any of those files:  python -m pipeline.sync_config
(GitHub Actions does this automatically on every push that touches config/.)
"""
from pipeline.common import db, load_config, log


def main():
    w = load_config("wilayah")
    z = load_config("zones")
    b = load_config("brands")
    with db() as cur:
        for p in w.get("provinsi", []):
            cur.execute(
                """insert into wilayah (kode, nama, level, alias, lat, lon) values (%s,%s,'provinsi',%s,%s,%s)
                   on conflict (kode) do update set nama=excluded.nama, alias=excluded.alias,
                     lat=excluded.lat, lon=excluded.lon""",
                (p["kode"], p["nama"], p.get("alias", []), p.get("lat"), p.get("lon")))
        for r in w.get("wilayah", []):
            cur.execute(
                """insert into wilayah (kode, nama, level, parent_kode, bagian, alias, lat, lon)
                   values (%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (kode) do update set nama=excluded.nama, level=excluded.level,
                     parent_kode=excluded.parent_kode, bagian=excluded.bagian, alias=excluded.alias,
                     lat=excluded.lat, lon=excluded.lon""",
                (r["kode"], r["nama"], r["level"], r["kode"].split(".")[0], r.get("bagian"),
                 r.get("alias", []), r.get("lat"), r.get("lon")))

        cur.execute("insert into kawasan (nama) values (%s) on conflict (nama) do nothing", (w.get("kawasan", "Jabodetabek"),))
        cur.execute("select id from kawasan where nama=%s", (w.get("kawasan", "Jabodetabek"),))
        kid = cur.fetchone()[0]
        for r in w.get("wilayah", []):
            cur.execute("insert into kawasan_wilayah values (%s,%s) on conflict do nothing", (kid, r["kode"]))

        for zz in z.get("zona", []):
            cur.execute(
                """insert into zona (nama, kode_wilayah, lat, lon, radius_m, alias, kecuali)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (nama) do update set kode_wilayah=excluded.kode_wilayah, lat=excluded.lat,
                     lon=excluded.lon, radius_m=excluded.radius_m, alias=excluded.alias, kecuali=excluded.kecuali""",
                (zz["nama"], zz["kota"], zz["lat"], zz["lon"], zz.get("radius_m", 1500),
                 zz.get("alias", []), zz.get("kecuali", [])))

        for br in b.get("brand", []):
            cur.execute("select id from entitas where tipe='brand' and lower(nama)=lower(%s)", (br["nama"],))
            row = cur.fetchone()
            if row:
                cur.execute("update entitas set alias=%s where id=%s", (br.get("alias", []), row[0]))
            else:
                cur.execute("insert into entitas (tipe, nama, alias) values ('brand',%s,%s)", (br["nama"], br.get("alias", [])))

    log(f"sync ok: {len(w.get('wilayah', []))} wilayah, {len(z.get('zona', []))} zona, {len(b.get('brand', []))} brand")


if __name__ == "__main__":
    main()
