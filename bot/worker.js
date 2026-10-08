// Radar Jabodetabek - Telegram bot (Cloudflare Worker webhook).
//
// Secrets (wrangler secret put NAME):
//   BOT_TOKEN             from @BotFather
//   WEBHOOK_SECRET        random string, also passed to setWebhook (secret_token)
//   SUPABASE_URL          https://PROJECT.supabase.co
//   SUPABASE_SERVICE_KEY  service_role key (server-side only, never in the web)
//   ADMIN_IDS             comma-separated Telegram user ids allowed to /tambah_promo
// Vars (wrangler.toml): WEB_URL

const HELP = `Radar Jabodetabek - berita, promo makanan & tempat viral.

/berita [zona|kota] - berita terkini, mis. /berita bsd
/promo [zona|kota] - promo makanan, mis. /promo kemang
/viral [zona|kota] - lagi viral/ramai, mis. /viral depok
/baru [zona|kota] - tempat makan baru (OSM)
/zona - daftar zona
/langganan <zona|kota> - notifikasi tempat viral
/berhenti - hapus semua langganan
/lapor <zona> | <nama tempat> - laporkan tempat yang lagi ramai

Data diperbarui tiap 15-60 menit; "ramai" adalah perkiraan, bukan real-time.`;

const ADMIN_HELP = `/tambah_promo Brand | Judul | Harga/diskon | selesai YYYY-MM-DD | zona/kota (opsional) | url (opsional)`;

// ---------------------------------------------------------------- helpers
export function normalize(text) {
  return " " + (text || "").toLowerCase().replace(/'/g, "").replace(/[^a-z0-9]+/g, " ").trim() + " ";
}

export function parseCommand(text) {
  const t = (text || "").trim();
  if (!t.startsWith("/")) return { cmd: null, arg: t };
  const sp = t.indexOf(" ");
  const head = sp < 0 ? t : t.slice(0, sp);
  return { cmd: head.split("@")[0].toLowerCase(), arg: sp < 0 ? "" : t.slice(sp + 1).trim() };
}

/** Find the zone or city named in `text`. Zones win over cities; longest alias wins. */
export function findArea(text, zonas, wilayahs) {
  const t = normalize(text);
  if (t.trim() === "") return null;
  const cands = [];
  for (const z of zonas) {
    const kec = (z.kecuali || []).map((k) => normalize(k).trim());
    if (kec.some((k) => t.includes(` ${k} `))) continue;
    for (const a of [z.nama, ...(z.alias || [])]) {
      const n = normalize(a).trim();
      if (n && t.includes(` ${n} `)) cands.push({ len: n.length + 1000, area: { type: "zona", id: z.id, nama: z.nama, kode: z.kode_wilayah } });
    }
  }
  for (const w of wilayahs) {
    for (const a of [w.nama, ...(w.alias || [])]) {
      const n = normalize(a).trim();
      if (n && t.includes(` ${n} `)) cands.push({ len: n.length, area: { type: "kota", kode: w.kode, nama: w.nama } });
    }
  }
  if (!cands.length) return null;
  cands.sort((a, b) => b.len - a.len);
  return cands[0].area;
}

export function timeAgo(iso, now = Date.now()) {
  const m = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m} mnt lalu`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.round(h / 24)} hari lalu`;
}

export function rupiah(n) {
  return n == null ? "" : "Rp" + Math.round(n).toLocaleString("id-ID");
}

export function parseTambahPromo(arg) {
  const p = arg.split("|").map((s) => s.trim());
  const [brand, judul, harga, selesai, area, url] = p;
  if (!brand || !judul) return { error: "Format: " + ADMIN_HELP };
  if (selesai && !/^\d{4}-\d{2}-\d{2}$/.test(selesai)) return { error: "Tanggal selesai harus YYYY-MM-DD" };
  if (url && !/^https?:\/\//.test(url)) return { error: "URL harus diawali http:// atau https://" };
  return { brand, judul, harga: harga || null, selesai: selesai || null, area: area || null, url: url || null };
}

export function areaFilter(area, kind) {
  if (!area) return "";
  if (kind === "promo") {
    const k = encodeURIComponent(`{"${area.kode}"}`);
    return `&or=(kota_berlaku.cs.${k},kota_berlaku.eq.%7B%7D)`;
  }
  return area.type === "zona" ? `&zona_id=eq.${area.id}` : `&kode_wilayah=eq.${encodeURIComponent(area.kode)}`;
}

// ---------------------------------------------------------------- Supabase
async function sb(env, path, init = {}) {
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: env.SUPABASE_SERVICE_KEY,
      Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!r.ok && r.status !== 409) throw new Error(`supabase ${r.status}: ${await r.text()}`);
  const txt = await r.text();
  return txt ? JSON.parse(txt) : null;
}

let areaCache = { at: 0, zonas: [], wilayahs: [] };
async function areas(env) {
  if (Date.now() - areaCache.at < 10 * 60 * 1000) return areaCache;
  const [zonas, wilayahs] = await Promise.all([
    sb(env, "zona?select=id,nama,alias,kecuali,kode_wilayah&order=nama"),
    sb(env, "wilayah?select=kode,nama,alias,level&level=in.(kota,kabupaten,provinsi)"),
  ]);
  areaCache = { at: Date.now(), zonas, wilayahs };
  return areaCache;
}

async function resolve(env, arg) {
  if (!arg) return { area: null };
  const { zonas, wilayahs } = await areas(env);
  const area = findArea(arg, zonas, wilayahs);
  if (!area) return { error: `Area "${arg}" tidak dikenal. Lihat /zona.` };
  return { area };
}

const judulArea = (area) => (area ? area.nama : "Jabodetabek");

// ---------------------------------------------------------------- commands
async function cmdBerita(env, arg) {
  const { area, error } = await resolve(env, arg);
  if (error) return error;
  const rows = await sb(env, `v_berita?select=judul,url,sumber,published_at&order=published_at.desc&limit=8${areaFilter(area)}`);
  if (!rows.length) return `Belum ada berita untuk ${judulArea(area)}.`;
  return `📰 Berita ${judulArea(area)}\n\n` + rows.map((r) => `• ${r.judul}\n  ${r.sumber}, ${timeAgo(r.published_at)}\n  ${r.url}`).join("\n\n");
}

async function cmdPromo(env, arg) {
  const { area, error } = await resolve(env, arg);
  if (error) return error;
  const rows = await sb(env, `v_promo?select=brand,judul,harga,harga_teks,selesai,url&order=published_at.desc&limit=8${areaFilter(area, "promo")}`);
  if (!rows.length) return `Belum ada promo aktif untuk ${judulArea(area)}.`;
  return `🍜 Promo ${judulArea(area)}\n\n` + rows.map((r) => {
    const harga = r.harga_teks || rupiah(r.harga);
    return `• ${r.judul}` + (harga && !r.judul.includes(harga) ? ` (${harga})` : "") +
      (r.selesai ? `\n  s.d. ${r.selesai}` : "") + (r.url ? `\n  ${r.url}` : "");
  }).join("\n\n");
}

async function cmdViral(env, arg) {
  const { area, error } = await resolve(env, arg);
  if (error) return error;
  const rows = await sb(env, `v_viral?select=nama,zona,skor,tier,mention_24j,platform,detail,contoh_url&order=tier.asc,skor.desc&limit=10${areaFilter(area)}`);
  if (!rows.length) return `Belum ada data tempat yang dibicarakan di ${judulArea(area)}.`;
  return `🔥 Viral & lagi dibicarakan di ${judulArea(area)}\n\n` + rows.map((r, i) => {
    const jumlah = r.tier === 2 ? `${(r.detail && r.detail.mention_7h) || r.mention_24j} sebutan/7 hari` : `${r.mention_24j} sebutan/24 jam`;
    return `${i + 1}. ${r.tier === 2 ? "📈" : "🔥"} ${r.nama}${r.zona ? ` (${r.zona})` : ""} - ${jumlah}` +
      (r.contoh_url ? `\n   ${r.contoh_url}` : "");
  }).join("\n");
}

async function cmdBaru(env, arg) {
  const { area, error } = await resolve(env, arg);
  if (error) return error;
  const rows = await sb(env, `v_tempat_baru?select=nama,zona,lat,lon,baru_sejak&order=baru_sejak.desc&limit=10${areaFilter(area)}`);
  if (!rows.length) return `Belum ada tempat baru tercatat di ${judulArea(area)}.`;
  return `🆕 Tempat baru di ${judulArea(area)}\n\n` + rows.map((r) =>
    `• ${r.nama}${r.zona ? ` (${r.zona})` : ""}, ${timeAgo(r.baru_sejak)}\n  https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=18/${r.lat}/${r.lon}`).join("\n");
}

async function cmdZona(env) {
  const { zonas } = await areas(env);
  return "📍 Zona:\n" + zonas.map((z) => `• ${z.nama}` + (z.alias?.length ? ` (${z.alias.slice(0, 2).join(", ")})` : "")).join("\n") +
    "\n\nBisa juga pakai nama kota: jaksel, depok, bekasi, tangsel, bogor, ...";
}

async function cmdLangganan(env, chatId, arg) {
  if (!arg) return "Contoh: /langganan bsd";
  const { area, error } = await resolve(env, arg);
  if (error) return error;
  await sb(env, "langganan", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({ chat_id: chatId, zona_id: area.type === "zona" ? area.id : null, kode_wilayah: area.type === "kota" ? area.kode : null }),
  });
  return `✅ Kamu akan dapat notifikasi tempat viral di ${area.nama}. Hentikan dengan /berhenti.`;
}

async function cmdBerhenti(env, chatId) {
  await sb(env, `langganan?chat_id=eq.${chatId}`, { method: "DELETE" });
  return "Semua langganan dihapus.";
}

async function cmdLapor(env, arg) {
  const [areaTxt, nama] = (arg || "").split("|").map((s) => s.trim());
  if (!areaTxt || !nama) return "Format: /lapor <zona> | <nama tempat>\nContoh: /lapor Kemang | Kopi Kenangan Kemang Raya";
  const { area, error } = await resolve(env, areaTxt);
  if (error) return error;
  if (area.type !== "zona") return "Sebutkan zona (lihat /zona), bukan kota.";
  await sb(env, "laporan", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({ zona_id: area.id, nama_tempat: nama.slice(0, 120), jenis: "ramai", sumber: "bot" }),
  });
  return `Terima kasih! Laporan "${nama}" di ${area.nama} dicatat.`;
}

export function isAdmin(env, userId) {
  const admins = (env.ADMIN_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
  return userId != null && admins.includes(String(userId));
}

async function cmdTambahPromo(env, userId, arg) {
  if (!isAdmin(env, userId)) return "Perintah ini khusus admin.";
  const p = parseTambahPromo(arg);
  if (p.error) return p.error;
  let kode = null;
  if (p.area) {
    const { area, error } = await resolve(env, p.area);
    if (error) return error;
    kode = area.kode;
  }
  const judul = [p.brand, p.judul, p.harga].filter(Boolean).join(" - ");
  const [item] = await sb(env, "item", {
    method: "POST",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify({
      tipe: "promo", judul, url: p.url, sumber: "Kurasi manual", kode_wilayah: kode,
      label_status: "teks", hash_dedup: `manual:${Date.now()}:${judul}`.slice(0, 200),
    }),
  });
  await sb(env, "promo", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      item_id: item.id, brand: p.brand, menu: p.judul, harga_teks: p.harga, selesai: p.selesai,
      kota_berlaku: kode ? [kode] : [], sumber_input: "manual",
    }),
  });
  return `✅ Promo disimpan (#${item.id}): ${judul}`;
}

export async function handle(env, update) {
  const msg = update.message || update.edited_message;
  if (!msg?.text) return null;
  const { cmd, arg } = parseCommand(msg.text);
  const chatId = msg.chat.id;
  switch (cmd) {
    case "/start":
    case "/help":
      return HELP + (isAdmin(env, msg.from?.id) ? "\n\nAdmin:\n" + ADMIN_HELP : "") +
        (env.WEB_URL ? `\n\nWeb: ${env.WEB_URL}` : "");
    case "/berita": return cmdBerita(env, arg);
    case "/promo": return cmdPromo(env, arg);
    case "/viral": return cmdViral(env, arg);
    case "/baru": return cmdBaru(env, arg);
    case "/zona": return cmdZona(env);
    case "/langganan": return cmdLangganan(env, chatId, arg);
    case "/berhenti": return cmdBerhenti(env, chatId);
    case "/lapor": return cmdLapor(env, arg);
    case "/tambah_promo": return cmdTambahPromo(env, msg.from?.id, arg);
    default:
      return msg.chat.type === "private" ? "Perintah tidak dikenal. Ketik /help" : null;
  }
}

async function reply(env, chatId, text) {
  // Telegram limit is 4096 chars per message
  for (let i = 0; i < text.length; i += 4000) {
    await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: text.slice(i, i + 4000), disable_web_page_preview: true }),
    });
  }
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("Radar Jabodetabek bot OK");
    if (env.WEBHOOK_SECRET && req.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    let update;
    try {
      update = await req.json();
    } catch {
      return new Response("bad request", { status: 400 });
    }
    const chatId = (update.message || update.edited_message)?.chat?.id;
    try {
      const text = await handle(env, update);
      if (text && chatId) await reply(env, chatId, text);
    } catch (e) {
      console.error(e);
      if (chatId) await reply(env, chatId, "Maaf, terjadi kesalahan. Coba lagi nanti.");
    }
    // always 200, otherwise Telegram keeps retrying the same update
    return new Response("ok");
  },
};
