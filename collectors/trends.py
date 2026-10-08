"""Google Trends via pytrends (unofficial -> bonus signal only).
python -m collectors.trends

Stores, per brand and province, the ratio "interest last 24 h / previous 6
days". score.py treats a ratio >= trends_naik as one extra platform.
Any failure exits quietly so the rest of the pipeline never depends on it.
"""
import time

from pipeline.common import db, load_config, log, today_wib
from pipeline.entities import add_signal, brand_id

GEO_KODE = {"ID-JK": "31", "ID-JB": "32", "ID-BT": "36"}


def ratio(series):
    """series: hourly/daily values over 7 days -> last-day mean / previous mean."""
    vals = [float(v) for v in series]
    if len(vals) < 8:
        return None
    n = max(1, len(vals) // 7)
    last, prev = vals[-n:], vals[:-n]
    base = sum(prev) / len(prev) if prev else 0
    if base <= 0:
        return None
    return round((sum(last) / len(last)) / base, 3)


def main():
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log("trends: pytrends tidak terpasang, dilewati")
        return
    cfg = load_config("sources").get("trends", {})
    brands = [b["nama"] for b in load_config("brands").get("brand", [])][: cfg.get("max_brand", 15)]
    try:
        pt = TrendReq(hl="id-ID", tz=-420, timeout=(10, 30), retries=2, backoff_factor=1.0)
    except Exception as e:
        log(f"trends: gagal inisialisasi ({e})")
        return
    n = 0
    tanggal = today_wib().isoformat()
    with db() as cur:
        for geo in cfg.get("geo", []):
            for i in range(0, len(brands), 5):
                group = brands[i:i + 5]
                try:
                    pt.build_payload(group, timeframe="now 7-d", geo=geo)
                    df = pt.interest_over_time()
                except Exception as e:
                    log(f"trends {geo} {group[0]}..: gagal ({type(e).__name__}), dilewati")
                    time.sleep(10)
                    continue
                if df is None or df.empty:
                    continue
                for b in group:
                    if b not in df:
                        continue
                    r = ratio(df[b].tolist())
                    if r is None:
                        continue
                    add_signal(cur, brand_id(cur, b), "trends", f"{geo}:{tanggal}", None,
                               GEO_KODE.get(geo), float(df[b].iloc[-1]), r)
                    n += 1
                time.sleep(5)
    log(f"trends: {n} sinyal")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never fail the workflow because of Trends
        log(f"trends: error diabaikan ({e})")
