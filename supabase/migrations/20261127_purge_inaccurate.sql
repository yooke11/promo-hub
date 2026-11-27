-- 2026-11-27 운영자 원칙: "정확하지 않다고 판단되는 데이터는 무조건 삭제, 잘못된 정보 노출은 절대 금지".
-- 매일 수집 → 상품 페이지 가격 대조 뒤 이 함수가 확인되지 않은 숫자와 상품이 아닌 항목을 지운다(다음 날 수집되면 다시 대조→삭제).

-- 쇼핑몰별 신뢰 등급(최근 3일 상품 페이지 대조 기준)
--  ok    : 대조 10건 이상, 불일치 2% 이하, 확인 불가 10% 이하 → 가격·할인율 표시
--  price : 위 조건이지만 '가격만 일치'(정가·할인율 확인 안 됨) 10% 초과 → 가격만, 정가·할인율 삭제
--  bad   : 그 외(불일치·확인 불가가 많거나 대조 10건 미만) → 가격 숫자 삭제
create table if not exists public.source_trust (
  source_id text primary key,
  level text not null check (level in ('ok','price','bad')),
  checks int not null, mismatch int not null, not_found int not null, price_only int not null,
  reason text,
  updated_at timestamptz not null default now()
);
alter table public.source_trust enable row level security;
create policy source_trust_read on public.source_trust for select to anon, authenticated using (true);
grant select on public.source_trust to anon, authenticated;

create or replace function private.purge_inaccurate(p_step int default 0) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r jsonb := '{}'::jsonb; n int; today date := (now() at time zone 'Asia/Seoul')::date;
begin
  -- p_step: 0 전부, 1 신뢰 등급·상품 아닌 항목·틀린 가격, 2 미확인 쇼핑몰 상품, 3 정가·할인율·최대 할인·오래된 비교·가격 기록
  if p_step in (0, 1) then
  -- 1) 쇼핑몰 신뢰 등급
  delete from public.source_trust where true;
  insert into public.source_trust (source_id, level, checks, mismatch, not_found, price_only, reason)
  select l.source_id,
    case when coalesce(v.n,0) < 10 then 'bad'
         when v.mm::numeric / v.n > 0.02 then 'bad'
         when v.nf::numeric / v.n > 0.10 then 'bad'
         when v.po::numeric / v.n > 0.10 then 'price'
         else 'ok' end,
    coalesce(v.n,0), coalesce(v.mm,0), coalesce(v.nf,0), coalesce(v.po,0),
    case when coalesce(v.n,0) < 10 then '대조 ' || coalesce(v.n,0) || '건(10건 미만)'
         when v.mm::numeric / v.n > 0.02 then '불일치 ' || v.mm || '/' || v.n
         when v.nf::numeric / v.n > 0.10 then '확인 불가 ' || v.nf || '/' || v.n
         when v.po::numeric / v.n > 0.10 then '정가 확인 안 됨 ' || v.po || '/' || v.n end
  from (select distinct p.source_id from public.promotions p join public.promotion_items i on i.promotion_id = p.id) l
  left join (
    select source_id, count(*) n,
           count(*) filter (where status = 'mismatch') mm, count(*) filter (where status = 'not_found') nf, count(*) filter (where status = 'price_only') po
    from public.price_verifications
    where checked_at > now() - interval '3 days' and status <> 'blocked'
    group by source_id) v on v.source_id = l.source_id;

  -- 2) 상품이 아닌 항목(가격 없는 배너·메뉴·안내 문구·UI 글자·리뷰 글) 삭제
  delete from public.promotion_items i
  where i.price is null or i.price <= 0
     or i.name ~* '^(장바구니(\s*담기)?|재입고(\s*(신청|알림))?|품절|더보기|자세히 ?보기|바로가기|구매하기)$'
     or i.name ~ '\*{2,}\s*고객님' or i.name ~ '(검색어가 없습니다|신고해주신 내용|로그인이 필요|쿠키를 사용)'
     or length(regexp_replace(i.name, '\s', '', 'g')) < 2;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_not_products', n);

  -- 3) 말이 안 되는 가격(100원 미만, 1억 원 초과) 상품 삭제
  delete from public.promotion_items where price < 100 or price > 100000000;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_absurd_price', n);

  -- 4) 상품 페이지와 대조해 틀린(또는 가격을 찾을 수 없던) 그 가격 그대로인 상품 삭제
  delete from public.promotion_items i
  using (select distinct on (item_key) item_key, status, our_price from public.price_verifications
         where checked_at > now() - interval '3 days' and status in ('match','price_only','mismatch','not_found')
         order by item_key, checked_at desc) v
  where v.item_key = i.item_key and v.status in ('mismatch','not_found') and i.price = v.our_price;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_verified_wrong', n);
  end if;
  if p_step in (0, 2) then

  -- 5) 신뢰 등급 bad 쇼핑몰: 확인되지 않은 가격 숫자를 가진 상품 삭제(그 상품 자체가 대조에서 맞은 경우는 남김)
  delete from public.promotion_items i
  using public.promotions p, public.source_trust t
  where p.id = i.promotion_id and t.source_id = p.source_id and t.level = 'bad'
    and not exists (select 1 from public.price_verifications v where v.item_key = i.item_key and v.status = 'match'
                    and v.our_price = i.price and v.checked_at > now() - interval '3 days');
  get diagnostics n = row_count; r := r || jsonb_build_object('items_untrusted_source', n);
  end if;
  if p_step in (0, 3) then

  -- 6) 정가·할인율이 확인되지 않은 것: price 등급 쇼핑몰, '가격만 일치' 상품, 할인율 계산이 안 맞는 상품 → 정가·할인율만 삭제
  update public.promotion_items i set original_price = null, discount_rate = null
  from public.promotions p, public.source_trust t
  where p.id = i.promotion_id and t.source_id = p.source_id and t.level = 'price'
    and (i.original_price is not null or i.discount_rate is not null)
    and not exists (select 1 from public.price_verifications v where v.item_key = i.item_key and v.status = 'match'
                    and v.our_price = i.price and v.checked_at > now() - interval '3 days');
  get diagnostics n = row_count; r := r || jsonb_build_object('discount_unverified_source', n);
  update public.promotion_items i set original_price = null, discount_rate = null
  from (select distinct on (item_key) item_key, status, our_price from public.price_verifications
        where checked_at > now() - interval '3 days' and status in ('match','price_only','mismatch','not_found')
        order by item_key, checked_at desc) v
  where v.item_key = i.item_key and v.status = 'price_only' and i.price = v.our_price
    and (i.original_price is not null or i.discount_rate is not null);
  get diagnostics n = row_count; r := r || jsonb_build_object('discount_price_only', n);
  update public.promotion_items set original_price = null, discount_rate = null
  where (original_price is not null and original_price <= price)
     or (discount_rate is not null and (discount_rate <= 0 or discount_rate >= 95))
     or (discount_rate is not null and original_price > price and abs(discount_rate - round(100.0 * (original_price - price) / original_price)) > 2)
     or (discount_rate is not null and original_price is null);
  get diagnostics n = row_count; r := r || jsonb_build_object('discount_math_wrong', n);

  -- 7) 기획전 '최대 N%': 확인된(ok) 쇼핑몰이 아니면 기획전 제목·설명에 그 숫자가 직접 적힌 경우만 남김
  update public.promotions p set max_discount = null
  from public.source_trust t
  where t.source_id = p.source_id and t.level <> 'ok' and p.max_discount is not null
    and coalesce(p.title, '') || ' ' || coalesce(p.description, '') !~ (p.max_discount::text || '\s*%');
  get diagnostics n = row_count; r := r || jsonb_build_object('promo_max_discount', n);

  -- 8) 30시간 넘은 웹 최저가 비교는 지금 가격이 아니므로 삭제
  delete from public.price_checks where checked_at < now() - interval '30 hours';
  get diagnostics n = row_count; r := r || jsonb_build_object('stale_market_prices', n);

  -- 9) 오늘 가격 기록 중 지금 남아 있지 않은 가격(위에서 지운 것)은 기록에서도 삭제
  delete from public.price_history h
  where h.d = today and not exists (select 1 from public.promotion_items i where hashtextextended(i.item_key, 0) = h.k and i.price = h.price);
  get diagnostics n = row_count; r := r || jsonb_build_object('price_history_today_removed', n);
  end if;

  return r || jsonb_build_object('trust', (select jsonb_object_agg(level, c) from (select level, count(*) c from public.source_trust group by 1) x));
end $$;
revoke all on function private.purge_inaccurate(int) from public, anon, authenticated;

-- 매일 picks 잡이 토큰으로 호출(가격 대조 뒤, 추천 계산 앞)
create or replace function public.purge_inaccurate(p_token text, p_step int default 0) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
begin
  if not exists (select 1 from private.ingest_tokens where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
    return private.purge_inaccurate(p_step);
end $$;
revoke all on function public.purge_inaccurate(text, int) from public;
grant execute on function public.purge_inaccurate(text, int) to anon, authenticated;

-- 사이트의 이중 안전장치: bad 쇼핑몰은 숫자 숨김, price 쇼핑몰은 정가·할인율 숨김
create or replace function public.price_trust() returns jsonb
language sql stable security definer set search_path = public as $$
  with today as (
    select distinct on (item_key) item_key, source_id, kind, status, url, our_price from public.price_verifications
    where checked_at > now() - interval '3 days' and status in ('match','price_only','mismatch','not_found')
    order by item_key, checked_at desc)
  select jsonb_build_object(
    'low_sources', coalesce((select jsonb_agg(source_id) from public.source_trust where level = 'bad'), '[]'::jsonb),
    'price_only_sources', coalesce((select jsonb_agg(source_id) from public.source_trust where level = 'price'), '[]'::jsonb),
    'bad_urls', coalesce((select jsonb_agg(url) from today where status in ('mismatch','not_found')), '[]'::jsonb))
$$;
