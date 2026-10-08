# Radar Jabodetabek

News, food promos and viral/busy places for Jabodetabek, filtered per city and
per popular zone (Kemang, BSD, Margonda, …). Web + Telegram bot. Runs entirely
on free tiers, with no credit card: GitHub Actions, Supabase, Cloudflare Pages/Workers,
Gemini/Groq, YouTube Data API, OpenStreetMap.

Implements `Blueprint_Radar_Jabodetabek.docx` and all 12 stages of
`Panduan_Step_by_Step_Radar_Jabodetabek.docx`.

```
GitHub Actions (cron)                         Supabase Postgres (+PostGIS, pg_trgm, RLS)
  news  /15m : rss, bmkg, gdelt, dedup, geocode ─┐        │
  promo /3h  : promo pages -> LLM -> JSON        ├──────► │ ◄── web/ (Cloudflare Pages, anon key, read-only)
  viral /2h  : youtube, reddit, trends           │        │ ◄── bot/ (Cloudflare Worker, service key)
  osm   daily: Overpass POIs per zone            │        │
  score /1h  : viral score per zone + notify ────┘        │
  maintenance: sync config on push, daily cleanup
```

## What is where

| Path | What |
|---|---|
| `db/schema.sql` | All tables, indexes, views (`v_berita`, `v_promo`, `v_viral`, `v_tempat_baru`), RLS policies. Idempotent. |
| `config/wilayah.yaml` | 14 kota/kabupaten with Kemendagri codes + aliases + centres |
| `config/zones.yaml` | 20 popular zones (centre + radius + aliases + `kecuali` for ambiguous names) |
| `config/brands.yaml` | 25 food brands + aliases (`kokenang` → Kopi Kenangan) |
| `config/sources.yaml` | RSS feeds, BMKG, GDELT, promo pages, YouTube queries, Trends, Reddit, OSM |
| `config/scoring.yaml` | Viral score weights (0.5/0.3/0.2), thresholds, notification settings |
| `collectors/` | `rss`, `bmkg`, `gdelt`, `promo`, `youtube`, `trends`, `reddit`, `osm` |
| `pipeline/` | `geocode` (text → zone/city, LLM + Nominatim fallback), `extract_llm`, `entities`, `dedup`, `score`, `notify`, `cleanup`, `sync_config` |
| `web/` | Static site: news / promo / viral / map tabs, area filter, "Dekat saya", crowd reports. Demo mode until configured. |
| `bot/` | Telegram bot Worker: `/berita /promo /viral /baru /zona /langganan /berhenti /lapor /tambah_promo` |
| `scripts/` | `check_setup.py`, `set_webhook.py`, `make_demo.py` |
| `.github/workflows/` | `news`, `promo`, `viral`, `osm`, `score`, `maintenance`, `test` |

## Try it right now (no accounts needed)

```bash
python -m http.server 8765 --directory web
```

Open http://localhost:8765, which shows demo mode with sample data, all marked "Contoh".

## One-time setup (~2 hours)

Never put a key in the code: the repo is public. Keys go in **GitHub Secrets**,
**Worker secrets**, or your local `.env` (git-ignored).

### 1. Accounts
Free accounts, no credit card: GitHub, Supabase, Cloudflare, Telegram,
Google AI Studio (Gemini key). Optional: Groq (LLM fallback), Google Cloud
(YouTube Data API v3 key; enable the API, no billing), Reddit app.

### 2. Supabase
1. New project (region Singapore). Save the database password.
2. **SQL Editor** → paste all of `db/schema.sql` → Run. (It enables `postgis` and `pg_trgm` itself.)
3. **Connect → Session pooler** → copy the connection string → this is `DATABASE_URL`.
4. **Project Settings → API** → copy *Project URL*, *anon public* key, *service_role* key.

### 3. GitHub repo
1. Create a **public** repo `radar-jabodetabek` (public = unlimited Actions minutes) and push this folder.
2. **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required | Value |
|---|---|---|
| `DATABASE_URL` | yes | Session pooler string |
| `GEMINI_API_KEY` | yes* | aistudio.google.com/apikey |
| `GROQ_API_KEY` | optional* | fallback LLM (*at least one of the two) |
| `YOUTUBE_API_KEY` | recommended | main viral signal |
| `TELEGRAM_BOT_TOKEN` | for notifications | from @BotFather (step 6) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | optional | check Reddit's API terms first |
| `CONTACT_EMAIL` | recommended | used in the User-Agent for Nominatim/Overpass |

3. **Actions** tab → enable workflows → run **maintenance** manually first. That loads
   the regions, zones and brands into the database. Then run **news**, **osm**, **viral** and **score**
   once each (Run workflow) and check they are green.

Check everything locally at any point:
```bash
pip install -r requirements.txt
```
```bash
python scripts/check_setup.py
```

### 4. Web on Cloudflare Pages
1. Edit `web/config.js`: `SUPABASE_URL` + **anon** key (safe because RLS only allows reads).
   **Never** the service_role key. Commit + push.
2. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → pick the repo.
   Framework: *None*, build command: *empty*, output directory: `web`. Every push redeploys.

### 5. Telegram bot
1. Telegram → @BotFather → `/newbot` → save the token. Get your own user id from @userinfobot.
2. Deploy the Worker:
```bash
cd bot
```
```bash
npm install
```
```bash
npx wrangler login
```
```bash
npx wrangler deploy
```
3. Set its secrets (each command prompts for the value):
```bash
npx wrangler secret put BOT_TOKEN
```
```bash
npx wrangler secret put WEBHOOK_SECRET
```
```bash
npx wrangler secret put SUPABASE_URL
```
```bash
npx wrangler secret put SUPABASE_SERVICE_KEY
```
```bash
npx wrangler secret put ADMIN_IDS
```
   `WEBHOOK_SECRET` is any long random string you make up.
4. Connect Telegram to the Worker: put `TELEGRAM_BOT_TOKEN`, `WORKER_URL` (from the deploy output)
   and the same `WEBHOOK_SECRET` in `.env`, then:
```bash
python scripts/set_webhook.py
```
5. Send `/start` to your bot.

### 6. Monitoring
- GitHub → profile **Settings → Notifications → Actions**: email on failed workflows.
- UptimeRobot (free): monitor your Pages URL and the Worker URL.
- Supabase dashboard: check database size weekly (`maintenance` logs it too).

## Day-to-day

| Want to… | Do this |
|---|---|
| Add/adjust a zone | Edit `config/zones.yaml`, push. `maintenance` syncs it. Verify coordinates on openstreetmap.org. |
| Add a brand alias | Edit `config/brands.yaml`, push. |
| Add a news feed | Add to `config/sources.yaml` → `rss`. `filter_wilayah: true` for national feeds. |
| Add a promo page | Add to `sources.yaml` → `promo`. Check robots.txt + ToS. The collector also enforces robots.txt. |
| Instagram-only promo | In the bot (admin): `/tambah_promo Brand \| Judul \| Diskon 20% \| 2026-12-31 \| bsd \| https://…` |
| Tune "viral" | `config/scoring.yaml`. Review the top list weekly. Early on, with little data, try `min_mention_24j: 2`. |
| Regenerate demo data | `python scripts/make_demo.py` |
| Run one collector locally | Fill `.env`, then e.g. `python -m collectors.rss` |
| Run tests | `python -m pytest -q` and `node --test bot/worker.test.js` |

### Free-quota budget
| Service | Limit | Usage here |
|---|---|---|
| GitHub Actions | unlimited (public repo) | ~170 short runs/day |
| YouTube Data API | 10,000 units/day | 4 searches × 12 runs ≈ 4,900 units |
| Gemini/Groq | per-minute/day limits | promo pages only when the page text changes; place/location extraction batched (1 call per run) |
| Nominatim | 1 req/s | max 15 lookups per news run, cached forever |
| Overpass | fair use | 20 queries/day at 03:00 WIB, 5 s apart |
| Supabase | 500 MB | daily cleanup (02:30 WIB): news > 14 days, videos > 30 days, expired promos, signals > 30 days. Change with repo variables `RETENSI_BERITA_HARI` / `RETENSI_POST_HARI`. |

## Things to know

- **Region codes:** the blueprint lists `31.71–31.75` without the order. Verified against BMKG
  (Kemendagri): **31.71 Jakarta Pusat, 31.72 Utara, 31.73 Barat, 31.74 Selatan, 31.75 Timur**.
  BPS numbering differs (BPS 3171 = Jaksel), so don't mix datasets.
- **Sources tested 2026-10-08:** 12 RSS feeds work. Kompas megapolitan (404), Tempo metro (403),
  Radar Bogor and Radar Depok (timeouts) did not, and are left out. Of the promo pages, McDonald's,
  HokBen, Richeese, BCA, Mandiri and ShopeePay have readable static text. KFC, Pizza Hut, Domino's,
  Starbucks and Grand Indonesia need JavaScript and are listed but `aktif: false`. Use the bot's
  manual curation for those.
- GoFood/GrabFood/ShopeeFood, Instagram/TikTok/X APIs and Google Places are deliberately not used (ToS / cost).
- News stores only title, a summary of up to 300 characters, and the link (copyright). No personal user data
  is stored, except Telegram chat ids of people who `/langganan`, which `/berhenti` deletes (UU PDP).
- "Ramai" is an estimate from mention spikes, not live crowd data. Updates lag 15–60 min (free cron).
- GitHub disables cron on repos with no activity for 60 days. Push a commit or run a workflow manually.

## Troubleshooting

| Symptom | Fix |
|---|---|
| DB connection fails in Actions | Use the **Session pooler** string, not the direct host (IPv6). |
| `violates foreign key constraint ... wilayah` | Run the **maintenance** workflow (config not synced yet). |
| Web shows "Gagal memuat data" | Wrong URL/anon key in `web/config.js`, or `schema.sql` not run (grants/RLS). |
| Bot does not answer | `python scripts/set_webhook.py` → check `getWebhookInfo.last_error_message`. Use the same `WEBHOOK_SECRET` in both places. |
| Promo: "teks terlalu sedikit" | Page needs JavaScript. Set `aktif: false` and use `/tambah_promo`. |
| LLM returns invalid JSON | Logged and skipped automatically. If it is frequent, switch `GEMINI_MODEL` (default `gemini-flash-lite-latest`) or add `GROQ_API_KEY`. |
| Viral list empty | Normal at first: needs ≥3 mentions from ≥2 platforms in 24 h. Check the `viral` logs, then lower thresholds in `scoring.yaml`. |
| Wrong city on a news item | Add/adjust aliases or `kecuali` in `zones.yaml` / `wilayah.yaml`. |
| YouTube quota exceeded | Lower `youtube.per_run` in `sources.yaml`. |

## Final checklist (from the guide)
- [ ] Public repo, no secrets in code
- [ ] Supabase: PostGIS + pg_trgm on, RLS on (`check_setup.py` all OK)
- [ ] `news` runs every 15 min, green
- [ ] Most items have a city/zone label
- [ ] Web on Cloudflare Pages, city filter works
- [ ] Promo pages extracted and validated
- [ ] Bot answers `/berita`, `/promo`, `/viral`
- [ ] YouTube/Trends/OSM signals stored
- [ ] Zone scores computed and reviewed manually
- [ ] Map and "Dekat saya" work
- [ ] Cleanup + monitoring active
