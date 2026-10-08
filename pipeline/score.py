"""Hourly viral score per (entity, zone).  python -m pipeline.score

Baselines are per zone, not per city, so a trend in Margonda is not drowned
out by Jakarta Selatan.
"""
import math
from collections import defaultdict
from datetime import timedelta

from pipeline.common import db, load_config, log, now_utc


def _mean_std(xs):
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def hitung_skor(signals, now, trends_up=frozenset(), laporan=None, cfg=None):
    """Pure scoring function (unit-tested).

    signals:   iterable of (entitas_id, zona_id, sumber, waktu, nilai, engagement)
    trends_up: entity ids whose Google Trends interest is rising
    laporan:   {(entitas_id, zona_id): count of user reports in last 24 h}
    Returns list of dicts sorted by score desc (only entries passing thresholds).
    """
    cfg = cfg or load_config("scoring")
    w = cfg["bobot"]
    mention_src = set(cfg["sumber_mention"])
    laporan = laporan or {}
    t24 = now - timedelta(hours=24)

    # per key: mentions per day-bucket (0 = last 24h, 1..14 = previous days)
    mentions = defaultdict(lambda: [0.0] * 15)
    engage = defaultdict(lambda: [0.0] * 15)
    sources24 = defaultdict(set)
    for ent, zona, sumber, waktu, nilai, eng in signals:
        if sumber not in mention_src:
            continue
        day = int((now - waktu).total_seconds() // 86400)
        if day < 0 or day > 14:
            continue
        k = (ent, zona)
        mentions[k][day] += nilai or 1
        engage[k][day] += eng or 0
        if waktu >= t24:
            sources24[k].add(sumber)

    out = []
    for k, days in mentions.items():
        m24 = days[0]
        ent, _ = k
        platforms = len(sources24[k]) + (1 if ent in trends_up else 0)
        if m24 < cfg["min_mention_24j"] or platforms < cfg["min_sumber"]:
            continue
        mean, std = _mean_std(days[1:])
        z = (m24 - mean) / max(std, 1.0)
        e24 = engage[k][0]
        e_base = sum(engage[k][1:]) / 14
        growth = max(-2.0, min(5.0, math.log1p(e24) - math.log1p(e_base)))
        n_lap = laporan.get(k, 0)
        bonus = min(cfg["bonus_maks"], cfg["bonus_per_laporan"] * n_lap)
        skor = w["mention"] * z + w["engagement"] * growth + w["platform"] * platforms + bonus
        out.append({
            "entitas_id": ent, "zona_id": k[1], "skor": round(skor, 4),
            "mention_24j": int(m24), "platform": platforms,
            "detail": {"z": round(z, 3), "growth": round(growth, 3), "baseline": round(mean, 3),
                       "sumber": sorted(sources24[k]), "laporan": n_lap,
                       "trends": ent in trends_up},
        })
    out.sort(key=lambda r: -r["skor"])
    return out


def proses_laporan(cur):
    """Turn crowd reports (web/bot) into entities + 'laporan' signals."""
    from pipeline.entities import BrandMatcher, add_signal, find_or_create

    brands = BrandMatcher()
    cur.execute("select l.id, l.entitas_id, l.zona_id, l.nama_tempat, z.kode_wilayah from laporan l "
                "left join zona z on z.id=l.zona_id where not l.diproses order by l.id limit 500")
    rows = cur.fetchall()
    for lid, ent, zona, nama, kode in rows:
        if not ent and nama and nama.strip():
            ent = find_or_create(cur, nama.strip(), zona_id=zona, kode_wilayah=kode, brands=brands)
        if ent:
            add_signal(cur, ent, "laporan", f"lap{lid}", zona, kode)
        cur.execute("update laporan set diproses=true, entitas_id=coalesce(entitas_id,%s) where id=%s", (ent, lid))
    if rows:
        log(f"laporan diproses: {len(rows)}")


def main():
    from psycopg2.extras import Json, execute_values

    cfg = load_config("scoring")
    now = now_utc()
    with db() as cur:
        proses_laporan(cur)
        cur.execute("select entitas_id, zona_id, sumber, waktu, nilai, engagement from sinyal "
                    "where waktu > now() - interval '15 days' and entitas_id is not null and sumber = any(%s)",
                    (cfg["sumber_mention"],))
        signals = cur.fetchall()

        # Trends: latest ratio per entity within 48 h
        cur.execute("""select distinct on (entitas_id) entitas_id, engagement from sinyal
                       where sumber='trends' and waktu > now() - interval '48 hours'
                       order by entitas_id, waktu desc""")
        trends_up = frozenset(e for e, ratio in cur.fetchall() if ratio and ratio >= cfg["trends_naik"])

        cur.execute("select entitas_id, zona_id, count(*) from sinyal where sumber='laporan' "
                    "and waktu > now() - interval '24 hours' group by 1, 2")
        laporan = {(e, z): n for e, z, n in cur.fetchall()}

        hasil = hitung_skor(signals, now, trends_up, laporan, cfg)
        per_zona = defaultdict(int)
        rows = []
        for r in hasil:
            per_zona[r["zona_id"]] += 1
            if per_zona[r["zona_id"]] <= cfg["top_per_zona"]:
                rows.append((r["entitas_id"], r["zona_id"], r["skor"], r["mention_24j"], r["platform"], Json(r["detail"])))

        cur.execute("delete from skor")
        if rows:
            execute_values(cur, "insert into skor (entitas_id, zona_id, skor, mention_24j, platform, detail) values %s", rows)
    log(f"skor: {len(signals)} sinyal -> {len(rows)} entri lolos ambang")


if __name__ == "__main__":
    main()
