"""Telegram notifications: newly viral places in subscribed zones/cities.
Subscriptions are made in the bot with /langganan <zona|kota>.
Each place is sent at most once per chat per day.
python -m pipeline.notify
"""
import time

from pipeline.common import db, env, http, load_config, log


def send(token, chat_id, text):
    r = http().post(f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=20)
    if r.status_code == 403:  # user blocked the bot -> drop subscription
        return "blocked"
    return r.ok


def main():
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        log("notify: TELEGRAM_BOT_TOKEN not set, skipped")
        return
    cfg = load_config("scoring")
    with db() as cur:
        cur.execute("select chat_id, zona_id, kode_wilayah from langganan")
        subs = cur.fetchall()
        sent = 0
        for chat_id, zona_id, kode in subs:
            cur.execute(
                """select v.entitas_id, v.nama, coalesce(v.zona, w.nama, 'Jabodetabek'), v.skor, v.mention_24j, v.contoh_url
                   from v_viral v left join wilayah w on w.kode = v.kode_wilayah
                   where v.skor >= %s
                     and ((%s::int is not null and v.zona_id = %s) or (%s::text is not null and v.kode_wilayah = %s))
                     and not exists (select 1 from notif_log n where n.chat_id=%s and n.entitas_id=v.entitas_id
                                     and n.tanggal=current_date)
                   order by v.skor desc limit %s""",
                (cfg["notif_min_skor"], zona_id, zona_id, kode, kode, chat_id, cfg["notif_top"]))
            rows = cur.fetchall()
            if not rows:
                continue
            lines = ["🔥 Lagi viral di area langgananmu:"]
            for _, nama, zona, skor, m24, url in rows:
                lines.append(f"• {nama} ({zona}) - {m24} sebutan/24 jam" + (f"\n  {url}" if url else ""))
            res = send(token, chat_id, "\n".join(lines))
            if res == "blocked":
                cur.execute("delete from langganan where chat_id=%s", (chat_id,))
                continue
            if res:
                sent += 1
                for ent, *_ in rows:
                    cur.execute("insert into notif_log values (%s,%s,current_date) on conflict do nothing", (chat_id, ent))
            time.sleep(0.05)  # Telegram limit ~30 msg/s
    log(f"notify: {sent} pesan terkirim ke {len(subs)} langganan")


if __name__ == "__main__":
    main()
