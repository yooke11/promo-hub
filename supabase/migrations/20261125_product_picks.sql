-- 2026-11-25 추천 상품(오늘의 추천): 진행 중인 기획전 상품 중 잘 팔릴 만한 상품을 매일 골라 따로 저장한다.
-- 점수(0~100): 할인율 30 + 웹 최저가 대비 25(비싸면 -15) + 여러 채널 중 최저 10 + 가격대 10
--             + 마감 임박 8 + 브랜드 5 + 검색 수요(키워드 월 검색량) 12
-- 다양성: 쇼핑몰당 4개, 기획전당 2개, 같은 상품명 1개. 하루 최대 80개.
create table if not exists public.product_picks (
  pick_date      date        not null,
  item_key       text        not null,
  promotion_id   text        not null,
  rank           int         not null,
  score          numeric(5,1) not null,
  section        text        not null,   -- web_low | ending | half | value | demand | best
  copy           text        not null,   -- 카드에 쓰는 한 줄 카피
  reasons        text[]      not null default '{}',
  name text, brand text, url text, image_url text,
  price int, original_price int, discount_rate int,
  market_lowest int, market_mall text, vs_market_pct numeric,
  source_id text, source_name text, channel_type text,
  promotion_title text, promotion_url text, end_date date, top_keyword text, keyword_volume int,
  created_at timestamptz not null default now(),
  primary key (pick_date, item_key)
);
alter table public.product_picks enable row level security;
drop policy if exists picks_read on public.product_picks;
create policy picks_read on public.product_picks for select to anon, authenticated using (true);
grant select on public.product_picks to anon, authenticated;

create or replace view public.v_picks with (security_invoker = true) as
  select * from public.product_picks
  where pick_date = (select max(pick_date) from public.product_picks)
  order by rank;
grant select on public.v_picks to anon, authenticated;

create or replace function private.refresh_picks_core() returns int
language plpgsql security definer set search_path = public, extensions as $$
declare d date := (now() at time zone 'Asia/Seoul')::date; n int;
begin
  delete from public.product_picks where pick_date = d;           -- 같은 날 다시 돌리면 오늘 것만 새로 만든다
  delete from public.product_picks where pick_date < d - 14;       -- 2주 지난 추천은 정리
  with live as (select id, title, url, end_date from public.v_promotions where status <> 'ended'),
  base0 as (
    select i.*, l.title ptitle, l.url purl, l.end_date pend,
           btrim(regexp_replace(regexp_replace(i.name, '^스크랩\s+', ''), '\s+\d[\d,]*\s*(원|\d+\s*%).*$', '')) cname,
           case when coalesce(i.discount_rate, case when i.original_price > i.price then round(100.0*(i.original_price-i.price)/i.original_price)::int end) between 1 and 90
                then coalesce(i.discount_rate, round(100.0*(i.original_price-i.price)/i.original_price)::int) end dr,  -- 90% 초과는 정가 오인식으로 보고 쓰지 않음
           (l.end_date - d) dleft
    from public.v_items i join live l on l.id = i.promotion_id
    where i.price >= 1000 and coalesce(i.image_url,'') <> '' and coalesce(i.url,'') <> '' and i.url not like 'javascript:%'
  ),
  base as (   -- 검색 수요: 기획전 추천 키워드 중 상품명에 들어 있는 단어만 인정
    select b.*, coalesce(k.vol,0) vol, k.keyword top_kw
    from base0 b
    left join lateral (
      select pk.keyword, coalesce(pk.pc,0)+coalesce(pk.mobile,0) vol
      from public.promotion_keywords pk
      where pk.promotion_id = b.promotion_id
        and exists (select 1 from unnest(string_to_array(pk.keyword, ' ')) w where length(w) >= 2 and position(w in b.cname) > 0)
      order by 2 desc limit 1) k on true
  ),
  scored as (
    select *,
      round((least(coalesce(dr,0),80)/80.0*30
       + case when market_lowest > 0 and price <= market_lowest then 25
              when market_lowest > 0 and vs_market_pct <= 5 then 10
              when market_lowest > 0 and vs_market_pct > 15 then -15 else 0 end
       + case when cross_channels > 1 and price <= cross_lowest then 10 else 0 end
       + case when price between 9900 and 79000 then 10 when price between 79001 and 300000 then 5 else 0 end
       + case when dleft between 0 and 3 then 8 else 0 end
       + case when coalesce(brand,'') <> '' then 5 else 0 end
       + least(12, case when vol > 0 then ln(vol+1)*1.2 else 0 end))::numeric, 1) score
    from base),
  dedup as (select distinct on (lower(regexp_replace(regexp_replace(cname,'\(.*?\)|\[.*?\]','','g'),'\s+','','g'))) * from scored
            order by lower(regexp_replace(regexp_replace(cname,'\(.*?\)|\[.*?\]','','g'),'\s+','','g')), score desc),
  ranked as (select *, row_number() over (partition by source_id order by score desc) rs,
                       row_number() over (partition by promotion_id order by score desc) rp from dedup),
  top as (select * from ranked where rs <= 4 and rp <= 2 and score >= 25 order by score desc limit 80)
  insert into public.product_picks (pick_date, item_key, promotion_id, rank, score, section, copy, reasons,
      name, brand, url, image_url, price, original_price, discount_rate, market_lowest, market_mall, vs_market_pct,
      source_id, source_name, channel_type, promotion_title, promotion_url, end_date, top_keyword, keyword_volume)
  select d, item_key, promotion_id, row_number() over (order by score desc), score,
    case when market_lowest > 0 and price <= market_lowest then 'web_low'
         when dleft between 0 and 3 then 'ending'
         when coalesce(dr,0) >= 50 then 'half'
         when price < 20000 then 'value'
         when vol >= 10000 then 'demand'
         else 'best' end,
    case when market_lowest > 0 and price < market_lowest then '웹 최저가보다 ' || to_char(market_lowest - price, 'FM999,999,999') || '원 싸요'
         when market_lowest > 0 and price = market_lowest then '웹 최저가와 같은 가격'
         when dleft = 0 then '오늘 마감, 놓치면 끝'
         when dleft between 1 and 3 then 'D-' || dleft || ' 마감 임박'
         when coalesce(dr,0) >= 50 then '정가보다 ' || dr || '% 싸게'
         when price < 20000 then to_char(price, 'FM999,999') || '원, 부담 없는 가격'
         when vol >= 10000 then '월 ' || to_char(vol, 'FM999,999') || '회 검색되는 ‘' || top_kw || '’'
         else '할인율·가격·수요를 따져 고른 상품' end,
    array_remove(array[
      case when coalesce(dr,0) > 0 then dr || '% 할인' end,
      case when market_lowest > 0 and price <= market_lowest then '웹 최저가 이하' end,
      case when cross_channels > 1 and price <= cross_lowest then cross_channels || '개 쇼핑몰 중 최저' end,
      case when dleft between 0 and 3 then case when dleft = 0 then '오늘 마감' else 'D-' || dleft end end,
      case when vol >= 1000 then '‘' || top_kw || '’ 월 ' || to_char(vol, 'FM999,999') || '회 검색' end
    ], null),
    cname, brand, url, image_url, price, case when dr is not null then original_price end, dr, market_lowest, market_mall, vs_market_pct,
    source_id, source_name, channel_type, ptitle, purl, pend, top_kw, vol
  from top;
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function private.refresh_picks_core() from public, anon, authenticated;

create or replace function public.refresh_picks(p_token text) returns int
language plpgsql security definer set search_path = public, extensions as $$
begin
  if not exists (select 1 from private.ingest_tokens
                 where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  return private.refresh_picks_core();
end $$;
revoke all on function public.refresh_picks(text) from public;
grant execute on function public.refresh_picks(text) to anon, authenticated;
