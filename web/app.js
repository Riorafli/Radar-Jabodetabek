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
    if (REDUCED || from === to) { el.textContent = to.toLocaleString("id-ID"); return; }
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
      return rest(`v_promo?select=id,brand,judul,menu,harga,harga_teks,selesai,syarat,url,sumber,kota_berlaku,sumber_input&order=published_at.desc&limit=60${areaQS(area, "promo")}`);
    },
    async viral(area) {
      if (DEMO) return D().viral.filter((r) => areaMatch(r, area)).sort((a, b) => (a.tier || 1) - (b.tier || 1) || b.skor - a.skor).slice(0, 30);
      return rest(`v_viral?select=entitas_id,nama,zona_id,zona,kode_wilayah,skor,tier,mention_24j,platform,detail,lat,lon,contoh_url&order=tier.asc,skor.desc&limit=30${areaQS(area)}`);
    },
    async baru(area) {
      if (DEMO) return D().baru.filter((r) => areaMatch(r, area));
      return rest(`v_tempat_baru?select=id,nama,lat,lon,zona_id,zona,kode_wilayah,baru_sejak&order=baru_sejak.desc&limit=30${areaQS(area)}`);
    },
    async lapor(body) {
      if (DEMO) return;
      await rest("laporan", { method: "POST", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ ...body, sumber: "web" }) });
    },
  };

  // ------------------------------------------------------------ state
  const S = { tab: "berita", area: null, zonas: [], wilayahs: [], offset: 0, q: "", map: null, layers: null, me: null };

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

  function sisaChip(selesai) {
    const d = daysLeft(selesai);
    if (d == null) return `<span class="chip good">Periode tidak disebut</span>`;
    if (d <= 0) return `<span class="chip urgent">⏰ Berakhir hari ini</span>`;
    if (d <= 3) return `<span class="chip urgent">⏰ ${d} hari lagi</span>`;
    return `<span class="chip">s.d. ${esc(tgl(selesai))}</span>`;
  }

  async function renderPromo() {
    const el = $("#list-promo");
    $("#h-promo").textContent = `Promo makanan · ${areaName()}`;
    el.innerHTML = skeleton(6);
    try {
      const rows = await data.promo(S.area);
      el.innerHTML = rows.map((r, i) => {
        const url = safeUrl(r.url);
        const harga = r.harga_teks || rupiah(r.harga);
        const title = r.menu || r.judul;
        return `<li class="promo" style="--i:${i};--h:${hue(r.brand)}">
          <div class="promo-head"><span class="avatar">${esc(initials(r.brand))}</span>
            <div><div class="promo-brand">${esc(r.brand)}</div>${r.sumber_input === "manual" ? '<span class="chip good">✓ kurasi</span>' : ""}</div></div>
          <span class="promo-title">${esc(title)}</span>
          ${harga ? `<span class="promo-price">${esc(harga)}</span>` : ""}
          ${r.syarat ? `<span class="promo-syarat">${esc(r.syarat)}</span>` : ""}
          <span class="meta">${sisaChip(r.selesai)}<span>${r.kota_berlaku && r.kota_berlaku.length ? esc(r.kota_berlaku.map(kodeNama).join(", ")) : "Semua kota"}</span></span>
          ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Lihat di ${esc(r.sumber || "sumber")} <span>→</span></a>` : ""}
        </li>`;
      }).join("") || empty(`Belum ada promo aktif untuk ${areaName()}.`);
    } catch (e) { fail(el, e); }
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
    try {
      const baru = await data.baru(S.area);
      elBaru.innerHTML = baru.map((r, i) => `<li style="--i:${i}"><b>${esc(r.nama)}</b>
        <span class="meta">${r.zona ? `<span class="chip good">📍 ${esc(r.zona)}</span>` : ""}<span>tercatat ${timeAgo(r.baru_sejak)}</span>·
        <a href="https://www.openstreetmap.org/?mlat=${Number(r.lat)}&mlon=${Number(r.lon)}#map=18/${Number(r.lat)}/${Number(r.lon)}" target="_blank" rel="noopener noreferrer">lihat peta →</a></span></li>`).join("")
        || empty("Belum ada tempat baru tercatat. Muncul setelah pemindaian OSM harian menemukan tempat yang baru ditambahkan.");
    } catch (e) { fail(elBaru, e); }
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
      const [viral, baru] = await Promise.all([data.viral(S.area), data.baru(S.area)]);
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
