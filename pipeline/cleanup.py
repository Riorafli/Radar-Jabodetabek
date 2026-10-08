"""Weekly cleanup so the free 500 MB database never fills up.
python -m pipeline.cleanup
"""
from pipeline.common import db, env, log


def main():
    hari_item = int(env("RETENSI_ITEM_HARI", 60))
    hari_sinyal = int(env("RETENSI_SINYAL_HARI", 30))  # score needs >= 15 days
    steps = [
        ("promo kedaluwarsa",
         "delete from item i using promo p where p.item_id=i.id and p.selesai < (now() at time zone 'Asia/Jakarta')::date - 1"),
        ("item lama",
         f"delete from item where published_at < now() - interval '{hari_item} days' "
         "and id not in (select item_id from promo where selesai is null or selesai >= current_date)"),
        ("sinyal lama", f"delete from sinyal where waktu < now() - interval '{hari_sinyal} days'"),
        ("laporan lama", "delete from laporan where waktu < now() - interval '30 days'"),
        ("notif_log lama", "delete from notif_log where tanggal < current_date - 7"),
        ("statistik zona lama", "delete from zona_statistik where tanggal < current_date - 180"),
        ("halaman_cache lama", "delete from halaman_cache where diambil < now() - interval '90 days'"),
        ("tempat tanpa sinyal", """delete from entitas e where e.tipe='tempat' and e.osm_id is null
             and e.dibuat < now() - interval '60 days'
             and not exists (select 1 from sinyal s where s.entitas_id=e.id)
             and not exists (select 1 from skor k where k.entitas_id=e.id)"""),
    ]
    with db() as cur:
        for nama, sql in steps:
            cur.execute(sql)
            log(f"cleanup {nama}: {cur.rowcount}")
        cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
        log("ukuran database:", cur.fetchone()[0])


if __name__ == "__main__":
    main()
