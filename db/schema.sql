-- Radar Jabodetabek - full schema. Idempotent: safe to run again in the
-- Supabase SQL Editor after edits.

create extension if not exists postgis;
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------- wilayah
-- Kemendagri codes (verified against api.bmkg.go.id, Oct 2026). Note that
-- BPS numbers Jakarta differently (BPS 3171 = Jaksel, Kemendagri 31.71 = Jakpus).
create table if not exists wilayah (
  kode        text primary key,
  nama        text not null,
  level       text not null check (level in ('provinsi','kota','kabupaten','kecamatan')),
  parent_kode text references wilayah(kode),
  bagian      text,                       -- Ja | Bo | De | Ta | Bek
  alias       text[] not null default '{}',
  lat         double precision,
  lon         double precision,
  geom        geometry(MultiPolygon, 4326) -- optional admin boundary
);
create index if not exists wilayah_geom on wilayah using gist (geom);

create table if not exists kawasan (
  id   serial primary key,
  nama text unique not null
);
create table if not exists kawasan_wilayah (
  kawasan_id   int  references kawasan(id) on delete cascade,
  kode_wilayah text references wilayah(kode) on delete cascade,
  primary key (kawasan_id, kode_wilayah)
);

-- ---------------------------------------------------------------- zona
create table if not exists zona (
  id           serial primary key,
  nama         text unique not null,
  kode_wilayah text references wilayah(kode),
  lat          double precision not null,
  lon          double precision not null,
  radius_m     int not null default 1500,
  alias        text[] not null default '{}',
  kecuali      text[] not null default '{}'  -- words that cancel a match ("kemang" + "bogor")
);

-- ---------------------------------------------------------------- entitas
create table if not exists entitas (
  id           bigserial primary key,
  tipe         text not null check (tipe in ('brand','tempat','menu')),
  nama         text not null,
  alias        text[] not null default '{}',
  lat          double precision,
  lon          double precision,
  zona_id      int references zona(id) on delete set null,
  kode_wilayah text references wilayah(kode),
  osm_id       text unique,
  baru_sejak   timestamptz,               -- set when OSM shows a newly added place
  dibuat       timestamptz not null default now()
);
alter table entitas add column if not exists baru_sejak timestamptz;
create index if not exists entitas_nama_trgm on entitas using gin (lower(nama) gin_trgm_ops);
create index if not exists entitas_tipe_nama on entitas (tipe, lower(nama));

-- ---------------------------------------------------------------- item
create table if not exists item (
  id           bigserial primary key,
  tipe         text not null check (tipe in ('berita','info','promo','post')),
  judul        text not null,
  url          text,
  sumber       text,
  ringkasan    text,
  kode_wilayah text references wilayah(kode),
  zona_id      int references zona(id) on delete set null,
  entitas_id   bigint references entitas(id) on delete set null,
  lat          double precision,
  lon          double precision,
  meta         jsonb not null default '{}',
  label_status text not null default 'baru',  -- baru | teks | llm | geocode | gagal
  published_at timestamptz not null default now(),
  dibuat       timestamptz not null default now(),
  hash_dedup   text unique
);
create index if not exists item_tipe_waktu on item (tipe, published_at desc);
create index if not exists item_wilayah    on item (kode_wilayah, published_at desc);
create index if not exists item_zona       on item (zona_id, published_at desc);
create index if not exists item_label      on item (label_status) where label_status = 'baru';
create index if not exists item_judul_trgm on item using gin (judul gin_trgm_ops);

create table if not exists promo (
  item_id       bigint primary key references item(id) on delete cascade,
  brand         text not null,
  menu          text,
  harga         numeric,
  harga_teks    text,
  mulai         date,
  selesai       date,
  syarat        text,
  kota_berlaku  text[] not null default '{}',   -- kode wilayah; empty = all Jabodetabek
  sumber_input  text not null default 'scrape'  -- scrape | manual
);
create index if not exists promo_selesai on promo (selesai);

-- ---------------------------------------------------------------- signals & scores
create table if not exists sinyal (
  id           bigserial primary key,
  entitas_id   bigint references entitas(id) on delete cascade,
  zona_id      int references zona(id) on delete cascade,
  kode_wilayah text,
  sumber       text not null,          -- youtube | berita | reddit | trends | osm_baru | laporan
  ref          text not null default '',  -- video id / url hash, prevents double counting
  nilai        double precision not null default 1,
  engagement   double precision not null default 0,
  waktu        timestamptz not null default now()
);
create unique index if not exists sinyal_uniq on sinyal (entitas_id, sumber, ref, coalesce(zona_id, 0));
create index if not exists sinyal_ez_waktu on sinyal (entitas_id, zona_id, waktu desc);
create index if not exists sinyal_waktu on sinyal (waktu desc);

create table if not exists skor (
  id            bigserial primary key,
  entitas_id    bigint not null references entitas(id) on delete cascade,
  zona_id       int references zona(id) on delete cascade,
  skor          double precision not null,
  mention_24j   int not null default 0,
  platform      int not null default 0,
  detail        jsonb not null default '{}',
  dihitung_pada timestamptz not null default now()
);
create index if not exists skor_zona on skor (zona_id, skor desc);

create table if not exists zona_statistik (
  zona_id    int references zona(id) on delete cascade,
  tanggal    date not null,
  jumlah_poi int not null,
  poi_baru   int not null default 0,
  primary key (zona_id, tanggal)
);

-- crowd reports from web/bot ("ramai" / "viral" buttons)
create table if not exists laporan (
  id          bigserial primary key,
  entitas_id  bigint references entitas(id) on delete cascade,
  zona_id     int references zona(id) on delete cascade,
  nama_tempat text check (char_length(nama_tempat) <= 120),
  jenis       text not null check (jenis in ('ramai','viral')),
  sumber      text not null default 'web' check (sumber in ('web','bot')),
  waktu       timestamptz not null default now(),
  diproses    boolean not null default false
);

-- ---------------------------------------------------------------- internal caches
create table if not exists geocode_cache (
  query        text primary key,
  lat          double precision,
  lon          double precision,
  kode_wilayah text,
  raw          jsonb,
  dibuat       timestamptz not null default now()
);
create table if not exists halaman_cache (
  url     text primary key,
  hash    text not null,
  diambil timestamptz not null default now()
);
create table if not exists langganan (
  id           bigserial primary key,
  chat_id      bigint not null,
  zona_id      int references zona(id) on delete cascade,
  kode_wilayah text references wilayah(kode) on delete cascade,
  dibuat       timestamptz not null default now(),
  check (zona_id is not null or kode_wilayah is not null)
);
create unique index if not exists langganan_uniq on langganan (chat_id, coalesce(zona_id, 0), coalesce(kode_wilayah, ''));
create table if not exists notif_log (
  chat_id    bigint not null,
  entitas_id bigint not null,
  tanggal    date not null,
  primary key (chat_id, entitas_id, tanggal)
);

-- ---------------------------------------------------------------- views for web/bot
create or replace view v_berita with (security_invoker = true) as
select i.id, i.tipe, i.judul, i.url, i.sumber, i.ringkasan, i.published_at,
       i.kode_wilayah, w.nama as wilayah, i.zona_id, z.nama as zona,
       coalesce(i.lat, z.lat, w.lat) as lat, coalesce(i.lon, z.lon, w.lon) as lon
from item i
left join wilayah w on w.kode = i.kode_wilayah
left join zona z on z.id = i.zona_id
where i.tipe in ('berita','info');

create or replace view v_promo with (security_invoker = true) as
select i.id, i.judul, i.url, i.sumber, i.ringkasan, i.published_at,
       i.zona_id, i.kode_wilayah,
       p.brand, p.menu, p.harga, p.harga_teks, p.mulai, p.selesai, p.syarat,
       p.kota_berlaku, p.sumber_input
from item i
join promo p on p.item_id = i.id
where p.selesai is null or p.selesai >= (now() at time zone 'Asia/Jakarta')::date;

create or replace view v_viral with (security_invoker = true) as
select s.entitas_id, e.nama, e.tipe, s.zona_id, z.nama as zona,
       coalesce(z.kode_wilayah, e.kode_wilayah) as kode_wilayah,
       s.skor, s.mention_24j, s.platform, s.detail, s.dihitung_pada,
       coalesce(e.lat, z.lat) as lat, coalesce(e.lon, z.lon) as lon,
       rank() over (partition by s.zona_id order by s.skor desc) as peringkat,
       (select i.url from item i where i.entitas_id = e.id and i.url is not null
         order by i.published_at desc limit 1) as contoh_url
from skor s
join entitas e on e.id = s.entitas_id
left join zona z on z.id = s.zona_id;

create or replace view v_tempat_baru with (security_invoker = true) as
select e.id, e.nama, e.lat, e.lon, e.zona_id, z.nama as zona, e.kode_wilayah, e.osm_id, e.baru_sejak
from entitas e
left join zona z on z.id = e.zona_id
where e.baru_sejak > now() - interval '30 days';

-- ---------------------------------------------------------------- RLS
-- Public (anon key) may only READ public tables and INSERT crowd reports.
-- Collectors write with DATABASE_URL (postgres role), which bypasses RLS.
do $$
declare t text;
begin
  foreach t in array array['wilayah','kawasan','kawasan_wilayah','zona','entitas',
                           'item','promo','skor','zona_statistik'] loop
    execute format('alter table %I enable row level security', t);
    if not exists (select 1 from pg_policies where tablename = t and policyname = 'baca publik') then
      execute format('create policy "baca publik" on %I for select using (true)', t);
    end if;
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
  -- private tables: RLS on, no policy => anon/authenticated get nothing
  foreach t in array array['sinyal','geocode_cache','halaman_cache','langganan','notif_log','laporan'] loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

drop policy if exists "lapor publik" on laporan;
create policy "lapor publik" on laporan for insert to anon, authenticated
  with check (sumber = 'web' and diproses = false);
grant insert on laporan to anon, authenticated;
grant usage on sequence laporan_id_seq to anon, authenticated;

grant select on v_berita, v_promo, v_viral, v_tempat_baru to anon, authenticated;
