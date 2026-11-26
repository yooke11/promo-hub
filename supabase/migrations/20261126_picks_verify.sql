-- 2026-11-26 정확도·속도 개선
-- 바꾸기 전 정의: supabase/migrations/20261125_verticals.sql 의 private.refresh_picks_for / refresh_picks_core (그대로 되돌릴 수 있음)
--
-- 1) 상품 페이지 대조 결과 테이블(price_verifications) + 기록 RPC(record_verifications, 수집 토큰 필요)
-- 2) 추천 계산 refresh_picks_for 에 strict 단계 추가(0 그대로, 1 불일치 제외, 2 일치 확인된 것만),
--    30시간 지난 웹 최저가 비교는 쓰지 않음, 적힌 할인율과 계산 할인율이 3%p 넘게 다르면 제외
-- 3) 분야별로 따로 호출하는 refresh_picks_v(토큰, 분야, 단계) — 한 번에 4개 분야를 계산하면 4.5초로
--    사이트용 3초 제한에 걸려 실패했다(2026-11-26 09:05 picks 잡 HTTP 500)

create table if not exists public.price_verifications (
  id bigserial primary key,
  item_key text not null,
  source_id text,
  kind text not null default 'pick',          -- pick(추천 상품) | sample(채널별 표본)
  url text,
  our_price int,
  our_original int,
  page_price int,                             -- 상품 페이지 구조화 데이터(JSON-LD·meta)의 가격
  status text not null,                       -- match | price_only | mismatch | not_found | blocked | error
  detail text,
  checked_at timestamptz not null default now()
);
create index if not exists ix_price_verif_item on public.price_verifications (item_key, checked_at desc);
create index if not exists ix_price_verif_time on public.price_verifications (checked_at desc);
alter table public.price_verifications enable row level security;   -- 정책 없음: 사이트(anon)에서는 읽지 못함
revoke all on public.price_verifications from anon, authenticated;

create or replace function public.record_verifications(p_token text, p_rows jsonb) returns int
language plpgsql security definer set search_path = public, extensions as $$
declare n int;
begin
  if not exists (select 1 from private.ingest_tokens
                 where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  insert into public.price_verifications (item_key, source_id, kind, url, our_price, our_original, page_price, status, detail)
  select r->>'item_key', r->>'source_id', coalesce(r->>'kind','pick'), r->>'url',
         (r->>'our_price')::int, (r->>'our_original')::int, (r->>'page_price')::int, r->>'status', left(r->>'detail', 500)
  from jsonb_array_elements(p_rows) r;
  get diagnostics n = row_count;
  delete from public.price_verifications where checked_at < now() - interval '30 days';
  return n;
end $$;
revoke all on function public.record_verifications(text, jsonb) from public;
grant execute on function public.record_verifications(text, jsonb) to anon, authenticated;

drop function if exists private.refresh_picks_for(text, text[], int, int, int, numeric);
create or replace function private.refresh_picks_for(v text, srcs text[], per_src int, per_promo int, lim int, min_score numeric, strict int default 0) returns int
language plpgsql security definer set search_path = public, extensions as $$
declare d date := (now() at time zone 'Asia/Seoul')::date; n int;
begin
  delete from public.product_picks where pick_date = d and vertical = v;   -- 같은 날 다시 돌리면 그 분야 오늘 것만 새로
  with live as (select id, title, url, end_date from public.v_promotions where status <> 'ended'),
  base0 as (
    select i.*, l.title ptitle, l.url purl, l.end_date pend,
           btrim(regexp_replace(regexp_replace(i.name, '^스크랩\s+', ''), '\s+\d[\d,]*\s*(원|\d+\s*%).*$', '')) cname,
           -- 할인율: 상품 페이지에서 정가가 확인되지 않은 상품(price_only)은 할인 표시를 하지 않는다
           case when coalesce(vf.status,'') = 'price_only' then null
                when coalesce(i.discount_rate, case when i.original_price > i.price then round(100.0*(i.original_price-i.price)/i.original_price)::int end) between 1 and 90
                then coalesce(i.discount_rate, round(100.0*(i.original_price-i.price)/i.original_price)::int) end dr,  -- 90% 초과는 정가 오인식으로 보고 쓰지 않음
           (l.end_date - d) dleft,
           -- 웹 최저가 비교는 30시간 안에 비교한 결과만 쓴다(오래된 비교로 '최저가' 문구를 만들지 않음)
           case when i.price_checked_at > now() - interval '30 hours' then i.market_lowest end ml,
           case when i.price_checked_at > now() - interval '30 hours' then i.vs_market_pct end vsm,
           case when i.price_checked_at > now() - interval '30 hours' then i.market_mall end mmall,
           vf.status vstatus
    from public.v_items i join live l on l.id = i.promotion_id
    left join lateral (select pv.status from public.price_verifications pv
                       where pv.item_key = i.item_key and pv.checked_at >= (d::timestamp at time zone 'Asia/Seoul')
                       order by pv.checked_at desc limit 1) vf on true
    where (srcs is null or i.source_id = any(srcs)) and i.price >= 1000 and coalesce(i.image_url,'') <> '' and coalesce(i.url,'') <> '' and i.url not like 'javascript:%'
      -- 적힌 할인율과 정가·판매가로 계산한 할인율이 3%p 넘게 다르면 숫자를 믿을 수 없어 제외
      and not (i.discount_rate is not null and i.original_price > i.price
               and abs(i.discount_rate - round(100.0*(i.original_price-i.price)/i.original_price)) > 2)
      -- 상품 페이지 대조(price_verifications): 1단계 = 불일치·가격 없음 제외, 2단계 = 일치 확인된 상품만
      and (strict < 1 or coalesce(vf.status,'') not in ('mismatch','not_found'))
      and (strict < 2 or vf.status in ('match','price_only'))
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
       + case when ml > 0 and price <= ml then 25
              when ml > 0 and vsm <= 5 then 10
              when ml > 0 and vsm > 15 then -15 else 0 end
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
    case when ml > 0 and price <= ml then 'web_low'
         when dleft between 0 and 3 then 'ending'
         when coalesce(dr,0) >= 50 then 'half'
         when price < 20000 then 'value'
         when vol >= 10000 then 'demand'
         else 'best' end,
    case when ml > 0 and price < ml then '웹 최저가보다 ' || to_char(ml - price, 'FM999,999,999') || '원 싸요'
         when ml > 0 and price = ml then '웹 최저가와 같은 가격'
         when dleft = 0 then '오늘 마감, 놓치면 끝'
         when dleft between 1 and 3 then 'D-' || dleft || ' 마감 임박'
         when coalesce(dr,0) >= 50 then '정가보다 ' || dr || '% 싸게'
         when price < 20000 then to_char(price, 'FM999,999') || '원, 부담 없는 가격'
         when vol >= 10000 then '월 ' || to_char(vol, 'FM999,999') || '회 검색되는 ‘' || top_kw || '’'
         else '할인율·가격·수요를 따져 고른 상품' end,
    array_remove(array[
      case when coalesce(dr,0) > 0 then dr || '% 할인' end,
      case when ml > 0 and price <= ml then '웹 최저가 이하' end,
      case when cross_channels > 1 and price <= cross_lowest then cross_channels || '개 쇼핑몰 중 최저' end,
      case when dleft between 0 and 3 then case when dleft = 0 then '오늘 마감' else 'D-' || dleft end end,
      case when vol >= 1000 then '‘' || top_kw || '’ 월 ' || to_char(vol, 'FM999,999') || '회 검색' end
    ], null),
    cname, brand, url, image_url, price, case when dr is not null then original_price end, dr, ml, mmall, vsm,
    source_id, source_name, channel_type, ptitle, purl, pend, top_kw, vol
  from top;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function private.refresh_picks_for(text, text[], int, int, int, numeric, int) from public, anon, authenticated;

create or replace function public.refresh_picks_v(p_token text, p_vertical text, p_strict int default 0) returns int
language plpgsql security definer set search_path = public, extensions as $$
declare d date := (now() at time zone 'Asia/Seoul')::date; s text[];
begin
  if not exists (select 1 from private.ingest_tokens
                 where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  if p_vertical = 'all' then
    delete from public.product_picks where pick_date < d - 14;
    return private.refresh_picks_for('all', null, 4, 2, 80, 25, p_strict);
  end if;
  select array_agg(source_id) into s from public.source_verticals where vertical = p_vertical;
  if s is null then return 0; end if;
  return private.refresh_picks_for(p_vertical, s, 8, 3, 60, 10, p_strict);
end $$;
revoke all on function public.refresh_picks_v(text, text, int) from public;
grant execute on function public.refresh_picks_v(text, text, int) to anon, authenticated;
