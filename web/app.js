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
  /** brand initials for the promo mark */
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

  // figures are set, not counted up (the theme keeps still)
  function countUp(el, to) {
    el.dataset.v = to;
    el.textContent = to.toLocaleString("id-ID");
  }

  const skeleton = (n) => Array.from({ length: n }, () => `<li class="sk" aria-hidden="true"><i></i><i></i><i></i></li>`).join("");

  // ------------------------------------------------------------ source types (Berita + China)
  const JENIS_SUMBER = {
    resmi: ["Resmi pemerintah", "Instansi resmi pemerintah (mis. BMKG): data dan peringatan resmi"],
    negara: ["Media negara", "Media milik negara/BUMN (Indonesia: Antara; China: CGTN, Sixth Tone): cenderung membawa sudut pandang resmi pemerintah"],
    swasta: ["Media swasta", "Media swasta nasional"],
    lokal: ["Media lokal", "Media lokal daerah: liputan dekat, jangkauan terbatas"],
    agregator: ["Agregator/cepat", "Portal cepat yang sering menulis ulang media lain atau memuat bocoran: cek sumber aslinya"],
    lainnya: ["Lainnya", "Sumber lain (mis. hasil pencarian GDELT): cek kredibilitas medianya"],
  };
  // key points (pipeline/inti.py), one per line, plus a link to the full article
  const intiHTML = (inti, url, sumber) => `<ul class="inti" aria-label="Inti berita">${inti.split("\n").map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
    ${url ? `<a class="baca" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Baca selengkapnya di ${esc(sumber)}</a>` : ""}`;
  // ------------------------------------------------------------ verification (pipeline/cekfakta.py)
  const PERS = { faktual: "Terverifikasi faktual Dewan Pers", administratif: "Terverifikasi administratif Dewan Pers", resmi: "Sumber resmi pemerintah" };
  const verifHTML = (p) => (PERS[p] ? `<span class="verif" title="${PERS[p]}">terverifikasi</span>` : "");
  const hoaksHTML = (r) => {
    const u = safeUrl(r.hoaks_url);
    return `<p class="hoaks-warn"><b>Cek fakta.</b> Mirip klaim yang dinyatakan <b>${esc(r.hoaks_label || "SALAH")}</b> oleh ${esc(r.hoaks_sumber || "lembaga cek fakta")}:
      ${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(r.hoaks_judul)}</a>` : esc(r.hoaks_judul)}</p>`;
  };
  async function renderHoaks() {
    const el = $("#list-hoaks");
    try {
      const seen = new Set();   // the same claim is often in both feeds
      const rows = (await data.hoaks()).filter((r) => !seen.has(r.judul.toLowerCase()) && seen.add(r.judul.toLowerCase())).slice(0, 6);
      el.innerHTML = rows.map((r) => {
        const u = safeUrl(r.url);
        return `<li><span class="chip warn mini">${esc(r.label)}</span> ${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(r.judul)}</a>` : esc(r.judul)}
          <span class="muted">${esc(r.sumber)}</span></li>`;
      }).join("") || `<li class="muted">Belum ada data cek fakta.</li>`;
      $("#hoaks-box").hidden = !rows.length && !DEMO;
    } catch (e) { console.error(e); }
  }
  // the publisher's own photo (pipeline/gambar.py), loaded from their site and linked to the article
  const fotoHTML = (src, url) => (safeUrl(src) ? `<a class="foto" href="${esc(url || src)}" target="_blank" rel="noopener noreferrer" tabindex="-1" aria-hidden="true">
    <img src="${esc(safeUrl(src))}" alt="" loading="lazy" decoding="async" width="640" height="360"></a>` : "");
  const badgeSumber = (j) => (JENIS_SUMBER[j] ? `<span class="src-badge ${esc(j)}" title="${esc(JENIS_SUMBER[j][1])}">${JENIS_SUMBER[j][0]}</span>` : "");

  // ------------------------------------------------------------ berita filters
  const TOPIK = {
    lalu_lintas: "Lalu lintas", cuaca_bencana: "Cuaca & bencana", peristiwa: "Peristiwa", kriminal: "Kriminal & hukum",
    pemerintahan: "Pemerintahan", ekonomi: "Ekonomi & kerja", kesehatan: "Kesehatan", pendidikan: "Pendidikan",
    gaya_hidup: "Gaya hidup", olahraga: "Olahraga", umum: "Umum",
  };
  // WIB calendar helpers (dates as "YYYY-MM-DD")
  const WIB_MS = 7 * 3600e3;
  const tglWIB = (ms = Date.now()) => new Date(ms + WIB_MS).toISOString().slice(0, 10);
  const awalTglWIB = (tgl) => new Date(Date.parse(`${tgl}T00:00:00Z`) - WIB_MS);   // midnight WIB as an instant
  /** time filter value -> { since, until } ISO strings (either may be null).
   *  "6j" = 6 hours, "hari" = today, "<N>h" = last N days (1-30), "tgl:YYYY-MM-DD" = that day */
  function beritaRange(w, maks = 30) {
    const now = Date.now();
    if (w === "6j") return { since: new Date(now - 6 * 3600e3).toISOString(), until: null };
    if (w === "hari") return { since: awalTglWIB(tglWIB(now)).toISOString(), until: null };
    const n = /^(?:atur:)?(\d{1,2})h?$/.exec(w || "");
    if (n) return { since: new Date(now - Math.min(maks, Math.max(1, +n[1])) * 86400e3).toISOString(), until: null };
    if ((w || "").startsWith("tgl:")) {
      const a = awalTglWIB(w.slice(4));
      return { since: a.toISOString(), until: new Date(a.getTime() + 86400e3).toISOString() };
    }
    return { since: null, until: null };
  }
  const terbitQS = (r) => (r.since ? `&terbit=gte.${encodeURIComponent(r.since)}` : "") + (r.until ? `&terbit=lt.${encodeURIComponent(r.until)}` : "");
  const dalamRange = (iso, r) => (!r.since || iso >= r.since) && (!r.until || iso < r.until);
  function labelWaktu(w) {
    if (w === "hari") return "Hari ini";
    if (w === "6j") return "6 jam terakhir";
    if ((w || "").startsWith("tgl:")) return new Date(`${w.slice(4)}T00:00:00`).toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long" });
    const n = /^(?:atur:)?(\d{1,2})h?$/.exec(w || "");
    return n ? `${n[1]} hari terakhir` : "";
  }
  // for heads: "Berita hari ini di Bekasi"
  const judulWaktu = (w) => (w === "hari" ? "hari ini" : labelWaktu(w));
  const cocokTopik = (r, t) => !t || t === "semua" || (t === "info" ? r.tipe === "info" : (r.topik || ["umum"]).includes(t));
  function beritaQS(bf, r = {}) {
    let qs = "";
    if (bf.t === "info") qs += "&tipe=eq.info";
    else if (bf.t && bf.t !== "semua") qs += `&topik=cs.${encodeURIComponent(`{"${bf.t}"}`)}`;
    if (bf.s) qs += `&sumber=eq.${encodeURIComponent(bf.s)}`;
    if (bf.j) qs += `&jenis_sumber=eq.${encodeURIComponent(bf.j)}`;
    if (bf.v) qs += "&pers=not.is.null";
    if (r.since) qs += `&published_at=gte.${encodeURIComponent(r.since)}`;
    if (r.until) qs += `&published_at=lt.${encodeURIComponent(r.until)}`;
    return qs;
  }

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
        count(`item?select=id&tipe=eq.post&sumber=eq.YouTube${areaQS(area)}`),
        count(`entitas?select=id&tipe=eq.tempat${areaQS(area)}`),
        rest("item?select=dibuat&order=dibuat.desc&limit=1"),
      ]);
      return { berita, promo, video, tempat, updated: last && last[0] && last[0].dibuat };
    },
    async berita(area, q, offset, bf = {}) {
      const clean = (q || "").replace(/[,()*%]/g, " ").trim();
      const rng = beritaRange(bf.w);
      if (DEMO) {
        return D().berita.filter((r) => areaMatch(r, area) && (!clean || r.judul.toLowerCase().includes(clean.toLowerCase()))
          && cocokTopik(r, bf.t) && (!bf.s || r.sumber === bf.s) && (!bf.j || r.jenis_sumber === bf.j) && (!bf.v || r.pers)
          && dalamRange(r.published_at, rng)).slice(offset, offset + PAGE);
      }
      const qs = (clean ? `&judul=ilike.${encodeURIComponent(`*${clean}*`)}` : "") + beritaQS(bf, rng);
      return rest(`v_berita?select=id,tipe,judul,url,sumber,ringkasan,inti,gambar,published_at,wilayah,zona,topik,jenis_sumber,pers,hoaks_judul,hoaks_label,hoaks_url,hoaks_sumber&order=published_at.desc&limit=${PAGE}&offset=${offset}${areaQS(area)}${qs}`);
    },
    async beritaMeta(area, rng = {}) {
      if (DEMO) return D().berita.filter((r) => areaMatch(r, area) && dalamRange(r.published_at, rng));
      return rest(`v_berita?select=tipe,topik,sumber,jenis_sumber&order=published_at.desc&limit=5000${areaQS(area)}${beritaQS({ v: S.bf.v }, rng)}`);
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
    async videos(area) {
      if (DEMO) return [];
      const since = new Date(Date.now() - 7 * 86400e3).toISOString();
      return rest(`item?select=judul,url,meta,published_at,zona_id,kode_wilayah&tipe=eq.post&sumber=eq.YouTube&published_at=gt.${encodeURIComponent(since)}&order=published_at.desc&limit=400${areaQS(area)}`);
    },
    async hoaks() {
      if (DEMO) return [];
      return rest("hoaks?select=judul,label,url,sumber&order=terbit.desc,id.asc&limit=16");
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
    async china(kategori, sumber, q, offset, jenis, rng = {}) {
      if (DEMO) return [];
      const clean = (q || "").replace(/[,()*%]/g, " ").trim();
      const qs = (kategori && kategori !== "semua" ? `&kategori=eq.${kategori}` : "")
        + (sumber ? `&sumber=eq.${encodeURIComponent(sumber)}` : "")
        + (jenis ? `&jenis_sumber=eq.${encodeURIComponent(jenis)}` : "")
        + terbitQS(rng)
        + (clean ? `&or=(judul_id.ilike.${encodeURIComponent(`*${clean}*`)},ringkasan_id.ilike.${encodeURIComponent(`*${clean}*`)},judul_asli.ilike.${encodeURIComponent(`*${clean}*`)})` : "");
      return rest(`berita_china?select=id,url,sumber,bahasa,judul_asli,judul_id,ringkasan_id,inti,gambar,kategori,jenis_sumber,terbit&judul_id=not.is.null&order=terbit.desc&limit=${PAGE}&offset=${offset}${qs}`);
    },
    async chinaMeta(rng = {}) {
      if (DEMO) return [];
      return rest(`berita_china?select=kategori,sumber,jenis_sumber&judul_id=not.is.null&limit=2000${terbitQS(rng)}`);
    },
    async saham() {
      if (DEMO) return [];
      return rest("saham?select=*&order=kode");
    },
    async sahamRiwayat() {
      if (DEMO) return [];
      const since = new Date(Date.now() - 75 * 86400000).toISOString().slice(0, 10);
      return rest(`saham_harian?select=kode,tanggal,close&tanggal=gte.${since}&order=tanggal&limit=10000`);
    },
    async pasarBerita(jenis, offset, kode) {
      if (DEMO) return [];
      return rest(`saham_berita?select=judul,url,sumber,terbit,kode,jenis,gambar&order=terbit.desc&limit=${PAGE}&offset=${offset}${jenis ? `&jenis=eq.${jenis}` : ""}${kodeQS(kode)}`);
    },
    async pasarHitung(kode) {
      if (DEMO) return { semua: 0, saham: 0, kripto: 0 };
      const [semua, saham, kripto] = await Promise.all(["", "&jenis=eq.saham", "&jenis=eq.kripto"].map((q) => count(`saham_berita?select=id${q}${kodeQS(kode)}`)));
      return { semua, saham, kripto };
    },
    // codes named in market news over the last 7 days (the "paling banyak diberitakan" box)
    async pasarTop() {
      if (DEMO) return [];
      return rest(`saham_berita?select=kode,jenis&terbit=gte.${new Date(Date.now() - 7 * 86400e3).toISOString()}&limit=3000`);
    },
    async sahamBerita(kode) {
      if (DEMO) return [];
      return rest(`saham_berita?select=judul,url,sumber,terbit&kode=cs.${encodeURIComponent(`{"${kode}"}`)}&order=terbit.desc&limit=6`);
    },
    async lapor(body) {
      if (DEMO) return;
      await rest("laporan", { method: "POST", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ ...body, sumber: "web" }) });
    },
  };

  // ------------------------------------------------------------ state
  const S = { tab: "berita", area: null, zonas: [], wilayahs: [], offset: 0, q: "", map: null, layers: null, me: null,
    bf: { t: "semua", w: "semua", s: "", j: "", v: false },
    promos: [], outlets: [], outletKey: null,
    sh: { rows: [], hist: {}, sektor: "semua", sort: "kode", q: "", loaded: false, pasar: "", pasarOff: 0, kode: "" },
    cn: { kat: "semua", sumber: "", q: "", asli: false, offset: 0, jenis: "", w: "semua" },
    pf: { k: "semua", p: "semua", s: "baru", q: "", pasti: false, j: "semua", h: "semua" } };
  try { Object.assign(S.pf, JSON.parse(store.get("promoFilter") || "{}"), { q: "" }); } catch { /* ignore */ }
  try { Object.assign(S.bf, JSON.parse(store.get("beritaFilter") || "{}")); } catch { /* ignore */ }
  if (String(S.bf.w).startsWith("atur:")) S.bf.w = "semua";       // saved value from the removed day slider

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
      $("#updated").textContent = s.updated ? `Diperbarui ${timeAgo(s.updated)}` : "";
    } catch (e) { console.error(e); }
  }

  async function drawBeritaFilters() {
    const bf = S.bf, rng = beritaRange(bf.w);
    // the select shows presets; other values come from the slider or the date picker
    const w = bf.w || "semua", mode = w.startsWith("tgl:") ? "tgl" : w;
    $("#b-waktu").value = mode;
    $("#b-tgl-wrap").hidden = mode !== "tgl";
    if (mode === "tgl") $("#b-tgl").value = w.slice(4);
    $("#b-reset").hidden = bf.t === "semua" && bf.w === "semua" && !bf.s && !bf.j && !bf.v;
    $("#b-verif").checked = !!bf.v;
    try {
      const keys = ["semua", "info", ...Object.keys(TOPIK)];
      const ct = {}, cs = {};
      const meta = await data.beritaMeta(S.area, rng);         // recent rows: source list only (API caps rows)
      for (const m of meta) if (cocokTopik(m, bf.t) && (!bf.j || m.jenis_sumber === bf.j)) cs[m.sumber] = 1;
      const jenisKeys = ["", ...Object.keys(JENIS_SUMBER).filter((j) => j !== "agregator")];
      const cj = {};
      if (DEMO) {
        for (const k of keys) ct[k] = meta.filter((m) => cocokTopik(m, k) && (!bf.s || m.sumber === bf.s) && (!bf.j || m.jenis_sumber === bf.j)).length;
        for (const j of jenisKeys) cj[j] = meta.filter((m) => cocokTopik(m, bf.t) && (!j || m.jenis_sumber === j)).length;
      } else {                                                  // exact counts, respecting the other filters
        const [n, nj] = await Promise.all([
          Promise.all(keys.map((k) => count(`v_berita?select=id${areaQS(S.area)}${beritaQS({ t: k, s: bf.s, j: bf.j, v: bf.v }, rng)}`))),
          Promise.all(jenisKeys.map((j) => count(`v_berita?select=id${areaQS(S.area)}${beritaQS({ t: bf.t, s: bf.s, j, v: bf.v }, rng)}`))),
        ]);
        keys.forEach((k, i) => { ct[k] = n[i]; });
        jenisKeys.forEach((j, i) => { cj[j] = nj[i]; });
      }
      $("#f-jenis").innerHTML = jenisKeys.map((j) => `<button type="button" data-j="${j}" class="fchip ${bf.j === j ? "on" : ""}" ${!cj[j] && j && bf.j !== j ? "disabled" : ""}>
        ${j ? JENIS_SUMBER[j][0] : "Semua jenis sumber"} <span class="n">${cj[j] || 0}</span></button>`).join("");
      const opsi = [["semua", "Semua"], ["info", "Info layanan"], ...Object.entries(TOPIK)];
      $("#f-topik").innerHTML = opsi.map(([k, label]) => `<button type="button" data-t="${k}" class="fchip ${bf.t === k ? "on" : ""}" ${!ct[k] && k !== "semua" && bf.t !== k ? "disabled" : ""}>${label} <span class="n">${ct[k] || 0}</span></button>`).join("");
      $("#b-sumber").innerHTML = `<option value="">Semua sumber</option>` + Object.keys(cs).sort()
        .map((s) => `<option value="${esc(s)}" ${bf.s === s ? "selected" : ""}>${esc(s)}</option>`).join("")
        + (bf.s && !cs[bf.s] ? `<option value="${esc(bf.s)}" selected>${esc(bf.s)}</option>` : "");
    } catch (e) { console.error(e); }
  }

  function setBF(patch) {
    Object.assign(S.bf, patch);
    store.set("beritaFilter", JSON.stringify(S.bf));
    renderBerita();
  }

  async function renderBerita(append = false) {
    const el = $("#list-berita");
    $("#h-berita").textContent = `Berita ${judulWaktu(S.bf.w) || "terkini"} di ${areaName()}`;
    if (!append) { S.offset = 0; el.innerHTML = skeleton(5); drawBeritaFilters(); }
    try {
      const rows = await data.berita(S.area, S.q, S.offset, S.bf);
      const html = rows.map((r, i) => {
        const url = safeUrl(r.url);
        const where = r.zona || r.wilayah;
        return `<li class="${r.tipe === "info" ? "info" : ""} ${r.gambar ? "ada-foto" : ""}" style="--i:${i}">
          ${fotoHTML(r.gambar, url)}<div class="teks">
          ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.judul)}</a>` : `<span class="title">${esc(r.judul)}</span>`}
          ${r.hoaks_judul ? hoaksHTML(r) : ""}
          ${r.inti ? intiHTML(r.inti, url, r.sumber) : r.ringkasan ? `<p class="sum">${esc(r.ringkasan)}</p>` : ""}
          <div class="meta">${r.tipe === "info" ? '<span class="chip info">Info layanan</span>' : ""}
            ${where ? `<span class="chip place">${esc(where)}</span>` : ""}
            ${(r.topik || []).filter((t) => t !== "umum" && TOPIK[t]).map((t) => `<span class="chip soft">${TOPIK[t]}</span>`).join("")}
            ${badgeSumber(r.jenis_sumber)}
            ${r.pers ? "" : `<span class="chip warn" title="Media ini belum tercatat terverifikasi di Dewan Pers: cek juga di media lain">Belum terverifikasi</span>`}
            <span class="by">${esc(r.sumber)}</span>${verifHTML(r.pers)}<time>${timeAgo(r.published_at)}</time></div>
        </div></li>`;
      }).join("");
      if (append) el.insertAdjacentHTML("beforeend", html);
      else el.innerHTML = html || empty(S.bf.t !== "semua" || S.bf.w !== "semua" || S.bf.s || S.bf.j || S.bf.v
        ? "Tidak ada berita yang cocok dengan filter ini." : `Belum ada berita untuk ${areaName()}.`);
      S.offset += rows.length;
      $("#more-berita").hidden = rows.length < PAGE;
    } catch (e) { fail(el, e); }
  }

  const kodeNama = (k) => (S.wilayahs.find((w) => w.kode === k) || {}).nama || k;

  function sisaChip(selesai, perkiraan) {
    const d = daysLeft(selesai);
    if (d == null) return `<span class="chip good">Periode tidak disebut</span>`;
    if (perkiraan) return `<span class="chip soft" title="Sumber tidak menyebut tanggal berakhir">± s.d. ${esc(tgl(selesai))}</span>`;
    if (d <= 0) return `<span class="chip urgent">Berakhir hari ini</span>`;
    if (d <= 3) return `<span class="chip urgent">${d} hari lagi</span>`;
    return `<span class="chip">s.d. ${esc(tgl(selesai))}</span>`;
  }

  const KAT = {
    makanan: { nama: "Makanan" },
    marketplace: { nama: "Marketplace" },
    cuci_gudang: { nama: "Cuci gudang & sale" },
    lainnya: { nama: "Lainnya" },
  };
  const kat = (r) => r.kategori || "makanan";
  const diskonOf = (r) => r.diskon_persen || Number(((r.harga_teks || r.judul || "").match(/(\d{1,2})\s*%/) || [])[1]) || 0;

  async function renderPromo() {
    const el = $("#list-promo");
    $("#h-promo").textContent = `Promo & diskon di ${areaName()}`;
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
      toast("Mencari lokasi Anda…");
      navigator.geolocation.getCurrentPosition((p) => { S.me = { lat: p.coords.latitude, lon: p.coords.longitude }; res(true); },
        () => { toast("Izin lokasi ditolak. Urutan terdekat butuh lokasi Anda."); res(false); },
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
    });
  }
  const JENIS = { makanan: "Makanan", minuman: "Minuman", campuran: "Makanan & minuman" };

  /** filter + sort the cached promos and redraw (no network) */
  function drawPromo() {
    const f = S.pf, all = S.promos;
    // category chips with counts
    const counts = { semua: all.length };
    for (const r of all) counts[kat(r)] = (counts[kat(r)] || 0) + 1;
    $("#f-kat").innerHTML = [["semua", "Semua"], ...Object.entries(KAT).map(([k, v]) => [k, v.nama])]
      .map(([k, nama]) => `<button type="button" data-k="${k}" class="fchip ${f.k === k ? "on" : ""}" ${!counts[k] && k !== "semua" ? "disabled" : ""}>
        ${esc(nama)} <span class="n">${counts[k] || 0}</span></button>`).join("");
    // platform chips (marketplace)
    const mp = all.filter((r) => kat(r) === "marketplace");
    const plats = {};
    for (const r of mp) for (const p of (r.platform && r.platform.length ? r.platform : ["Lainnya"])) plats[p] = (plats[p] || 0) + 1;
    const showPlat = (f.k === "semua" || f.k === "marketplace") && Object.keys(plats).length > 0;
    $("#f-plat").hidden = !showPlat;
    if (!plats[f.p] && f.p !== "semua") f.p = "semua";
    $("#f-plat").innerHTML = showPlat ? [["semua", mp.length], ...Object.entries(plats).sort((a, b) => b[1] - a[1])]
      .map(([p, n]) => `<button type="button" data-p="${esc(p)}" class="fchip plat ${f.p === p ? "on" : ""}">
        ${p === "semua" ? "Semua platform" : esc(p)} <span class="n">${n}</span></button>`).join("") : "";
    // food chips: jenis + halal (only for the Makanan category)
    const food = all.filter((r) => kat(r) === "makanan");
    const cj = { semua: food.length }, ch = { semua: food.length };
    for (const r of food) { cj[r.jenis || "campuran"] = (cj[r.jenis || "campuran"] || 0) + 1; if (r.halal) ch[r.halal] = (ch[r.halal] || 0) + 1; }
    const showFood = f.k === "makanan" && food.length > 0;
    const chip = (t, v, label, n) => `<button type="button" data-${t}="${v}" class="fchip ${f[t] === v ? "on" : ""}" ${!n && v !== "semua" ? "disabled" : ""}>${label} <span class="n">${n || 0}</span></button>`;
    $("#f-food").hidden = !showFood;
    $("#halal-note").hidden = !showFood;
    $("#f-food").innerHTML = showFood
      ? chip("j", "semua", "Semua jenis", cj.semua) + chip("j", "makanan", "Makanan", cj.makanan) + chip("j", "minuman", "Minuman", cj.minuman)
        + '<span class="sep" aria-hidden="true"></span>'
        + chip("h", "semua", "Semua status", ch.semua) + chip("h", "halal", "Halal", ch.halal) + chip("h", "non_halal", "Non-halal", ch.non_halal)
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
      const plat = (r.platform || []).map((p) => `<span class="pchip">${esc(p)}</span>`).join("");
      const d = diskonOf(r);
      const where = r.lokasi ? `${esc(r.lokasi)}${r.kota_berlaku && r.kota_berlaku.length ? `, ${esc(kodeNama(r.kota_berlaku[0]))}` : ""}`
        : k === "marketplace" ? "Online" : r.kota_berlaku && r.kota_berlaku.length ? esc(r.kota_berlaku.map(kodeNama).join(", ")) : "Semua kota";
      const linkTxt = r.sumber === "YouTube" ? "Tonton videonya di YouTube"
        : k === "makanan" ? `Lihat di ${esc(r.sumber || "sumber")}` : `Baca info lengkap (${esc(r.sumber || "sumber")})`;
      return `<li class="promo k-${k}" style="--i:${i}">
        ${d ? `<span class="ribbon">-${d}%</span>` : ""}
        <div class="promo-head"><span class="avatar">${esc(initials(r.brand))}</span>
          <div><div class="promo-brand">${esc(r.brand)}</div>
            <span class="kchip">${esc(KAT[k].nama)}</span>${r.sumber_input === "manual" ? ' <span class="chip good">kurasi</span>' : ""}</div></div>
        ${plat ? `<div class="plats">${plat}</div>` : ""}
        <span class="promo-title">${esc(title)}</span>
        ${r.produk && k !== "makanan" && !r.judul.toLowerCase().includes(r.produk.toLowerCase()) ? `<span class="promo-syarat">${esc(r.produk)}</span>` : ""}
        ${harga ? `<span class="promo-price">${esc(harga)}</span>` : ""}
        ${r.syarat ? `<span class="promo-syarat">${esc(r.syarat)}</span>` : ""}
        ${k === "makanan" ? `<div class="tags">${r.jenis ? `<span class="chip soft">${JENIS[r.jenis] || ""}</span>` : ""}${
          r.halal === "halal" ? '<span class="chip halal" title="Dari teks promo atau sertifikasi brand yang tercatat">Halal</span>'
          : r.halal === "non_halal" ? '<span class="chip nonhalal">Non-halal</span>' : ""}</div>` : ""}
        <span class="meta">${sisaChip(r.selesai, r.selesai_perkiraan)}<span>${where}</span></span>
        ${near.get(r) ? `<span class="near">${esc(near.get(r).nama)}, <span class="num">${(near.get(r).d / 1000).toFixed(1).replace(".", ",")} km</span>${near.get(r).kira ? " (perkiraan)" : ""}</span>` : ""}
        ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${linkTxt}</a>` : ""}
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
  
  async function renderViral() {
    const el = $("#list-viral"), elBaru = $("#list-baru");
    $("#h-viral").textContent = `Lagi ramai di ${areaName()}`;
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
          ? `<li class="tier-head" style="--i:${i}">Lagi dibicarakan <span class="muted">paling banyak disebut 7 hari terakhir</span></li>` : "";
        const jumlah = tier === 2 ? `${(r.detail && r.detail.mention_7h) || r.mention_24j} sebutan/7 hari` : `${r.mention_24j} sebutan/24 jam`;
        return `${head}<li class="${medal >= 0 ? "top" : ""} ${tier === 2 ? "t2" : ""}" style="--i:${i}">
          <span class="no num ${medal >= 0 ? "medal" : ""}">${i + 1 - (tier === 2 ? rows.filter((x) => (x.tier || 1) === 1).length : 0)}</span>
          <div>
            ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.nama)}</a>` : `<span class="title">${esc(r.nama)}</span>`}
            <div class="meta">${tier === 1 ? '<span class="chip urgent">Viral</span>' : ""}${r.zona || r.kode_wilayah ? `<span class="chip place">${esc(r.zona || kodeNama(r.kode_wilayah))}</span>` : ""}
              <span>${jumlah}</span><span>${r.platform} platform${src.length ? ` (${esc(src.join(", "))})` : ""}</span>
              ${r.jarak != null ? `<span>${(r.jarak / 1000).toFixed(1)} km</span>` : ""}</div>
            <div class="bar"><span style="--p:${Math.max(0.04, r.skor / max[tier]).toFixed(3)}"></span></div>
          </div>
          <button class="btn ghost ${done ? "done" : ""}" type="button" data-lapor="${r.entitas_id}" data-zona="${r.zona_id ?? ""}" ${done ? "disabled" : ""}>${done ? "Terkirim" : "Ramai di sini"}</button>
        </li>`;
      }).join("") || empty(`Belum ada tempat yang dibicarakan di ${areaName()} minggu ini. Coba pilih "Semua Jabodetabek".`);
    } catch (e) { fail(el, e); }
    renderGtrends();
    renderVideos();
    try {
      const baru = await data.baru(S.area);
      elBaru.innerHTML = baru.map((r, i) => `<li style="--i:${i}"><b>${esc(r.nama)}</b>
        <span class="meta">${r.zona ? `<span class="chip place">${esc(r.zona)}</span>` : ""}<span>tercatat ${timeAgo(r.baru_sejak)}</span>
        <a href="https://www.openstreetmap.org/?mlat=${Number(r.lat)}&mlon=${Number(r.lon)}#map=18/${Number(r.lat)}/${Number(r.lon)}" target="_blank" rel="noopener noreferrer">lihat peta</a></span></li>`).join("")
        || empty("Belum ada tempat baru tercatat. Muncul setelah pemindaian OSM harian menemukan tempat yang baru ditambahkan.");
    } catch (e) { fail(elBaru, e); }
  }

  // ------------------------------------------------------------ kuliner videos (YouTube, collectors/youtube.py)
  const VIDEO_PAGE = 12;
  const PROV = { 31: "DKI Jakarta", 32: "Jawa Barat", 36: "Banten" };   // province-level codes
  const ytId = (url) => (/[?&]v=([\w-]{11})/.exec(url || "") || /youtu\.be\/([\w-]{11})/.exec(url || "") || [])[1];
  const fmtViews = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace(".", ",")} jt` : n >= 1000 ? `${Math.round(n / 1000)} rb` : `${n}`);
  async function renderVideos(more = false) {
    const el = $("#list-video");
    if (!more) {
      el.innerHTML = skeleton(3);
      try {
        const rows = (await data.videos(S.area)).filter((r) => ytId(r.url))
          .map((r) => ({ ...r, views: Number((r.meta && r.meta.stats && r.meta.stats.viewCount) || 0) }));
        if ($("#v-urut").value === "views") rows.sort((a, b) => b.views - a.views);
        S.videos = rows; S.videoN = 0;
      } catch (e) { fail(el, e); return; }
    }
    const part = S.videos.slice(S.videoN, S.videoN + VIDEO_PAGE);
    const html = part.map((r, i) => {
      const id = ytId(r.url), where = (S.zonas.find((z) => z.id === r.zona_id) || {}).nama || PROV[r.kode_wilayah] || kodeNama(r.kode_wilayah);
      return `<li style="--i:${i}"><a href="https://www.youtube.com/watch?v=${id}" target="_blank" rel="noopener noreferrer">
        <span class="thumb"><img src="https://i.ytimg.com/vi/${id}/mqdefault.jpg" alt="" loading="lazy" width="320" height="180"><span class="play" aria-hidden="true"></span></span>
        <span class="vt">${esc(r.judul)}</span></a>
        <span class="meta">${where ? `<span class="chip place">${esc(where)}</span>` : ""}<span>${esc((r.meta && r.meta.channel) || "YouTube")}</span><span>${fmtViews(r.views)} ditonton</span><span>${timeAgo(r.published_at)}</span></span></li>`;
    }).join("");
    if (more) el.insertAdjacentHTML("beforeend", html);
    else el.innerHTML = html || empty(`Belum ada video kuliner minggu ini untuk ${areaName()}.`);
    S.videoN += part.length;
    $("#more-video").hidden = S.videoN >= S.videos.length;
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
          <span class="trend-q">${esc(r.judul)}</span>${n ? `<span class="trend-n">${fmtTraffic(n)}</span>` : ""}</a></li>`;
      }).join("") || `<li class="empty">Belum ada data trending. Diperbarui tiap 15 menit.</li>`;
    } catch (e) { el.innerHTML = `<li class="empty">Gagal memuat trending.</li>`; console.error(e); }
  }

  // ------------------------------------------------------------ saham
  const fmtNum = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const fmtPct = (n) => (n == null ? "–" : `${n > 0 ? "+" : ""}${fmtNum(n, 2)}%`);
  const arah = (n) => (n > 0 ? "naik" : n < 0 ? "turun" : "datar");
  const panah = (n) => (n > 0 ? "▲" : n < 0 ? "▼" : "■");
  function sparkline(vals, w = 90, h = 28) {
    if (!vals || vals.length < 2) return `<span class="spark-empty" style="width:${w}px"></span>`;
    const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
    const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`).join(" ");
    return `<svg class="spark ${vals[vals.length - 1] >= vals[0] ? "naik" : "turun"}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`;
  }

  const kodeQS = (k) => (k ? `&kode=cs.${encodeURIComponent(`{"${k}"}`)}` : "");

  async function renderPasarTop() {
    const el = $("#pasar-top");
    try {
      const n = {}, jenis = {};
      for (const r of await data.pasarTop()) for (const k of r.kode || []) {
        if (k === "IHSG") continue;
        n[k] = (n[k] || 0) + 1;
        jenis[k] = r.jenis;
      }
      const top = Object.entries(n).sort((a, b) => b[1] - a[1]).slice(0, 8);
      $("#pasar-top-sec").hidden = !top.length;
      el.innerHTML = top.map(([k, c], i) => `<li><button type="button" data-top="${esc(k)}" class="${S.sh.kode === k ? "on" : ""}" aria-pressed="${S.sh.kode === k}">
        <span class="rk num">${i + 1}</span><b>${esc(k)}</b><span class="jml"><span class="num">${c}</span> berita</span>
        <span class="jn">${jenis[k] === "kripto" ? "Kripto" : "Saham"}</span></button></li>`).join("");
    } catch (e) { $("#pasar-top-sec").hidden = true; console.error(e); }
  }

  function setKode(k) {
    S.sh.kode = S.sh.kode === k ? "" : k;
    renderPasar();
    for (const b of document.querySelectorAll("#pasar-top button")) {
      b.classList.toggle("on", b.dataset.top === S.sh.kode);
      b.setAttribute("aria-pressed", String(b.dataset.top === S.sh.kode));
    }
    $("#pasar-head").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  }

  async function renderPasar(append = false) {
    const el = $("#list-pasar"), sh = S.sh;
    if (!append) {
      sh.pasarOff = 0;
      el.innerHTML = skeleton(3);
      try {
        $("#pasar-kode").hidden = !sh.kode;
        $("#pasar-kode-n").textContent = sh.kode;
        const c = await data.pasarHitung(sh.kode);
        $("#f-pasar").innerHTML = [["", "Semua", c.semua], ["saham", "Saham", c.saham], ["kripto", "Kripto", c.kripto]]
          .map(([k, label, n]) => `<button type="button" data-p="${k}" class="fchip ${sh.pasar === k ? "on" : ""}" ${!n && k ? "disabled" : ""}>${label} <span class="n">${n}</span></button>`).join("");
      } catch (e) { console.error(e); }
    }
    try {
      const rows = await data.pasarBerita(sh.pasar, sh.pasarOff, sh.kode);
      const html = rows.map((r, i) => {
        const url = safeUrl(r.url);
        const kode = (r.kode || []).filter((k) => k !== "IHSG").slice(0, 4);
        return `<li style="--i:${i}" class="${r.jenis === "kripto" ? "kripto" : "saham"} ${r.gambar ? "ada-foto" : ""}">
          ${fotoHTML(r.gambar, url)}<div class="teks">
          ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.judul)}</a>` : `<span class="title">${esc(r.judul)}</span>`}
          <div class="meta"><span class="chip ${r.jenis === "kripto" ? "soft" : ""}">${r.jenis === "kripto" ? "Kripto" : "Saham"}</span>
            ${kode.map((k) => `<button type="button" class="kode-chip" data-kode="${esc(k)}" title="Berita tentang ${esc(k)}">${esc(k)}</button>`).join("")}
            <span class="by">${esc(r.sumber || "")}</span><time>${timeAgo(r.terbit)}</time></div>
        </div></li>`;
      }).join("");
      if (append) el.insertAdjacentHTML("beforeend", html);
      else el.innerHTML = html || empty(sh.kode ? `Belum ada berita tentang ${sh.kode}.` : "Belum ada berita pasar modal.");
      sh.pasarOff += rows.length;
      $("#more-pasar").hidden = rows.length < PAGE;
    } catch (e) { fail(el, e); }
  }

  async function renderSaham() {
    renderPasar();
    renderPasarTop();
    const el = $("#list-saham");
    if (!S.sh.loaded) el.innerHTML = skeleton(6);
    try {
      const [rows, hist] = await Promise.all([data.saham(), data.sahamRiwayat()]);
      S.sh.rows = rows;
      S.sh.hist = {};
      for (const h of hist) (S.sh.hist[h.kode] = S.sh.hist[h.kode] || []).push(Number(h.close));
      S.sh.loaded = true;
      drawSaham();
    } catch (e) { fail(el, e); }
  }

  function drawSaham() {
    const sh = S.sh, el = $("#list-saham");
    const ihsg = sh.rows.find((r) => r.kode === "IHSG");
    const list = sh.rows.filter((r) => r.kode !== "IHSG" && r.harga != null);
    // no price data yet: hide the price section (sort row and list), the market news below stays
    const kosong = !list.length && !ihsg;
    $("#s-sort").closest(".filters").hidden = kosong;
    el.hidden = kosong;
    $("#sq").closest(".search").hidden = kosong;
    if (kosong) {
      $("#ihsg").innerHTML = "";
      $("#movers").innerHTML = "";
      $("#f-sektor").innerHTML = "";
      el.innerHTML = "";
      return;
    }
    const tw = (r) => (r.waktu_data ? new Date(r.waktu_data).toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
    $("#ihsg").innerHTML = ihsg ? `
      <div class="ihsg-main"><span class="lbl">IHSG</span><b class="val">${fmtNum(ihsg.harga, 2)}</b>
        <span class="pill ${arah(ihsg.persen)}">${panah(ihsg.perubahan)} ${fmtNum(Math.abs(ihsg.perubahan || 0), 2)} (${fmtPct(ihsg.persen)})</span></div>
      ${sparkline(sh.hist.IHSG, 320, 64)}
      <span class="note">Indeks Harga Saham Gabungan. Data ${esc(tw(ihsg))} WIB, grafik 70 hari.</span>` : "";
    const naik = [...list].filter((r) => r.persen > 0).sort((a, b) => b.persen - a.persen).slice(0, 3);
    const turun = [...list].filter((r) => r.persen < 0).sort((a, b) => a.persen - b.persen).slice(0, 3);
    const mv = (r) => `<button type="button" class="mover ${arah(r.persen)}" data-kode="${esc(r.kode)}"><b>${esc(r.kode)}</b> ${fmtPct(r.persen)}</button>`;
    $("#movers").innerHTML = (naik.length ? `<div><span class="lbl">▲ Naik terbanyak</span>${naik.map(mv).join("")}</div>` : "")
      + (turun.length ? `<div><span class="lbl">▼ Turun terbanyak</span>${turun.map(mv).join("")}</div>` : "");
    const sek = {};
    for (const r of list) if (r.sektor) sek[r.sektor] = (sek[r.sektor] || 0) + 1;
    $("#f-sektor").innerHTML = [["semua", list.length], ...Object.entries(sek).sort()].map(([s, n]) =>
      `<button type="button" data-s="${esc(s)}" class="fchip ${sh.sektor === s ? "on" : ""}">${s === "semua" ? "Semua sektor" : esc(s)} <span class="n">${n}</span></button>`).join("");
    $("#s-sort").value = sh.sort;
    const q = sh.q.trim().toLowerCase();
    const rows = list.filter((r) => (sh.sektor === "semua" || r.sektor === sh.sektor)
      && (!q || r.kode.toLowerCase().includes(q) || (r.nama || "").toLowerCase().includes(q)));
    const by = { kode: (a, b) => a.kode.localeCompare(b.kode), naik: (a, b) => (b.persen ?? -1e9) - (a.persen ?? -1e9),
      turun: (a, b) => (a.persen ?? 1e9) - (b.persen ?? 1e9), volume: (a, b) => (b.volume || 0) - (a.volume || 0) };
    rows.sort(by[sh.sort]);
    el.innerHTML = rows.map((r, i) => `<li class="saham-row" data-kode="${esc(r.kode)}" style="--i:${i}">
      <button type="button" class="sh-btn" aria-expanded="false">
        <span class="sh-id"><b>${esc(r.kode)}</b><span>${esc(r.nama || "")}</span></span>
        ${sparkline(sh.hist[r.kode])}
        <span class="sh-harga">${fmtNum(r.harga)}</span>
        <span class="pill ${arah(r.persen)}">${fmtPct(r.persen)}</span>
      </button>
      <div class="sh-detail" hidden></div>
    </li>`).join("") || empty("Tidak ada saham yang cocok.");
  }

  async function bukaSaham(li) {
    const det = li.querySelector(".sh-detail"), btn = li.querySelector(".sh-btn");
    const open = det.hidden;
    det.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (!open || det.dataset.ok) return;
    const r = S.sh.rows.find((x) => x.kode === li.dataset.kode);
    if (!r) return;
    det.innerHTML = `${sparkline(S.sh.hist[r.kode], 320, 70)}
      <dl class="ohlc"><div><dt>Buka</dt><dd>${fmtNum(r.buka)}</dd></div><div><dt>Tertinggi</dt><dd>${fmtNum(r.tertinggi)}</dd></div>
        <div><dt>Terendah</dt><dd>${fmtNum(r.terendah)}</dd></div><div><dt>Tutup kemarin</dt><dd>${fmtNum(r.tutup_kemarin)}</dd></div>
        <div><dt>Perubahan</dt><dd class="${arah(r.perubahan)}">${panah(r.perubahan)} ${fmtNum(Math.abs(r.perubahan || 0))}</dd></div>
        <div><dt>Volume</dt><dd>${fmtNum(r.volume)}</dd></div></dl>
      <p class="note">${r.sektor ? `Sektor ${esc(r.sektor)}. ` : ""}<a href="https://www.google.com/finance/quote/${encodeURIComponent(r.kode)}:IDX" target="_blank" rel="noopener noreferrer">Lihat di Google Finance</a></p>
      <h4>Berita terkait</h4><ul class="sh-news"><li class="note">Memuat…</li></ul>`;
    det.dataset.ok = "1";
    try {
      const news = await data.sahamBerita(r.kode);
      det.querySelector(".sh-news").innerHTML = news.map((n) => `<li><a href="${esc(safeUrl(n.url) || "#")}" target="_blank" rel="noopener noreferrer">${esc(n.judul)}</a>
        <span class="note">${esc(n.sumber || "")}, ${timeAgo(n.terbit)}</span></li>`).join("") || `<li class="note">Belum ada berita 7 hari terakhir.</li>`;
    } catch (e) { det.querySelector(".sh-news").innerHTML = `<li class="note">Gagal memuat berita.</li>`; }
  }

  // ------------------------------------------------------------ china
  const KAT_CN = { teknologi: "Teknologi", bisnis: "Bisnis & pasar", fnb: "F&B & franchise", kebijakan: "Kebijakan", sosial: "Sosial", lainnya: "Lainnya" };

  async function renderChina(append = false) {
    const el = $("#list-china"), cn = S.cn, rng = beritaRange(cn.w, 14);
    if (!append) {
      cn.offset = 0;
      el.innerHTML = skeleton(5);
      const w = cn.w || "semua", mode = w.startsWith("atur:") ? "atur" : w.startsWith("tgl:") ? "tgl" : w;
      $("#c-waktu").value = mode;
      $("#c-hari-wrap").hidden = mode !== "atur";
      $("#c-tgl-wrap").hidden = mode !== "tgl";
      if (mode === "atur") { const n = parseInt(w.slice(5), 10) || 7; $("#c-hari").value = n; $("#c-hari-n").textContent = `${n} hari`; }
      if (mode === "tgl") $("#c-tgl").value = w.slice(4);
      $("#h-china-waktu").textContent = judulWaktu(w);
      $("#c-reset").hidden = cn.kat === "semua" && w === "semua" && !cn.sumber && !cn.jenis;
      try {
        // same layout as Berita: category chips, source-type chips, then Waktu / Sumber
        const meta = await data.chinaMeta(rng);
        const kat = (m) => m.kategori || "lainnya";
        const ck = { semua: 0 }, cj = { "": 0 }, cs = {};
        for (const m of meta) {
          if ((!cn.jenis || m.jenis_sumber === cn.jenis) && (!cn.sumber || m.sumber === cn.sumber)) { ck.semua++; ck[kat(m)] = (ck[kat(m)] || 0) + 1; }
          if ((cn.kat === "semua" || kat(m) === cn.kat) && (!cn.sumber || m.sumber === cn.sumber)) { cj[""]++; cj[m.jenis_sumber] = (cj[m.jenis_sumber] || 0) + 1; }
          if ((cn.kat === "semua" || kat(m) === cn.kat) && (!cn.jenis || m.jenis_sumber === cn.jenis)) cs[m.sumber] = (cs[m.sumber] || 0) + 1;
        }
        $("#f-china").innerHTML = [["semua", "Semua"], ...Object.entries(KAT_CN)].map(([k, label]) =>
          `<button type="button" data-k="${k}" class="fchip ${cn.kat === k ? "on" : ""}" ${!ck[k] && k !== "semua" && cn.kat !== k ? "disabled" : ""}>${label} <span class="n">${ck[k] || 0}</span></button>`).join("");
        $("#f-cjenis").innerHTML = ["", "negara", "swasta", "agregator"].map((j) => `<button type="button" data-j="${j}" class="fchip ${cn.jenis === j ? "on" : ""}" ${!cj[j] && j && cn.jenis !== j ? "disabled" : ""}>
          ${j ? JENIS_SUMBER[j][0] : "Semua jenis sumber"} <span class="n">${cj[j] || 0}</span></button>`).join("");
        $("#c-sumber").innerHTML = `<option value="">Semua sumber</option>` + Object.keys(cs).sort().map((s) =>
          `<option value="${esc(s)}" ${cn.sumber === s ? "selected" : ""}>${esc(s)}</option>`).join("")
          + (cn.sumber && !cs[cn.sumber] ? `<option value="${esc(cn.sumber)}" selected>${esc(cn.sumber)}</option>` : "");
      } catch (e) { console.error(e); }
    }
    try {
      const rows = await data.china(cn.kat, cn.sumber, cn.q, cn.offset, cn.jenis, rng);
      const html = rows.map((r, i) => {
        const url = safeUrl(r.url);
        return `<li style="--i:${i}" class="cn-${esc(r.kategori || "lainnya")} ${r.gambar ? "ada-foto" : ""}">
          ${fotoHTML(r.gambar, url)}<div class="teks">
          ${url ? `<a class="title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.judul_id)}</a>` : `<span class="title">${esc(r.judul_id)}</span>`}
          ${cn.asli ? `<p class="asli" lang="${r.bahasa === "zh" ? "zh" : "en"}">${esc(r.judul_asli)}</p>` : ""}
          ${r.inti ? intiHTML(r.inti, url, r.sumber) : r.ringkasan_id ? `<p class="sum">${esc(r.ringkasan_id)}</p>` : ""}
          <div class="meta"><span class="chip">${KAT_CN[r.kategori] || KAT_CN.lainnya}</span>
            ${badgeSumber(r.jenis_sumber)}
            <span class="lang">${r.bahasa === "zh" ? "中文" : "EN"}</span><span class="by">${esc(r.sumber || "")}</span><time>${timeAgo(r.terbit)}</time></div>
        </div></li>`;
      }).join("");
      if (append) el.insertAdjacentHTML("beforeend", html);
      else el.innerHTML = html || empty(DEMO ? "Mode demo: belum ada berita China." : "Belum ada berita yang cocok.");
      cn.offset += rows.length;
      $("#more-china").hidden = rows.length < PAGE;
    } catch (e) { fail(el, e); }
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

  // Leaflet (about 150 kB) loads only when the Peta tab is first opened
  let leaflet;
  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (leaflet) return leaflet;
    const base = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = `${base}leaflet.min.css`;
    document.head.appendChild(css);
    leaflet = new Promise((ok, no) => {
      const js = document.createElement("script");
      js.src = `${base}leaflet.min.js`; js.onload = ok; js.onerror = no;
      document.head.appendChild(js);
    });
    return leaflet;
  }

  async function renderMap() {
    try { await loadLeaflet(); } catch (e) { $("#map").textContent = "Peta gagal dimuat. Coba lagi nanti."; leaflet = null; return; }
    ensureMap();
    if (!S.map) return;
    S.map.invalidateSize();
    S.layers.clearLayers();
    const info = getComputedStyle(document.documentElement).getPropertyValue("--color-zone").trim();
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
          .bindPopup(`<b>${esc(r.judul)}</b><br>${esc(r.lokasi || "")}${r.harga_teks ? `<br>${esc(r.harga_teks)}` : ""}<br>s.d. ${esc(tgl(r.selesai))}${url ? `<br><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">info lengkap</a>` : ""}`)
          .addTo(S.layers);
      }
      const max = Math.max(0.001, ...viral.map((r) => r.skor));
      for (const r of baru) {
        if (r.lat == null) continue;
        L.marker([r.lat, r.lon], { icon: pinIcon(12, "new") })
          .bindPopup(`<b>${esc(r.nama)}</b><br>Tempat baru${r.zona ? `, ${esc(r.zona)}` : ""}`).addTo(S.layers);
      }
      for (const r of viral) {
        if (r.lat == null) continue;
        const url = safeUrl(r.contoh_url);
        L.marker([r.lat, r.lon], { icon: pinIcon(Math.round(14 + 16 * (r.skor / max))), zIndexOffset: 1000 })
          .bindPopup(`<b>${esc(r.nama)}</b><br>${esc(r.zona || "")}<br>${(r.tier || 1) === 1 ? `${r.mention_24j} sebutan/24 jam` : `${(r.detail && r.detail.mention_7h) || r.mention_24j} sebutan/7 hari`}, skor ${r.skor.toFixed(2)}${url ? `<br><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">contoh konten</a>` : ""}`)
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
    for (const t of ["berita", "promo", "viral", "saham", "china", "peta"]) $(`#tab-${t}`).hidden = t !== S.tab;
    moveIndicator();
    saveHash();
    if (withStats) renderStats();
    ({ berita: renderBerita, promo: renderPromo, viral: renderViral, saham: renderSaham, china: renderChina, peta: renderMap })[S.tab]();
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

  const currentTheme = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  function syncThemeIcon() {
    const dark = currentTheme() === "dark";
    $("#theme").textContent = dark ? "Terang" : "Gelap";
    $("#theme").setAttribute("aria-label", dark ? "Ganti ke tema terang" : "Ganti ke tema gelap");
  }

  function bind() {
    $("#area").addEventListener("change", (e) => { S.area = areaFromValue(e.target.value); render(true); });
    for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => {
      // measured BEFORE switching: the new tab starts short (skeleton) and would clamp the scroll position
      const sticky = getComputedStyle($(".top")).position === "sticky";
      const top = Math.max(0, $("main").getBoundingClientRect().top + window.scrollY - (sticky ? $(".top").offsetHeight : 0) - 8);
      const jauh = window.scrollY > top;
      S.tab = b.dataset.tab;
      render();
      // already scrolled past the hero: glide to the start of the tab's content instead of jumping
      if (jauh) window.scrollTo({ top, behavior: REDUCED ? "auto" : "smooth" });
    });
    window.addEventListener("resize", moveIndicator);
    $("#more-berita").addEventListener("click", () => renderBerita(true));
    $("#f-china").addEventListener("click", (e) => { const b = e.target.closest("button[data-k]"); if (b) { S.cn.kat = b.dataset.k; renderChina(); } });
    $("#c-sumber").addEventListener("change", (e) => { S.cn.sumber = e.target.value; renderChina(); });
    $("#f-cjenis").addEventListener("click", (e) => { const b = e.target.closest("button[data-j]"); if (b) { S.cn.jenis = b.dataset.j; S.cn.sumber = ""; renderChina(); } });
    $("#c-reset").addEventListener("click", () => { Object.assign(S.cn, { kat: "semua", w: "semua", sumber: "", jenis: "" }); renderChina(); });
    $("#c-asli").addEventListener("change", (e) => { S.cn.asli = e.target.checked; renderChina(); });
    $("#more-china").addEventListener("click", () => renderChina(true));
    $("#more-video").addEventListener("click", () => renderVideos(true));
    $("#v-urut").addEventListener("change", () => renderVideos());
    // the "video kuliner" counter opens the Viral tab at the video list
    $("#stat-video").addEventListener("click", () => {
      document.querySelector('[data-tab="viral"]').click();
      setTimeout(() => $("#video-sec").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" }), 300);
    });
    // China time filter: same controls as Berita, limited to the 14 days the database keeps
    const setCW = (w) => { S.cn.w = w; renderChina(); };
    $("#c-waktu").addEventListener("change", (e) => {
      const v = e.target.value;
      $("#c-hari-wrap").hidden = v !== "atur";
      $("#c-tgl-wrap").hidden = v !== "tgl";
      if (v === "atur") setCW(`atur:${$("#c-hari").value}`);
      else if (v === "tgl") { $("#c-tgl").focus(); if ($("#c-tgl").value) setCW(`tgl:${$("#c-tgl").value}`); }
      else setCW(v);
    });
    $("#c-hari").addEventListener("input", (e) => { $("#c-hari-n").textContent = `${e.target.value} hari`; });
    $("#c-hari").addEventListener("change", (e) => setCW(`atur:${e.target.value}`));
    $("#c-tgl").max = tglWIB();
    $("#c-tgl").min = tglWIB(Date.now() - 13 * 86400e3);
    $("#c-tgl").addEventListener("change", (e) => { if (e.target.value) setCW(`tgl:${e.target.value}`); });
    let tc;
    $("#cq").addEventListener("input", (e) => { clearTimeout(tc); tc = setTimeout(() => { S.cn.q = e.target.value; renderChina(); }, 300); });
    $("#f-pasar").addEventListener("click", (e) => { const b = e.target.closest("button[data-p]"); if (b) { S.sh.pasar = b.dataset.p; renderPasar(); } });
    $("#more-pasar").addEventListener("click", () => renderPasar(true));
    $("#list-pasar").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-kode]");
      if (!b) return;
      const li = document.querySelector(`.saham-row[data-kode="${CSS.escape(b.dataset.kode)}"]`);
      if (li && !$("#list-saham").hidden) { li.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" }); bukaSaham(li); }
      else setKode(b.dataset.kode);
    });
    $("#pasar-top").addEventListener("click", (e) => { const b = e.target.closest("button[data-top]"); if (b) setKode(b.dataset.top); });
    $("#pasar-kode-x").addEventListener("click", () => setKode(S.sh.kode));
    $("#f-sektor").addEventListener("click", (e) => { const b = e.target.closest("button[data-s]"); if (b) { S.sh.sektor = b.dataset.s; drawSaham(); } });
    $("#s-sort").addEventListener("change", (e) => { S.sh.sort = e.target.value; drawSaham(); });
    let ts;
    $("#sq").addEventListener("input", (e) => { clearTimeout(ts); ts = setTimeout(() => { S.sh.q = e.target.value; drawSaham(); }, 200); });
    $("#list-saham").addEventListener("click", (e) => { const li = e.target.closest(".sh-btn") && e.target.closest(".saham-row"); if (li) bukaSaham(li); });
    $("#movers").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-kode]");
      if (!b) return;
      S.sh.sektor = "semua"; S.sh.q = ""; $("#sq").value = ""; drawSaham();
      const li = document.querySelector(`.saham-row[data-kode="${CSS.escape(b.dataset.kode)}"]`);
      if (li) { li.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" }); bukaSaham(li); }
    });
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
    $("#f-topik").addEventListener("click", (e) => { const b = e.target.closest("button[data-t]"); if (b) setBF({ t: b.dataset.t }); });
    $("#b-waktu").addEventListener("change", (e) => {
      const v = e.target.value;
      $("#b-tgl-wrap").hidden = v !== "tgl";
      if (v === "tgl") { $("#b-tgl").focus(); if ($("#b-tgl").value) setBF({ w: `tgl:${$("#b-tgl").value}` }); }
      else setBF({ w: v });
    });
    // date picker limited to the 30 days the database keeps
    $("#b-tgl").max = tglWIB();
    $("#b-tgl").min = tglWIB(Date.now() - 30 * 86400e3);
    $("#b-tgl").addEventListener("change", (e) => { if (e.target.value) setBF({ w: `tgl:${e.target.value}` }); });
    $("#b-sumber").addEventListener("change", (e) => setBF({ s: e.target.value }));
    $("#b-reset").addEventListener("click", () => setBF({ t: "semua", w: "semua", s: "", j: "", v: false }));
    $("#b-verif").addEventListener("change", (e) => setBF({ v: e.target.checked, s: "" }));
    $("#hoaks-box").addEventListener("toggle", (e) => { if (e.target.open && !$("#list-hoaks").children.length) renderHoaks(); }, { once: false });
    $("#f-jenis").addEventListener("click", (e) => { const b = e.target.closest("button[data-j]"); if (b) setBF({ j: b.dataset.j, s: "" }); });
    $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value; renderBerita(); }, 300); });

    $("#theme").addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      store.set("theme", next);
      syncThemeIcon();
    });

    document.addEventListener("error", (e) => {
      const f = e.target.closest && e.target.closest(".foto");
      if (f) { f.closest("li").classList.remove("ada-foto"); f.remove(); }
    }, true);

    const toTop = $("#to-top");
    let scrollTick = false;   // at most one update per frame while scrolling
    window.addEventListener("scroll", () => {
      if (scrollTick) return;
      scrollTick = true;
      requestAnimationFrame(() => { toTop.classList.toggle("show", window.scrollY > 600); scrollTick = false; });
    }, { passive: true });
    toTop.addEventListener("click", () => window.scrollTo({ top: 0 }));

    $("#near").addEventListener("click", () => {
      const btn = $("#near");
      if (!navigator.geolocation) { toast("Browser ini tidak mendukung lokasi."); return; }
      btn.disabled = true;
      toast("Mencari lokasi Anda…");
      navigator.geolocation.getCurrentPosition((pos) => {
        S.me = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        const v = nearest(S.me.lat, S.me.lon);
        btn.disabled = false;
        if (!v) { toast("Lokasi Anda di luar Jabodetabek."); return; }
        $("#area").value = v; S.area = areaFromValue(v);
        toast(`Menampilkan area ${S.area.nama}`);
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
        b.textContent = "Terkirim"; b.classList.add("done");
        toast("Terima kasih. Laporan masuk ke skor jam berikutnya.");
      } catch (err) { b.disabled = false; toast("Gagal mengirim laporan."); console.error(err); }
    });

    $("#lapor").addEventListener("submit", async (e) => {
      e.preventDefault();
      const zona = Number($("#lapor-zona").value), nama = $("#lapor-nama").value.trim();
      if (!zona || !nama) return;
      try {
        await data.lapor({ zona_id: zona, nama_tempat: nama.slice(0, 120), jenis: "ramai" });
        toast(DEMO ? "Mode demo: laporan tidak disimpan." : "Terima kasih. Laporan masuk ke perhitungan skor.");
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
    if (["berita", "promo", "viral", "saham", "china", "peta"].includes(tab)) S.tab = tab;
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
