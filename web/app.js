(() => {
  "use strict";
  const C = window.RADAR_CONFIG || {};
  const DEMO = !C.SUPABASE_URL || /PROJECT/.test(C.SUPABASE_URL) || !C.SUPABASE_ANON_KEY || /ANON_PUBLIC_KEY/.test(C.SUPABASE_ANON_KEY);
  const PAGE = 20;
  const REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s) => document.querySelector(s);

  // ------------------------------------------------------------ utils
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  /** stable hue 0-359 from a string, for brand/source colours */
  const hue = (s) => { let h = 0; for (const c of String(s || "")) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
  const initials = (s) => String(s || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";

  function timeAgo(iso) {
    const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (m < 1) return "baru saja";
    if (m < 60) return `${m} mnt lalu`;
    const h = Math.round(m / 60);
    return h < 24 ? `${h} jam lalu` : `${Math.round(h / 24)} hari lalu`;
  }
  const tgl = (d) => new Date(d + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
  const rupiah = (n) => (n == null ? "" : "Rp" + Math.round(n).toLocaleString("id-ID"));
  function daysLeft(d) {
    if (!d) return null;
    const end = new Date(d + "T23:59:59");
    return Math.floor((end - Date.now()) / 86400000);
  }

  function haversine(lat1, lon1, lat2, lon2) {
    const r = 6371000, rad = Math.PI / 180;
    const dp = (lat2 - lat1) * rad, dl = (lon2 - lon1) * rad;
    const a = Math.sin(dp / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dl / 2) ** 2;
    return 2 * r * Math.asin(Math.sqrt(a));
  }

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2800);
  }

  function countUp(el, to) {
    const from = Number(el.dataset.v || 0);
    el.dataset.v = to;
    // no animation when reduced motion is on or the tab is hidden (rAF does not run there)
    if (REDUCED || from === to || document.hidden) { el.textContent = to.toLocaleString("id-ID"); return; }
    const t0 = performance.now(), dur = 900;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(from + (to - from) * e).toLocaleString("id-ID");
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  const skeleton = (n) => Array.from({ length: n }, () => `<li class="sk" aria-hidden="true"><i></i><i></i><i></i></li>`).join("");

  // ------------------------------------------------------------ data layer
  const headers = () => ({ apikey: C.SUPABASE_ANON_KEY, Authorization: `Bearer ${C.SUPABASE_ANON_KEY}`, "content-type": "application/json" });
  async function rest(path, init = {}) {
    const r = await fetch(`${C.SUPABASE_URL}/rest/v1/${path}`, { ...init, headers: { ...headers(), ...(init.headers || {}) } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const t = await r.text();
    return t ? JSON.parse(t) : null;
  }
  async function count(path) {
    const r = await fetch(`${C.SUPABASE_URL}/rest/v1/${path}`, { method: "HEAD", headers: { ...headers(), Prefer: "count=exact" } });
    const cr = r.headers.get("content-range") || "";
    return Number(cr.split("/")[1]) || 0;
  }

  function areaQS(area, kind) {
    if (!area) return "";
    if (kind === "promo") return `&or=(kota_berlaku.cs.${encodeURIComponent(`{"${area.kode}"}`)},kota_berlaku.eq.%7B%7D)`;
    return area.type === "zona" ? `&zona_id=eq.${area.id}` : `&kode_wilayah=eq.${encodeURIComponent(area.kode)}`;
  }
  function areaMatch(row, area, kind) {
    if (!area) return true;
    if (kind === "promo") return !row.kota_berlaku.length || row.kota_berlaku.includes(area.kode);
    return area.type === "zona" ? row.zona_id === area.id : row.kode_wilayah === area.kode;
  }
  const D = () => window.RADAR_DEMO;

  const data = {
    async areas() {
      if (DEMO) return { zonas: D().zona, wilayahs: D().wilayah };
      const [zonas, wilayahs] = await Promise.all([
        rest("zona?select=id,nama,alias,kode_wilayah,lat,lon,radius_m&order=nama"),
        rest("wilayah?select=kode,nama,level,lat,lon&level=in.(kota,kabupaten)&order=kode"),
      ]);
      return { zonas, wilayahs };
    },
    async stats(area) {
      if (DEMO) {
        const d = D();
        return { berita: d.berita.filter((r) => areaMatch(r, area)).length, promo: d.promo.filter((r) => areaMatch(r, area, "promo")).length,
          video: 37, tempat: 1274, updated: d.berita[0] && d.berita[0].published_at };
      }
      const [berita, promo, video, tempat, last] = await Promise.all([
        count(`v_berita?select=id${areaQS(area)}`),
        count(`v_promo?select=id${areaQS(area, "promo")}`),
        count(`item?select=id&tipe=eq.post${areaQS(area)}`),
        count(`entitas?select=id&tipe=eq.tempat${areaQS(area)}`),
        rest("item?select=dibuat&order=dibuat.desc&limit=1"),
      ]);
      return { berita, promo, video, tempat, updated: last && last[0] && last[0].dibuat };
    },
    async berita(area, q, offset) {
      const clean = (q || "").replace(/[,()*%]/g, " ").trim();
      if (DEMO) {
        return D().berita.filter((r) => areaMatch(r, area) && (!clean || r.judul.toLowerCase().includes(clean.toLowerCase())))
          .slice(offset, offset + PAGE);
      }
      const qs = clean ? `&judul=ilike.${encodeURIComponent(`*${clean}*`)}` : "";
      return rest(`v_berita?select=id,tipe,judul,url,sumber,ringkasan,published_at,wilayah,zona&order=published_at.desc&limit=${PAGE}&offset=${offset}${areaQS(area)}${qs}`);
    },
    async promo(area) {
      if (DEMO) return D().promo.filter((r) => areaMatch(r, area, "promo"));
      return rest(`v_promo?select=id,brand,judul,menu,harga,harga_teks,selesai,syarat,url,sumber,kota_berlaku,sumber_input,kategori,platform,produk,lokasi,diskon_persen,selesai_perkiraan,lat,lon,published_at,jenis,halal&order=published_at.desc&limit=300${areaQS(area, "promo")}`);
    },
    async outlets(brands) {
      if (DEMO || !brands.length) return [];
      const pats = brands.slice(0, 60).map((b) => `nama.ilike."*${b.replace(/[^A-Za-z0-9]+/g, "*")}*"`);
      return rest(`entitas?select=nama,lat,lon,kode_wilayah&osm_id=not.is.null&lat=not.is.null&or=(${encodeURIComponent(pats.join(","))})&limit=5000`);
    },
    async viral(area) {
      if (DEMO) return D().viral.filter((r) => areaMatch(r, area)).sort((a, b) => (a.tier || 1) - (b.tier || 1) || b.skor - a.skor).slice(0, 30);
      return rest(`v_viral?select=entitas_id,nama,zona_id,zona,kode_wilayah,skor,tier,mention_24j,platform,detail,lat,lon,contoh_url&order=tier.asc,skor.desc&limit=30${areaQS(area)}`);
    },
    async baru(area) {
      if (DEMO) return D().baru.filter((r) => areaMatch(r, area));
      return rest(`v_tempat_baru?select=id,nama,lat,lon,zona_id,zona,kode_wilayah,baru_sejak&order=baru_sejak.desc&limit=30${areaQS(area)}`);
    },
    async gtrends() {
      if (DEMO) {
        return [["kuliner viral", 20000, "Contoh berita kuliner"], ["contoh brand kopi", 5000, "Contoh promo baru"],
          ["contoh konser", 2000, "Contoh berita hiburan"]].map(([judul, traffic, ringkasan]) =>
          ({ judul, ringkasan, url: "https://example.com/", meta: { traffic, traffic_teks: `${traffic}+` } }));
      }
      const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
      return rest(`item?select=judul,url,ringkasan,meta,published_at&sumber=eq.${encodeURIComponent("Google Trends")}&published_at=gt.${encodeURIComponent(since)}&order=published_at.desc&limit=40`);
    },
    async lapor(body) {
      if (DEMO) return;
      await rest("laporan", { method: "POST", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ ...body, sumber: "web" }) });
    },
  };

  // ------------------------------------------------------------ state
  const S = { tab: "berita", area: null, zonas: [], wilayahs: [], offset: 0, q: "", map: null, layers: null, me: null,
    promos: [], outlets: [], outletKey: null,
    pf: { k: "semua", p: "semua", s: "baru", q: "", pasti: false, j: "semua", h: "semua" } };
  try { Object.assign(S.pf, JSON.parse(store.get("promoFilter") || "{}"), { q: "" }); } catch { /* ignore */ }

  function areaFromValue(v) {
    if (!v || v === "all") return null;
    const [t, id] = [v.slice(0, 1), v.slice(2)];
    if (t === "z") {
      const z = S.zonas.find((x) => String(x.id) === id);
      return z && { type: "zona", id: z.id, nama: z.nama, kode: z.kode_wilayah, lat: z.lat, lon: z.lon };
    }
    const w = S.wilayahs.find((x) => x.kode === id);
    return w && { type: "kota", kode: w.kode, nama: w.nama, lat: w.lat, lon: w.lon };
  }
  const areaValue = (a) => (!a ? "all" : a.type === "zona" ? `z:${a.id}` : `k:${a.kode}`);
  const areaName = () => (S.area ? S.area.nama : "Jabodetabek");
  const saveHash = () => history.replaceState(null, "", `#${S.tab}/${areaValue(S.area)}`);

  // ------------------------------------------------------------ renderers
  const empty = (msg) => `<li class="empty">${esc(msg)}</li>`;
  const fail = (el, e) => { el.innerHTML = empty("Gagal memuat data. Coba lagi nanti."); console.error(e); };

  async function renderStats() {
    $("#hero-area").textContent = areaName();
    try {
      const s = await data.stats(S.area);
      for (const el of document.querySelectorAll("[data-count]")) countUp(el, s[el.dataset.count] || 0);
      $("#updated").textContent = s.updated ? `· diperbarui ${timeAgo(s.updated)}` : "";
    } catch (e) { console.error(e); }
  }

  async function renderBerita(append = false) {
    const el = $("#list-berita");
    $("#h-berita").textContent = `Berita terkini · ${areaName()}`;
    if (!append) { S.offset = 0; el.innerHTML = skeleton(5); }
    try {
      const rows = await data.berita(S.area, S.q, S.offset);
      const html = rows.map((r, i) => {
        const url = safeUrl(r.url);
        const where = r.zona || r.wilayah;
        return `<li class="${r.tipe === "info" ? "info" : ""}" style="--i:${i}">
          ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.judul)}</a>` : `<span class="title">${esc(r.judul)}</span>`}
          ${r.ringkasan ? `<p class="sum">${esc(r.ringkasan)}</p>` : ""}
          <div class="meta">${r.tipe === "info" ? '<span class="chip info">⚠️ Info layanan</span>' : ""}
            ${where ? `<span class="chip">📍 ${esc(where)}</span>` : ""}
            <span class="src" style="--h:${hue(r.sumber)}">${esc(initials(r.sumber).slice(0, 1))}</span><span>${esc(r.sumber)}</span>·<span>${timeAgo(r.published_at)}</span></div>
        </li>`;
      }).join("");
      if (append) el.insertAdjacentHTML("beforeend", html);
      else el.innerHTML = html || empty(`Belum ada berita untuk ${areaName()}.`);
      S.offset += rows.length;
      $("#more-berita").hidden = rows.length < PAGE;
    } catch (e) { fail(el, e); }
  }

  const kodeNama = (k) => (S.wilayahs.find((w) => w.kode === k) || {}).nama || k;

  function sisaChip(selesai, perkiraan) {
    const d = daysLeft(selesai);
    if (d == null) return `<span class="chip good">Periode tidak disebut</span>`;
    if (perkiraan) return `<span class="chip soft" title="Sumber tidak menyebut tanggal berakhir">± s.d. ${esc(tgl(selesai))}</span>`;
    if (d <= 0) return `<span class="chip urgent">⏰ Berakhir hari ini</span>`;
    if (d <= 3) return `<span class="chip urgent">⏰ ${d} hari lagi</span>`;
    return `<span class="chip">s.d. ${esc(tgl(selesai))}</span>`;
  }

  const KAT = {
    makanan: { ikon: "🍜", nama: "Makanan" },
    marketplace: { ikon: "🛒", nama: "Marketplace" },
    cuci_gudang: { ikon: "🏷️", nama: "Cuci gudang & sale" },
    lainnya: { ikon: "💳", nama: "Lainnya" },
  };
  const PLAT_WARNA = { Shopee: "#ee4d2d", Tokopedia: "#03ac0e", Lazada: "#1a1aa6", Blibli: "#0095da",
    "TikTok Shop": "#fe2c55", Bukalapak: "#e31e52", Zalora: "#222", "JD.ID": "#e1251b" };
  const kat = (r) => r.kategori || "makanan";
  const diskonOf = (r) => r.diskon_persen || Number(((r.harga_teks || r.judul || "").match(/(\d{1,2})\s*%/) || [])[1]) || 0;

  async function renderPromo() {
    const el = $("#list-promo");
    $("#h-promo").textContent = `Promo & diskon · ${areaName()}`;
    el.innerHTML = skeleton(6);
    $("#promo-count").textContent = "";
    try {
      S.promos = await data.promo(S.area);
      if (S.me) await ensureOutlets();
      drawPromo();
    } catch (e) { fail(el, e); }
  }

  // ---- "terdekat": nearest outlet of the promo brand (OSM outlets) ----
  const brandRx = (b) => new RegExp(String(b).replace(/[^A-Za-z0-9]+/g, ".*"), "i");
  async function ensureOutlets() {
    const brands = [...new Set(S.promos.filter((r) => kat(r) === "makanan").map((r) => (r.brand || "").trim())
      .filter((b) => b.replace(/[^A-Za-z0-9]/g, "").length >= 3))];
    const key = brands.join("|");
    if (S.outletKey === key) return;
    S.outletKey = key;
    try { S.outlets = await data.outlets(brands); } catch (e) { S.outlets = []; console.error(e); }
  }
  function nearestFor(r) {
    if (!S.me) return null;
    if (r.lat != null) return { d: haversine(S.me.lat, S.me.lon, r.lat, r.lon), nama: r.lokasi || r.brand };
    let best = null;
    if (kat(r) === "makanan" && r.brand && S.outlets.length) {
      const rx = brandRx(r.brand);
      for (const o of S.outlets) {
        if (!rx.test(o.nama)) continue;
        const d = haversine(S.me.lat, S.me.lon, o.lat, o.lon);
        if (!best || d < best.d) best = { d, nama: o.kode_wilayah ? `${o.nama} (${kodeNama(o.kode_wilayah)})` : o.nama };
      }
    }
    if (best) return best;
    const w = (r.kota_berlaku || []).length && S.wilayahs.find((x) => x.kode === r.kota_berlaku[0]);
    return w && w.lat != null ? { d: haversine(S.me.lat, S.me.lon, w.lat, w.lon), nama: `pusat ${w.nama}`, kira: true } : null;
  }
  function mintaLokasi() {
    return new Promise((res) => {
      if (S.me) return res(true);
      if (!navigator.geolocation) { toast("Browser ini tidak mendukung lokasi."); return res(false); }
      toast("📡 Mencari lokasi Anda…");
      navigator.geolocation.getCurrentPosition((p) => { S.me = { lat: p.coords.latitude, lon: p.coords.longitude }; res(true); },
        () => { toast("Izin lokasi ditolak. Urutan terdekat butuh lokasi Anda."); res(false); },
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
    });
  }
  const JENIS = { makanan: "🍔 Makanan", minuman: "🥤 Minuman", campuran: "🍽️ Makanan & minuman" };

  /** filter + sort the cached promos and redraw (no network) */
  function drawPromo() {
    const f = S.pf, all = S.promos;
    // category chips with counts
    const counts = { semua: all.length };
    for (const r of all) counts[kat(r)] = (counts[kat(r)] || 0) + 1;
    $("#f-kat").innerHTML = [["semua", "✨", "Semua"], ...Object.entries(KAT).map(([k, v]) => [k, v.ikon, v.nama])]
      .map(([k, ikon, nama]) => `<button type="button" data-k="${k}" class="fchip ${f.k === k ? "on" : ""}" ${!counts[k] && k !== "semua" ? "disabled" : ""}>
        ${ikon} ${esc(nama)} <span class="n">${counts[k] || 0}</span></button>`).join("");
    // platform chips (marketplace)
    const mp = all.filter((r) => kat(r) === "marketplace");
    const plats = {};
    for (const r of mp) for (const p of (r.platform && r.platform.length ? r.platform : ["Lainnya"])) plats[p] = (plats[p] || 0) + 1;
    const showPlat = (f.k === "semua" || f.k === "marketplace") && Object.keys(plats).length > 0;
    $("#f-plat").hidden = !showPlat;
    if (!plats[f.p] && f.p !== "semua") f.p = "semua";
    $("#f-plat").innerHTML = showPlat ? [["semua", mp.length], ...Object.entries(plats).sort((a, b) => b[1] - a[1])]
      .map(([p, n]) => `<button type="button" data-p="${esc(p)}" class="fchip plat ${f.p === p ? "on" : ""}" style="--pc:${PLAT_WARNA[p] || "var(--accent)"}">
        ${p === "semua" ? "🛒 Semua platform" : esc(p)} <span class="n">${n}</span></button>`).join("") : "";
    // food chips: jenis + halal (only for the Makanan category)
    const food = all.filter((r) => kat(r) === "makanan");
    const cj = { semua: food.length }, ch = { semua: food.length };
    for (const r of food) { cj[r.jenis || "campuran"] = (cj[r.jenis || "campuran"] || 0) + 1; if (r.halal) ch[r.halal] = (ch[r.halal] || 0) + 1; }
    const showFood = f.k === "makanan" && food.length > 0;
    const chip = (t, v, label, n) => `<button type="button" data-${t}="${v}" class="fchip ${f[t] === v ? "on" : ""}" ${!n && v !== "semua" ? "disabled" : ""}>${label} <span class="n">${n || 0}</span></button>`;
    $("#f-food").hidden = !showFood;
    $("#halal-note").hidden = !showFood;
    $("#f-food").innerHTML = showFood
      ? chip("j", "semua", "🍽️ Semua jenis", cj.semua) + chip("j", "makanan", "🍔 Makanan", cj.makanan) + chip("j", "minuman", "🥤 Minuman", cj.minuman)
        + '<span class="sep" aria-hidden="true"></span>'
        + chip("h", "semua", "Semua status", ch.semua) + chip("h", "halal", "✅ Halal", ch.halal) + chip("h", "non_halal", "🚫 Non-halal", ch.non_halal)
      : "";
    if (f.s === "dekat" && !S.me) f.s = "baru";
    $("#f-sort").value = f.s;
    $("#f-pasti").checked = f.pasti;
    $("#f-reset").hidden = f.k === "semua" && f.p === "semua" && f.s === "baru" && !f.q && !f.pasti && f.j === "semua" && f.h === "semua";

    const q = f.q.trim().toLowerCase();
    let rows = all.filter((r) =>
      (f.k === "semua" || kat(r) === f.k) &&
      (f.p === "semua" || (kat(r) === "marketplace" && ((r.platform && r.platform.length ? r.platform : ["Lainnya"]).includes(f.p)))) &&
      (!f.pasti || (r.selesai && !r.selesai_perkiraan)) &&
      (f.k !== "makanan" || f.j === "semua" || (r.jenis || "campuran") === f.j) &&
      (f.k !== "makanan" || f.h === "semua" || r.halal === f.h) &&
      (!q || [r.brand, r.judul, r.menu, r.produk, r.lokasi, ...(r.platform || [])].some((x) => (x || "").toLowerCase().includes(q))));
    const last = (v) => (v == null ? Infinity : v);
    if (f.s === "akhir") rows.sort((a, b) => last(daysLeft(a.selesai)) - last(daysLeft(b.selesai)));
    if (f.s === "diskon") rows.sort((a, b) => diskonOf(b) - diskonOf(a));
    if (f.s === "harga") rows.sort((a, b) => last(a.harga) - last(b.harga));
    const near = new Map(S.me ? rows.map((r) => [r, nearestFor(r)]) : []);
    if (f.s === "dekat") rows.sort((a, b) => last(near.get(a) && near.get(a).d) - last(near.get(b) && near.get(b).d));

    $("#promo-count").textContent = all.length ? `Menampilkan ${rows.length} dari ${all.length} promo` : "";
    const el = $("#list-promo");
    el.innerHTML = rows.map((r, i) => {
      const url = safeUrl(r.url);
      const k = kat(r);
      const harga = r.harga_teks || rupiah(r.harga);
      const title = k === "makanan" ? (r.menu || r.judul) : r.judul;
      const plat = (r.platform || []).map((p) => `<span class="pchip" style="--pc:${PLAT_WARNA[p] || "var(--accent)"}">${esc(p)}</span>`).join("");
      const d = diskonOf(r);
      const where = r.lokasi ? `📍 ${esc(r.lokasi)}${r.kota_berlaku && r.kota_berlaku.length ? `, ${esc(kodeNama(r.kota_berlaku[0]))}` : ""}`
        : k === "marketplace" ? "🌐 Online" : r.kota_berlaku && r.kota_berlaku.length ? esc(r.kota_berlaku.map(kodeNama).join(", ")) : "Semua kota";
      const linkTxt = r.sumber === "YouTube" ? "▶ Tonton videonya di YouTube"
        : k === "makanan" ? `Lihat di ${esc(r.sumber || "sumber")}` : `Baca info lengkap (${esc(r.sumber || "sumber")})`;
      return `<li class="promo k-${k}" style="--i:${i};--h:${hue(r.brand)}">
        ${d ? `<span class="ribbon">-${d}%</span>` : ""}
        <div class="promo-head"><span class="avatar">${esc(initials(r.brand))}</span>
          <div><div class="promo-brand">${esc(r.brand)}</div>
            <span class="kchip">${KAT[k].ikon} ${esc(KAT[k].nama)}</span>${r.sumber_input === "manual" ? ' <span class="chip good">✓ kurasi</span>' : ""}</div></div>
        ${plat ? `<div class="plats">${plat}</div>` : ""}
        <span class="promo-title">${esc(title)}</span>
        ${r.produk && k !== "makanan" && !r.judul.toLowerCase().includes(r.produk.toLowerCase()) ? `<span class="promo-syarat">🎁 ${esc(r.produk)}</span>` : ""}
        ${harga ? `<span class="promo-price">${esc(harga)}</span>` : ""}
        ${r.syarat ? `<span class="promo-syarat">${esc(r.syarat)}</span>` : ""}
        ${k === "makanan" ? `<div class="tags">${r.jenis ? `<span class="chip soft">${JENIS[r.jenis] || ""}</span>` : ""}${
          r.halal === "halal" ? '<span class="chip halal" title="Dari teks promo atau sertifikasi brand yang tercatat">✅ Halal</span>'
          : r.halal === "non_halal" ? '<span class="chip nonhalal">🚫 Non-halal</span>' : ""}</div>` : ""}
        <span class="meta">${sisaChip(r.selesai, r.selesai_perkiraan)}<span>${where}</span></span>
        ${near.get(r) ? `<span class="near">🏪 ${esc(near.get(r).nama)} · ${(near.get(r).d / 1000).toFixed(1).replace(".", ",")} km${near.get(r).kira ? " (perkiraan)" : ""}</span>` : ""}
        ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${linkTxt} <span>→</span></a>` : ""}
      </li>`;
    }).join("") || empty(all.length ? "Tidak ada promo yang cocok dengan filter ini." : `Belum ada promo aktif untuk ${areaName()}.`);
  }

  function setPF(patch) {
    Object.assign(S.pf, patch);
    const { q, ...keep } = S.pf;
    store.set("promoFilter", JSON.stringify(keep));
    drawPromo();
  }

  const sudahLapor = (id) => Date.now() - Number(store.get(`lapor:${id}`) || 0) < 6 * 3600 * 1000;
  const MEDAL = ["🥇", "🥈", "🥉"];

  async function renderViral() {
    const el = $("#list-viral"), elBaru = $("#list-baru");
    $("#h-viral").textContent = `Lagi viral & ramai · ${areaName()}`;
    el.innerHTML = skeleton(4);
    elBaru.innerHTML = skeleton(2);
    try {
      let rows = await data.viral(S.area);
      if (S.me) rows = rows.map((r) => ({ ...r, jarak: r.lat ? haversine(S.me.lat, S.me.lon, r.lat, r.lon) : null }));
      const maxOf = (t) => Math.max(0.001, ...rows.filter((r) => (r.tier || 1) === t).map((r) => r.skor));
      const max = { 1: maxOf(1), 2: maxOf(2) };
      let viralNo = 0;
      el.innerHTML = rows.map((r, i) => {
        const url = safeUrl(r.contoh_url);
        const src = (r.detail && r.detail.sumber) || [];
        const done = sudahLapor(r.entitas_id);
        const tier = r.tier || 1;
        const medal = tier === 1 && viralNo < 3 ? viralNo : -1;
        if (tier === 1) viralNo++;
        const head = tier === 2 && (i === 0 || (rows[i - 1].tier || 1) === 1)
          ? `<li class="tier-head" style="--i:${i}">📈 Lagi dibicarakan <span class="muted">· paling banyak disebut 7 hari terakhir</span></li>` : "";
        const jumlah = tier === 2 ? `${(r.detail && r.detail.mention_7h) || r.mention_24j} sebutan/7 hari` : `${r.mention_24j} sebutan/24 jam`;
        return `${head}<li class="${medal >= 0 ? "top" : ""} ${tier === 2 ? "t2" : ""}" style="--i:${i}">
          <span class="no ${medal >= 0 ? `medal m${medal + 1}` : ""}">${medal >= 0 ? MEDAL[medal] : i + 1}</span>
          <div>
            ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.nama)}</a>` : `<span class="title">${esc(r.nama)}</span>`}
            <div class="meta">${tier === 1 ? '<span class="chip urgent">🔥 Viral</span>' : ""}${r.zona || r.kode_wilayah ? `<span class="chip">📍 ${esc(r.zona || kodeNama(r.kode_wilayah))}</span>` : ""}
              <span>${medal >= 0 ? '<span class="flame">🔥</span> ' : ""}${jumlah}</span>·<span>${r.platform} platform${src.length ? ` (${esc(src.join(", "))})` : ""}</span>
              ${r.jarak != null ? `·<span>${(r.jarak / 1000).toFixed(1)} km</span>` : ""}</div>
            <div class="bar"><span style="width:${Math.max(4, (r.skor / max[tier]) * 100).toFixed(0)}%"></span></div>
          </div>
          <button class="btn ghost ${done ? "done" : ""}" type="button" data-lapor="${r.entitas_id}" data-zona="${r.zona_id ?? ""}" ${done ? "disabled" : ""}>${done ? "✓ Terkirim" : "🔥 Ramai"}</button>
        </li>`;
      }).join("") || empty(`Belum ada tempat yang dibicarakan di ${areaName()} minggu ini. Coba pilih "Semua Jabodetabek".`);
    } catch (e) { fail(el, e); }
    renderGtrends();
    try {
      const baru = await data.baru(S.area);
      elBaru.innerHTML = baru.map((r, i) => `<li style="--i:${i}"><b>${esc(r.nama)}</b>
        <span class="meta">${r.zona ? `<span class="chip good">📍 ${esc(r.zona)}</span>` : ""}<span>tercatat ${timeAgo(r.baru_sejak)}</span>·
        <a href="https://www.openstreetmap.org/?mlat=${Number(r.lat)}&mlon=${Number(r.lon)}#map=18/${Number(r.lat)}/${Number(r.lon)}" target="_blank" rel="noopener noreferrer">lihat peta →</a></span></li>`).join("")
        || empty("Belum ada tempat baru tercatat. Muncul setelah pemindaian OSM harian menemukan tempat yang baru ditambahkan.");
    } catch (e) { fail(elBaru, e); }
  }

  const fmtTraffic = (n) => (n >= 1e6 ? `${Math.round(n / 1e6)}jt+` : n >= 1000 ? `${Math.round(n / 1000)}rb+` : n ? `${n}+` : "");

  async function renderGtrends() {
    const el = $("#list-gtrends");
    el.innerHTML = `<li class="sk trend-sk" aria-hidden="true"><i></i></li>`.repeat(6);
    try {
      const seen = new Set();
      const rows = (await data.gtrends())
        .filter((r) => { const k = r.judul.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; })
        .sort((a, b) => ((b.meta && b.meta.traffic) || 0) - ((a.meta && a.meta.traffic) || 0))
        .slice(0, 20);
      const max = Math.max(1, ...rows.map((r) => (r.meta && r.meta.traffic) || 0));
      el.innerHTML = rows.map((r, i) => {
        const url = safeUrl(r.url);
        const n = (r.meta && r.meta.traffic) || 0;
        const hot = n >= max * 0.5 && n >= 1000;
        return `<li style="--i:${i}"><a class="trend ${hot ? "hot" : ""}" href="${esc(url || `https://www.google.com/search?q=${encodeURIComponent(r.judul)}`)}"
          target="_blank" rel="noopener noreferrer" title="${esc(r.ringkasan || "")}">
          <span class="trend-q">${hot ? "🔥 " : ""}${esc(r.judul)}</span>${n ? `<span class="trend-n">${fmtTraffic(n)}</span>` : ""}</a></li>`;
      }).join("") || `<li class="empty">Belum ada data trending. Diperbarui tiap 15 menit.</li>`;
    } catch (e) { el.innerHTML = `<li class="empty">Gagal memuat trending.</li>`; console.error(e); }
  }

  // ------------------------------------------------------------ map
  function ensureMap() {
    if (S.map || !window.L) return;
    S.map = L.map("map", { scrollWheelZoom: true }).setView([-6.29, 106.82], 10);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(S.map);
    S.layers = L.layerGroup().addTo(S.map);
  }
  const pinIcon = (size, cls = "") => L.divIcon({ className: "", html: `<span class="pin ${cls}"></span>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });

  async function renderMap() {
    ensureMap();
    if (!S.map) return;
    S.map.invalidateSize();
    S.layers.clearLayers();
    const info = getComputedStyle(document.documentElement).getPropertyValue("--info").trim();
    for (const z of S.zonas) {
      L.circle([z.lat, z.lon], { radius: z.radius_m, color: info, weight: 1.5, dashArray: "5 5", fillOpacity: 0.04 })
        .bindTooltip(esc(z.nama)).addTo(S.layers);
    }
    try {
      const [viral, baru, promos] = await Promise.all([data.viral(S.area), data.baru(S.area), data.promo(S.area)]);
      for (const r of promos) {
        if (r.lat == null || kat(r) !== "cuci_gudang") continue;
        const url = safeUrl(r.url);
        L.marker([r.lat, r.lon], { icon: pinIcon(16, "sale"), zIndexOffset: 500 })
          .bindPopup(`<b>🏷️ ${esc(r.judul)}</b><br>${esc(r.lokasi || "")}${r.harga_teks ? `<br>${esc(r.harga_teks)}` : ""}<br>s.d. ${esc(tgl(r.selesai))}${url ? `<br><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">info lengkap →</a>` : ""}`)
          .addTo(S.layers);
      }
      const max = Math.max(0.001, ...viral.map((r) => r.skor));
      for (const r of baru) {
        if (r.lat == null) continue;
        L.marker([r.lat, r.lon], { icon: pinIcon(12, "new") })
          .bindPopup(`<b>${esc(r.nama)}</b><br>🆕 Tempat baru · ${esc(r.zona || "")}`).addTo(S.layers);
      }
      for (const r of viral) {
        if (r.lat == null) continue;
        const url = safeUrl(r.contoh_url);
        L.marker([r.lat, r.lon], { icon: pinIcon(Math.round(14 + 16 * (r.skor / max))), zIndexOffset: 1000 })
          .bindPopup(`<b>${(r.tier || 1) === 1 ? "🔥" : "📈"} ${esc(r.nama)}</b><br>${esc(r.zona || "")}<br>${(r.tier || 1) === 1 ? `${r.mention_24j} sebutan/24 jam` : `${(r.detail && r.detail.mention_7h) || r.mention_24j} sebutan/7 hari`} · skor ${r.skor.toFixed(2)}${url ? `<br><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">contoh konten →</a>` : ""}`)
          .addTo(S.layers);
      }
    } catch (e) { console.error(e); }
    if (S.me) L.marker([S.me.lat, S.me.lon]).bindPopup("Lokasi Anda").addTo(S.layers);
    if (S.area && S.area.lat) S.map.flyTo([S.area.lat, S.area.lon], S.area.type === "zona" ? 14 : 12, { duration: REDUCED ? 0 : 0.8 });
    else S.map.fitBounds([[-6.65, 106.48], [-6.05, 107.18]]);
  }

  // ------------------------------------------------------------ wiring
  function moveIndicator() {
    const b = document.querySelector(`.tabs button[data-tab="${S.tab}"]`), ind = $(".tab-ind");
    if (!b || !ind) return;
    ind.style.setProperty("--x", `${b.offsetLeft}px`);
    ind.style.setProperty("--w", `${b.offsetWidth}px`);
  }

  function render(withStats = false) {
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === S.tab));
    for (const t of ["berita", "promo", "viral", "peta"]) $(`#tab-${t}`).hidden = t !== S.tab;
    moveIndicator();
    saveHash();
    if (withStats) renderStats();
    ({ berita: renderBerita, promo: renderPromo, viral: renderViral, peta: renderMap })[S.tab]();
  }

  function fillSelects() {
    const kota = S.wilayahs.map((w) => `<option value="k:${esc(w.kode)}">${esc(w.nama)}</option>`).join("");
    const zona = S.zonas.map((z) => `<option value="z:${z.id}">${esc(z.nama)}</option>`).join("");
    $("#area").innerHTML = `<option value="all">Semua Jabodetabek</option><optgroup label="Kota / Kabupaten">${kota}</optgroup><optgroup label="Zona populer">${zona}</optgroup>`;
    $("#lapor-zona").innerHTML = `<option value="">Pilih zona…</option>` + zona;
  }

  function nearest(lat, lon) {
    let best = null;
    for (const z of S.zonas) {
      const d = haversine(lat, lon, z.lat, z.lon);
      if (d <= z.radius_m * 1.5 && (!best || d < best.d)) best = { d, v: `z:${z.id}` };
    }
    if (best) return best.v;
    for (const w of S.wilayahs) {
      if (w.lat == null) continue;
      const d = haversine(lat, lon, w.lat, w.lon);
      if (d < 30000 && (!best || d < best.d)) best = { d, v: `k:${w.kode}` };
    }
    return best ? best.v : null;
  }

  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function syncThemeIcon() { $("#theme").textContent = currentTheme() === "dark" ? "☀️" : "🌙"; }

  function bind() {
    $("#area").addEventListener("change", (e) => { S.area = areaFromValue(e.target.value); render(true); });
    for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => { S.tab = b.dataset.tab; render(); });
    window.addEventListener("resize", moveIndicator);
    $("#more-berita").addEventListener("click", () => renderBerita(true));
    $("#f-kat").addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (b) setPF({ k: b.dataset.k, p: "semua" }); });
    $("#f-plat").addEventListener("click", (e) => { const b = e.target.closest("button[data-p]"); if (b) setPF({ p: b.dataset.p }); });
    $("#f-sort").addEventListener("change", async (e) => {
      const s = e.target.value;
      if (s === "dekat") {
        if (!(await mintaLokasi())) { e.target.value = S.pf.s; return; }
        await ensureOutlets();
      }
      setPF({ s });
    });
    $("#f-food").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-j],button[data-h]");
      if (b) setPF(b.dataset.j ? { j: b.dataset.j } : { h: b.dataset.h });
    });
    $("#f-pasti").addEventListener("change", (e) => setPF({ pasti: e.target.checked }));
    $("#f-reset").addEventListener("click", () => { $("#pq").value = ""; setPF({ k: "semua", p: "semua", s: "baru", q: "", pasti: false, j: "semua", h: "semua" }); });
    let tp;
    $("#pq").addEventListener("input", (e) => { clearTimeout(tp); tp = setTimeout(() => setPF({ q: e.target.value }), 200); });
    let t;
    $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value; renderBerita(); }, 300); });

    $("#theme").addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      store.set("theme", next);
      syncThemeIcon();
    });

    const toTop = $("#to-top");
    window.addEventListener("scroll", () => toTop.classList.toggle("show", window.scrollY > 600), { passive: true });
    toTop.addEventListener("click", () => window.scrollTo({ top: 0 }));

    $("#near").addEventListener("click", () => {
      const btn = $("#near");
      if (!navigator.geolocation) { toast("Browser ini tidak mendukung lokasi."); return; }
      btn.disabled = true;
      toast("📡 Mencari lokasi Anda…");
      navigator.geolocation.getCurrentPosition((pos) => {
        S.me = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        const v = nearest(S.me.lat, S.me.lon);
        btn.disabled = false;
        if (!v) { toast("Lokasi Anda di luar Jabodetabek."); return; }
        $("#area").value = v; S.area = areaFromValue(v);
        toast(`📍 Menampilkan area ${S.area.nama}`);
        if (S.tab === "berita" || S.tab === "promo") S.tab = "viral";
        render(true);
      }, () => { btn.disabled = false; toast("Izin lokasi ditolak atau tidak tersedia."); },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
    });

    $("#list-viral").addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-lapor]");
      if (!b) return;
      b.disabled = true;
      try {
        await data.lapor({ entitas_id: Number(b.dataset.lapor), zona_id: b.dataset.zona ? Number(b.dataset.zona) : null, jenis: "ramai" });
        store.set(`lapor:${b.dataset.lapor}`, String(Date.now()));
        b.textContent = "✓ Terkirim"; b.classList.add("done");
        toast("🔥 Terima kasih! Laporan masuk ke skor jam berikutnya.");
      } catch (err) { b.disabled = false; toast("Gagal mengirim laporan."); console.error(err); }
    });

    $("#lapor").addEventListener("submit", async (e) => {
      e.preventDefault();
      const zona = Number($("#lapor-zona").value), nama = $("#lapor-nama").value.trim();
      if (!zona || !nama) return;
      try {
        await data.lapor({ zona_id: zona, nama_tempat: nama.slice(0, 120), jenis: "ramai" });
        toast(DEMO ? "Mode demo: laporan tidak disimpan." : "🙌 Terima kasih! Laporan masuk ke perhitungan skor.");
        $("#lapor-nama").value = "";
      } catch (err) { toast("Gagal mengirim laporan."); console.error(err); }
    });
  }

  async function init() {
    $("#demo").hidden = !DEMO;
    syncThemeIcon();
    document.querySelectorAll(".stat").forEach((s, i) => s.style.setProperty("--i", i));
    if (C.TELEGRAM_BOT) $("#bot-link").innerHTML = `Bot Telegram: <a href="https://t.me/${encodeURIComponent(C.TELEGRAM_BOT)}" target="_blank" rel="noopener noreferrer">@${esc(C.TELEGRAM_BOT)}</a>`;
    try {
      const a = await data.areas();
      S.zonas = a.zonas; S.wilayahs = a.wilayahs;
    } catch (e) { console.error(e); }
    fillSelects();
    bind();
    const [tab, area] = location.hash.slice(1).split("/");
    if (["berita", "promo", "viral", "peta"].includes(tab)) S.tab = tab;
    S.area = areaFromValue(area);
    $("#area").value = areaValue(S.area);
    render(true);
    // fonts change tab widths once loaded
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveIndicator);
    // refresh the live counters every 5 minutes
    setInterval(renderStats, 5 * 60 * 1000);
  }

  init();
})();
