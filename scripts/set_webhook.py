"""Point the Telegram bot at the Cloudflare Worker and register the command menu.

Usage (values from .env or environment):
  TELEGRAM_BOT_TOKEN=...  WORKER_URL=https://radar-jabodetabek-bot.NAME.workers.dev  WEBHOOK_SECRET=...
  python scripts/set_webhook.py
WEBHOOK_SECRET must be the same value you stored with `wrangler secret put WEBHOOK_SECRET`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import env, http  # noqa: E402

COMMANDS = [
    ("berita", "Berita terkini, mis. /berita bsd"),
    ("promo", "Promo makanan, mis. /promo kemang"),
    ("viral", "Tempat viral/ramai, mis. /viral depok"),
    ("baru", "Tempat makan baru"),
    ("zona", "Daftar zona"),
    ("langganan", "Notifikasi tempat viral di suatu zona"),
    ("berhenti", "Hapus semua langganan"),
    ("lapor", "Laporkan tempat ramai: /lapor zona | nama"),
    ("help", "Bantuan"),
]


def main():
    token, url, secret = env("TELEGRAM_BOT_TOKEN"), env("WORKER_URL"), env("WEBHOOK_SECRET")
    if not (token and url and secret):
        sys.exit("Set TELEGRAM_BOT_TOKEN, WORKER_URL and WEBHOOK_SECRET first (see docstring).")
    api = f"https://api.telegram.org/bot{token}"
    r = http().post(f"{api}/setWebhook", json={
        "url": url, "secret_token": secret, "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": True}, timeout=20)
    print("setWebhook:", r.json())
    r = http().post(f"{api}/setMyCommands", json={
        "commands": [{"command": c, "description": d} for c, d in COMMANDS]}, timeout=20)
    print("setMyCommands:", r.json())
    print("getWebhookInfo:", http().get(f"{api}/getWebhookInfo", timeout=20).json())


if __name__ == "__main__":
    main()
