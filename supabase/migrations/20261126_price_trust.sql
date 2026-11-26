-- 2026-11-26 상품 페이지 대조 요약(health)과 사이트용 가격 신뢰 정보
create or replace function public.verify_summary() returns table(source_id text, kind text, total int, match int, price_only int, mismatch int, not_found int, blocked int, examples text)
language sql security definer set search_path = public as $$
  with today as (
    select distinct on (item_key) * from public.price_verifications
    where checked_at >= ((now() at time zone 'Asia/Seoul')::date::timestamp at time zone 'Asia/Seoul')
    order by item_key, checked_at desc)
  select source_id, kind, count(*)::int,
         count(*) filter (where status='match')::int, count(*) filter (where status='price_only')::int,
         count(*) filter (where status='mismatch')::int, count(*) filter (where status='not_found')::int,
         count(*) filter (where status in ('blocked','error'))::int,
         string_agg(case when status='mismatch' then our_price || '→' || coalesce(page_price::text,'?') end, ', ')
  from today group by 1, 2 order by 6 desc, 1
$$;
revoke all on function public.verify_summary() from public;
grant execute on function public.verify_summary() to anon, authenticated;

-- 사이트가 숫자를 숨길 대상: (1) 대조에서 불일치·가격 없음으로 나온 상품 주소
-- (2) 채널 표본 중 20% 이상이 불일치인 채널(그 채널 가격 읽기 규칙이 틀림) — 규칙을 고치기 전까지 숨김
create or replace function public.price_trust() returns jsonb
language sql stable security definer set search_path = public as $$
  with today as (
    select distinct on (item_key) item_key, source_id, kind, status, url from public.price_verifications
    where checked_at >= ((now() at time zone 'Asia/Seoul')::date::timestamp at time zone 'Asia/Seoul') - interval '1 day'
    order by item_key, checked_at desc),
  src as (
    select source_id from today where kind = 'sample' and status not in ('blocked','error')
    group by source_id
    having count(*) >= 3 and count(*) filter (where status = 'mismatch') >= greatest(1, ceil(count(*) * 0.2)))
  select jsonb_build_object(
    'low_sources', coalesce((select jsonb_agg(source_id) from src), '[]'::jsonb),
    'bad_urls', coalesce((select jsonb_agg(url) from today where status in ('mismatch','not_found')), '[]'::jsonb))
$$;
revoke all on function public.price_trust() from public;
grant execute on function public.price_trust() to anon, authenticated;
