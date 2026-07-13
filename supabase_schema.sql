-- Run this in Supabase: SQL Editor -> New query -> paste -> Run

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
  is_blacklisted boolean default false,      -- "para peças", "avariado", etc.
  olx_created_at timestamptz,
  first_seen    timestamptz default now(),
  last_seen     timestamptz default now(),
  params        jsonb                        -- all raw OLX params, for debugging
);

create index if not exists ads_market_idx on ads (brand, model, year);
create index if not exists ads_price_idx  on ads (price);

create table if not exists deals (
  ad_id        bigint primary key references ads(id),
  price        numeric,
  median_price numeric,
  discount     numeric,                      -- 0.30 = 30% below median
  est_profit   numeric,                      -- median*0.85 - price
  score        numeric,                      -- higher = better
  created_at   timestamptz default now(),
  notified     boolean default false
);

-- Market medians per brand/model/2-year bucket (needs >= 5 comparable ads)
create or replace view market_stats as
select
  brand,
  model,
  (year / 2) * 2 as year_bucket,
  count(*)::int as n,
  percentile_cont(0.5) within group (order by price) as median_price
from ads
where price is not null and price > 100
  and brand is not null and model is not null and year is not null
  and not is_blacklisted
group by 1, 2, 3
having count(*) >= 5;

-- Dashboard convenience view
create or replace view deals_view as
select d.*, a.title, a.url, a.brand, a.model, a.year, a.mileage, a.fuel,
       a.region, a.olx_created_at
from deals d join ads a on a.id = d.ad_id
order by d.created_at desc;
