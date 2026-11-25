-- 2026-11-25 분야별 페이지(식품·장보기 / 패션 / 뷰티): 채널-분야 연결표와 분야별 추천 상품.
create table if not exists public.source_verticals (
  vertical  text not null,      -- food | fashion | beauty
  source_id text not null references public.sources(id) on delete cascade,
  primary key (vertical, source_id)
);
alter table public.source_verticals enable row level security;
drop policy if exists sv_read on public.source_verticals;
create policy sv_read on public.source_verticals for select to anon, authenticated using (true);
grant select on public.source_verticals to anon, authenticated;

alter table public.product_picks add column if not exists vertical text not null default 'all';
alter table public.product_picks drop constraint if exists product_picks_pkey;
alter table public.product_picks add primary key (pick_date, vertical, item_key);

drop view if exists public.v_picks;
create view public.v_picks with (security_invoker = true) as
  select * from public.product_picks
  where pick_date = (select max(pick_date) from public.product_picks)
  order by vertical, rank;
grant select on public.v_picks to anon, authenticated;

create or replace function private.refresh_picks_for(v text, srcs text[], per_src int, per_promo int, lim int, min_score numeric) returns int
language plpgsql security definer set search_path = public, extensions as $$
declare d date := (now() at time zone 'Asia/Seoul')::date; n int;
begin
  delete from public.product_picks where pick_date = d and vertical = v;   -- 같은 날 다시 돌리면 그 분야 오늘 것만 새로
  with live as (select id, title, url, end_date from public.v_promotions where status <> 'ended'),
  base0 as (
    select i.*, l.title ptitle, l.url purl, l.end_date pend,
           btrim(regexp_replace(regexp_replace(i.name, '^스크랩\s+', ''), '\s+\d[\d,]*\s*(원|\d+\s*%).*$', '')) cname,
           case when coalesce(i.discount_rate, case when i.original_price > i.price then round(100.0*(i.original_price-i.price)/i.original_price)::int end) between 1 and 90
                then coalesce(i.discount_rate, round(100.0*(i.original_price-i.price)/i.original_price)::int) end dr,  -- 90% 초과는 정가 오인식으로 보고 쓰지 않음
           (l.end_date - d) dleft
    from public.v_items i join live l on l.id = i.promotion_id
    where (srcs is null or i.source_id = any(srcs)) and i.price >= 1000 and coalesce(i.image_url,'') <> '' and coalesce(i.url,'') <> '' and i.url not like 'javascript:%'
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
  top as (select * from ranked where rs <= per_src and rp <= per_promo and score >= min_score order by score desc limit lim)
  insert into public.product_picks (pick_date, vertical, item_key, promotion_id, rank, score, section, copy, reasons,
      name, brand, url, image_url, price, original_price, discount_rate, market_lowest, market_mall, vs_market_pct,
      source_id, source_name, channel_type, promotion_title, promotion_url, end_date, top_keyword, keyword_volume)
  select d, v, item_key, promotion_id, row_number() over (order by score desc), score,
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
revoke all on function private.refresh_picks_for(text, text[], int, int, int, numeric) from public, anon, authenticated;

-- 전체 추천(쇼핑몰당 4·기획전당 2·80개) + 분야별 추천(쇼핑몰당 6·기획전당 3·60개, 기준 점수 15)
create or replace function private.refresh_picks_core() returns int
language plpgsql security definer set search_path = public, extensions as $$
declare d date := (now() at time zone 'Asia/Seoul')::date; n int; r record;
begin
  delete from public.product_picks where pick_date < d - 14;
  n := private.refresh_picks_for('all', null, 4, 2, 80, 25);
  for r in select vertical, array_agg(source_id) srcs from public.source_verticals group by vertical loop
    n := n + private.refresh_picks_for(r.vertical, r.srcs, 6, 3, 60, 15);
  end loop;
  return n;
end $$;
revoke all on function private.refresh_picks_core() from public, anon, authenticated;

insert into public.source_verticals (vertical, source_id)
select v, s from (values
  ('food','cjthemarket'),('food','dongwonmall'),('food','otokimall'),('food','kurly'),('food','oasis'),('food','homeplus'),('food','costco'),
  ('fashion','nike'),('fashion','29cm'),('fashion','kolonmall'),('fashion','brandi'),('fashion','fashionplus'),('fashion','northface'),
  ('beauty','innisfree')) x(v, s)
where exists (select 1 from public.sources where id = s)
on conflict do nothing;

-- 2026-11-25 시험 수집 결과 반영: 뷰티는 주요 몰(올리브영·아모레몰·시코르 등)이 수집 금지·차단이라 보류하고 가전·디지털로 대체
delete from public.source_verticals where vertical='beauty';
insert into public.source_verticals (vertical, source_id)
select v, s from (values ('food','choroc'),('food','harimmall'),('food','epost'),('food','nongshimmall'),
  ('fashion','mlbkorea'),('fashion','discovery'),
  ('digital','samsung'),('digital','lge'),('digital','himart'),('digital','dyson'),('digital','danawa')) x(v,s)
where exists (select 1 from public.sources where id=s) on conflict do nothing;

-- 2026-11-25 가전·디지털 분야 삭제, 뷰티(뷰티세일픽) 6곳 추가, 분야별 추천 기준 완화(쇼핑몰당 8·기준 10점)
delete from public.source_verticals where vertical='digital';
insert into public.source_verticals (vertical, source_id)
select 'beauty', s from unnest(array['innisfree','isoi','cellfusionc','clubclio','skinfood','banilaco']) s
where exists (select 1 from public.sources where id=s) on conflict do nothing;
-- refresh_picks_core: refresh_picks_for(r.vertical, r.srcs, 8, 3, 60, 10)
