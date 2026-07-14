-- Run this in Supabase: SQL Editor -> New query -> paste -> Run
-- Safe to re-run on an existing project: tables use IF NOT EXISTS + ALTERs,
-- views are dropped and recreated.

create table if not exists ads (
  id            bigint primary key,          -- OLX offer id
  url           text not null,
  title         text,
  price         numeric,
  brand         text,
  model         text,
  year          int,
  mileage       int,
  fuel          text,
  region        text,
  photo_url     text,
  is_blacklisted boolean default false,      -- "para peças", "avariado", etc.
  olx_created_at timestamptz,
  first_seen    timestamptz default now(),
  last_seen     timestamptz default now(),
  params        jsonb                        -- all raw OLX params, for debugging
);

alter table ads add column if not exists photo_url text;
alter table ads add column if not exists url_status text;        -- 'active' | 'sold' | 'removed' | null (unchecked)
alter table ads add column if not exists url_checked_at timestamptz;

create index if not exists ads_market_idx on ads (brand, model, year);
create index if not exists ads_price_idx  on ads (price);

-- Per-ad user flags (skip / favourite). Single-user app, no auth concept,
-- so keyed only by ad_id + flag rather than a per-user row.
create table if not exists ad_flags (
  ad_id      bigint not null references ads(id),
  flag       text not null,              -- 'skipped' | 'favourite'
  created_at timestamptz not null default now(),
  primary key (ad_id, flag)
);

create index if not exists ad_flags_flag_idx on ad_flags (flag);

create table if not exists deals (
  ad_id        bigint primary key references ads(id),
  price        numeric,
  median_price numeric,
  discount     numeric,                      -- 0.30 = 30% below median
  est_profit   numeric,                      -- median*0.85 - price
  score        numeric,                      -- higher = better
  n            int,                          -- comparable ads behind the median
  confidence   text,                         -- alta | media | baixa
  fingerprint  text,                         -- brand|model|year|km|price, for re-listing dedupe
  created_at   timestamptz default now(),
  notified     boolean default false
);

alter table deals add column if not exists n int;
alter table deals add column if not exists confidence text;
alter table deals add column if not exists fingerprint text;

-- RLS: public read-only, backend (crawler/url_checker) read+write. The crawler's
-- upsert path already worked before these existed (INSERT ... ON CONFLICT DO UPDATE
-- coincidentally cleared the RLS bar some other way), but plain per-row UPDATEs
-- (url_checker's status writes, deal pricing refreshes) were silently matching zero
-- rows under RLS with no INSERT/UPDATE policy at all — PostgREST returned 200 OK
-- either way, so the failure was invisible until traced through GH Actions logs.
alter table ads enable row level security;
alter table deals enable row level security;

drop policy if exists "public read access" on ads;
create policy "public read access" on ads for select to anon, authenticated using (true);
drop policy if exists "backend insert access" on ads;
create policy "backend insert access" on ads for insert to anon, authenticated with check (true);
drop policy if exists "backend update access" on ads;
create policy "backend update access" on ads for update to anon, authenticated using (true) with check (true);

drop policy if exists "public read access" on deals;
create policy "public read access" on deals for select to anon, authenticated using (true);
drop policy if exists "backend insert access" on deals;
create policy "backend insert access" on deals for insert to anon, authenticated with check (true);
drop policy if exists "backend update access" on deals;
create policy "backend update access" on deals for update to anon, authenticated using (true) with check (true);

-- Every price seen for an ad: first sighting + one row per change.
create table if not exists price_history (
  ad_id   bigint not null references ads(id),
  price   numeric not null,
  seen_at timestamptz not null default now(),
  primary key (ad_id, seen_at)
);

-- One row per crawler run (dashboard health indicator).
create table if not exists crawl_runs (
  id           bigserial primary key,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  mode         text,                         -- incremental | deep_sweep
  ads_fetched  int,
  deals_found  int
);

-- Views are dropped first: create-or-replace can't reorder/insert columns.
drop view if exists deals_view;
drop view if exists market_stats;
drop view if exists market_stats_fuel;
drop view if exists market_stats_fine;
drop view if exists market_liquidity;

-- Market medians per brand/model/2-year bucket (needs >= 5 comparable ads,
-- seen in the last 90 days). Year bucketing must stay identical to
-- deal_engine.stats_key().
create view market_stats as
select
  brand,
  model,
  (year / 2) * 2 as year_bucket,
  count(*)::int as n,
  percentile_cont(0.5)  within group (order by price) as median_price,
  percentile_cont(0.25) within group (order by price) as p25,
  percentile_cont(0.75) within group (order by price) as p75
from ads
where price is not null and price > 100
  and brand is not null and model is not null and year is not null
  and not is_blacklisted
  and last_seen > now() - interval '90 days'
group by 1, 2, 3
having count(*) >= 5;

-- Middle tier: same bucket + fuel (no mileage band). Used when the fuel+mileage
-- ("fine") bucket doesn't have enough comps, so we don't fall all the way back to
-- a fuel-blind coarse median. Must stay identical to deal_engine.fuel_key().
create view market_stats_fuel as
select
  brand,
  model,
  (year / 2) * 2 as year_bucket,
  fuel,
  count(*)::int as n,
  percentile_cont(0.5)  within group (order by price) as median_price,
  percentile_cont(0.25) within group (order by price) as p25,
  percentile_cont(0.75) within group (order by price) as p75
from ads
where price is not null and price > 100
  and brand is not null and model is not null and year is not null
  and fuel is not null
  and not is_blacklisted
  and last_seen > now() - interval '90 days'
group by 1, 2, 3, 4
having count(*) >= 5;

-- Finer comps: same bucket + fuel + mileage band. Band edges (150k/250k)
-- must stay identical to deal_engine.km_band() / config.KM_BANDS.
create view market_stats_fine as
select
  brand,
  model,
  (year / 2) * 2 as year_bucket,
  fuel,
  case when mileage < 150000 then 0
       when mileage < 250000 then 150000
       else 250000 end as km_band,
  count(*)::int as n,
  percentile_cont(0.5)  within group (order by price) as median_price,
  percentile_cont(0.25) within group (order by price) as p25,
  percentile_cont(0.75) within group (order by price) as p75
from ads
where price is not null and price > 100
  and brand is not null and model is not null and year is not null
  and fuel is not null and mileage is not null
  and not is_blacklisted
  and last_seen > now() - interval '90 days'
group by 1, 2, 3, 4, 5
having count(*) >= 5;

-- Liquidity per bucket: how many ads are live now, and how long ads that sold
-- stayed listed. "Sold" prefers the confirmed url_status check (its own page said
-- sold/removed — url_checked_at is when we learned that, frozen at that point since
-- url_checker never rechecks a terminal status) and falls back to the last_seen
-- staleness proxy (gone 8+ days, one weekly deep sweep + slack) for ads url_checker
-- hasn't gotten to yet. Must match deal engine / dashboard's ACTIVE_WINDOW_DAYS.
create view market_liquidity as
with dated as (
  select
    brand, model, (year / 2) * 2 as year_bucket,
    olx_created_at,
    last_seen,
    case
      when url_status in ('sold', 'removed') then url_checked_at
      when last_seen <= now() - interval '8 days' then last_seen
    end as sold_at
  from ads
  where brand is not null and model is not null and year is not null
    and not is_blacklisted
)
select
  brand,
  model,
  year_bucket,
  count(*) filter (where sold_at is null and last_seen > now() - interval '8 days')::int
    as active_ads,
  percentile_cont(0.5) within group (
    order by extract(epoch from (sold_at - olx_created_at)) / 86400
  ) filter (where sold_at is not null and olx_created_at is not null
            and sold_at > olx_created_at) as median_days_to_sell
from dated
group by 1, 2, 3;

-- Dashboard convenience view
create view deals_view as
select d.*,
       a.title, a.url, a.brand, a.model, a.year, a.mileage, a.fuel,
       a.region, a.olx_created_at, a.photo_url, a.last_seen,
       a.url_status, a.url_checked_at,
       a.price as current_price,
       case
         when a.url_status in ('sold', 'removed') then 'desaparecido'
         when a.url_status = 'active' then 'ativo'
         when a.last_seen > now() - interval '8 days' then 'ativo'
         else 'desaparecido'
       end as status,
       greatest(0, extract(epoch from (a.last_seen - a.olx_created_at)) / 86400)::int
         as days_listed,
       ph.previous_price,
       case when ph.previous_price > a.price
            then ph.previous_price - a.price end as price_drop
from deals d
join ads a on a.id = d.ad_id
left join lateral (
  select h.price as previous_price
  from price_history h
  where h.ad_id = d.ad_id
  order by h.seen_at desc
  offset 1 limit 1
) ph on true
order by d.created_at desc;
