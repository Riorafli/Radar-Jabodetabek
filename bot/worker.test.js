import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { areaFilter, findArea, handle, isAdmin, parseCommand, parseTambahPromo, timeAgo } from "./worker.js";

const zonas = [
  { id: 1, nama: "Kemang", alias: ["kemang", "kemang raya"], kecuali: ["bogor"], kode_wilayah: "31.74" },
  { id: 2, nama: "BSD City", alias: ["bsd", "serpong bsd"], kecuali: [], kode_wilayah: "36.74" },
];
const wilayahs = [
  { kode: "31.74", nama: "Jakarta Selatan", alias: ["jaksel"] },
  { kode: "36.71", nama: "Kota Tangerang", alias: ["tangerang"] },
  { kode: "36.74", nama: "Tangerang Selatan", alias: ["tangsel", "tangerang selatan"] },
  { kode: "32.01", nama: "Kabupaten Bogor", alias: ["kab bogor"] },
];

test("parseCommand strips @botname and splits args", () => {
  assert.deepEqual(parseCommand("/promo@RadarBot kemang raya"), { cmd: "/promo", arg: "kemang raya" });
  assert.deepEqual(parseCommand("/zona"), { cmd: "/zona", arg: "" });
  assert.equal(parseCommand("halo").cmd, null);
});

test("findArea prefers zones, longest alias, honours kecuali", () => {
  assert.equal(findArea("bsd", zonas, wilayahs).nama, "BSD City");
  assert.equal(findArea("Tangerang Selatan", zonas, wilayahs).kode, "36.74");
  assert.equal(findArea("tangerang", zonas, wilayahs).kode, "36.71");
  assert.equal(findArea("kemang", zonas, wilayahs).type, "zona");
  assert.equal(findArea("kemang kab bogor", zonas, wilayahs).kode, "32.01");
  assert.equal(findArea("antah berantah", zonas, wilayahs), null);
});

test("areaFilter builds PostgREST filters", () => {
  assert.equal(areaFilter({ type: "zona", id: 2, kode: "36.74" }), "&zona_id=eq.2");
  assert.equal(areaFilter({ type: "kota", kode: "31.74" }), "&kode_wilayah=eq.31.74");
  assert.match(areaFilter({ type: "kota", kode: "31.74" }, "promo"), /^&or=\(kota_berlaku\.cs\..*31\.74.*,kota_berlaku\.eq\.%7B%7D\)$/);
  assert.equal(areaFilter(null), "");
});

test("parseTambahPromo validates input", () => {
  const ok = parseTambahPromo("Kopi Kenangan | Buy 1 Get 1 | Rp20.000 | 2026-12-31 | bsd | https://x.id");
  assert.equal(ok.brand, "Kopi Kenangan");
  assert.equal(ok.area, "bsd");
  assert.ok(parseTambahPromo("hanya brand").error);
  assert.ok(parseTambahPromo("A | B | C | 31-12-2026").error);
  assert.ok(parseTambahPromo("A | B | C | 2026-12-31 | bsd | ftp://x").error);
});

test("isAdmin trims ids", () => {
  assert.ok(isAdmin({ ADMIN_IDS: "111, 222" }, 222));
  assert.ok(!isAdmin({ ADMIN_IDS: "111" }, 333));
  assert.ok(!isAdmin({}, 111));
});

test("timeAgo", () => {
  const now = Date.parse("2026-10-08T12:00:00Z");
  assert.equal(timeAgo("2026-10-08T11:30:00Z", now), "30 mnt lalu");
  assert.equal(timeAgo("2026-10-08T09:00:00Z", now), "3 jam lalu");
  assert.equal(timeAgo("2026-10-06T12:00:00Z", now), "2 hari lalu");
});

test("handle /tambah_promo refuses non-admins without touching the DB", async () => {
  const out = await handle({ ADMIN_IDS: "1" }, { message: { text: "/tambah_promo A | B", chat: { id: 5, type: "private" }, from: { id: 2 } } });
  assert.equal(out, "Perintah ini khusus admin.");
});

test("webhook rejects requests without the secret token", async () => {
  const req = new Request("https://w/", { method: "POST", body: "{}" });
  const res = await worker.fetch(req, { WEBHOOK_SECRET: "s3cret" });
  assert.equal(res.status, 403);
});

test("/viral queries Supabase with zone filter and formats the reply", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const u = String(url);
    const body = u.includes("/zona?") ? zonas
      : u.includes("/wilayah?") ? wilayahs
      : [{ nama: "Kopi Kenangan", zona: "BSD City", skor: 2.1, mention_24j: 5, platform: 2, contoh_url: "https://youtu.be/x" }];
    return new Response(JSON.stringify(body), { status: 200 });
  };
  try {
    const out = await handle({ SUPABASE_URL: "https://p.supabase.co", SUPABASE_SERVICE_KEY: "k" },
      { message: { text: "/viral bsd", chat: { id: 5, type: "private" }, from: { id: 9 } } });
    assert.match(out, /Viral di BSD City/);
    assert.match(out, /1\. Kopi Kenangan \(BSD City\) - 5 sebutan, 2 platform/);
    assert.ok(calls.some((c) => c.includes("v_viral?") && c.includes("zona_id=eq.2")));
  } finally {
    globalThis.fetch = realFetch;
  }
});
