"""Daily cleanup so the free 500 MB database never fills up.
python -m pipeline.cleanup

Retention (days) can be changed with env vars / GitHub secrets:
  RETENSI_BERITA_HARI  news + BMKG info          (default 14)
  RETENSI_POST_HARI    YouTube/Reddit posts      (default 30)
  RETENSI_PROMO_HARI   promos without an end date (default 60)
  RETENSI_SINYAL_HARI  viral signals             (default 30; scoring needs >= 15)
"""
from pipeline.common import db, env, log


def hari(name, default, minimum=1):
    return max(minimum, int(env(name, default)))


def main():
    hari_berita = hari("RETENSI_BERITA_HARI", 14)
    hari_post = hari("RETENSI_POST_HARI", 30)
    hari_promo = hari("RETENSI_PROMO_HARI", 60)
    hari_sinyal = hari("RETENSI_SINYAL_HARI", 30, minimum=15)  # 14-day baseline + today
    steps = [
        ("promo kedaluwarsa",
         "delete from item i using promo p where p.item_id=i.id and p.selesai < (now() at time zone 'Asia/Jakarta')::date - 1"),
        ("berita lama",
         f"delete from item where tipe in ('berita','info') and published_at < now() - interval '{hari_berita} days'"),
        ("video/post lama",
         f"delete from item where tipe = 'post' and published_at < now() - interval '{hari_post} days'"),
        ("promo tanpa tanggal lama",
         f"delete from item i using promo p where p.item_id=i.id and p.selesai is null "
         f"and i.published_at < now() - interval '{hari_promo} days'"),
        ("sinyal lama", f"delete from sinyal where waktu < now() - interval '{hari_sinyal} days'"),
        ("laporan lama", "delete from laporan where waktu < now() - interval '30 days'"),
        ("notif_log lama", "delete from notif_log where tanggal < current_date - 7"),
        ("statistik zona lama", "delete from zona_statistik where tanggal < current_date - 180"),
        ("halaman_cache lama", "delete from halaman_cache where diambil < now() - interval '90 days'"),
        ("geocode_cache lama", "delete from geocode_cache where dibuat < now() - interval '180 days'"),
        ("tempat tanpa sinyal", """delete from entitas e where e.tipe='tempat' and e.osm_id is null
             and e.dibuat < now() - interval '60 days'
             and not exists (select 1 from sinyal s where s.entitas_id=e.id)
             and not exists (select 1 from skor k where k.entitas_id=e.id)"""),
    ]
    total = 0
    with db() as cur:
        for nama, sql in steps:
            cur.execute(sql)
            total += cur.rowcount
            log(f"cleanup {nama}: {cur.rowcount}")
        cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
        log(f"cleanup selesai: {total} baris dihapus, ukuran database {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()