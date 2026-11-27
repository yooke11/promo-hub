-- 2026-11-28 삭제 기준 보강(더 엄격하게): 상품명 자리에 홍보 문구가 잡힌 항목은 어떤 상품인지 알 수 없어 삭제.
--  예) 동원몰 '황다랑어를 사용해 더욱 쫄깃하고 담백한 참치!' 27,800원, 아이소이 '거뭇한 잡티 집중저격!' 23,400원,
--      오아시스 '한우 육향이 가득한 … 깔끔한 맛', 메디큐브 '블프 신규회원 첫구매 혜택!' 5,900원, 동원몰 '+ 카무트 현미밥 …'(앞이 잘린 이름)
--  기준: 이름이 + & , / 로 시작하거나, 용량·수량 표기 없이 문장형 어미(! ? ~ 세요 네요 해요 니다 …는 …한 맛 / 최대 N% 할인)로 끝남.
--  책·디자인 문구 채널(yes24, kyobobook, 10x10)은 실제 상품명이 문장형이라 제외.
CREATE OR REPLACE FUNCTION private.purge_inaccurate(p_step integer DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare r jsonb := '{}'::jsonb; n int; today date := (now() at time zone 'Asia/Seoul')::date;
begin
  if p_step in (0, 1) then
  delete from public.verified_prices where true;
  delete from public.wrong_prices where true;
  insert into public.wrong_prices (item_key, price)
    select item_key, our_price from (select distinct on (item_key) item_key, status, our_price from public.price_verifications
      where checked_at > now() - interval '3 days' and status in ('match','price_only','mismatch','not_found') order by item_key, checked_at desc) v
    where status in ('mismatch','not_found') and our_price is not null on conflict do nothing;
  insert into public.verified_prices (item_key, price)
    select distinct item_key, our_price from public.price_verifications
    where status = 'match' and our_price is not null and checked_at > now() - interval '3 days'
    on conflict do nothing;
  -- 최근 수집에서 다시 확인되지 않은 상품(기획전은 다시 보였는데 상품은 빠짐)은 가격이 지금과 다를 수 있어 삭제
  delete from public.promotion_items i using public.promotions p
   where p.id = i.promotion_id and i.last_seen < p.last_seen - interval '1 hour';
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
      and checked_at > coalesce((select ts.since from private.trust_since ts where ts.source_id = price_verifications.source_id), '-infinity')
    group by source_id) v on v.source_id = l.source_id;

  delete from public.promotion_items i
  where i.price is null or i.price <= 0
     or i.name ~* '^(장바구니(\s*담기)?|재입고(\s*(신청|알림))?|품절|더보기|자세히 ?보기|바로가기|구매하기)$'
     or i.name ~ '\*{2,}\s*고객님' or i.name ~ '(검색어가 없습니다|신고해주신 내용|로그인이 필요|쿠키를 사용)'
     or length(regexp_replace(i.name, '\s', '', 'g')) < 2;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_not_products', n);

  delete from public.promotion_items i using public.promotions p
  where p.id = i.promotion_id and p.source_id not in ('yes24', 'kyobobook', '10x10')
    and (i.name ~ '^\s*[+&,/]'
         or (i.name ~ '(!|\?|~|세요|네요|해요|예요|어요|아요|니다|는|[한운은] 맛|최대\s*\d+\s*%\s*할인)\s*$'
             and i.name !~* '\d\s*(g|kg|mg|ml|l|개|입|정|포|매|팩|ea|박스|세트|캡슐|병|캔|봉|구|인분|롤|켤레|족|장)'));
  get diagnostics n = row_count; r := r || jsonb_build_object('items_copy_names', n);

  delete from public.promotion_items where price < 100 or price > 100000000;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_absurd_price', n);

  delete from public.promotion_items i
  using (select distinct on (item_key) item_key, status, our_price from public.price_verifications
         where checked_at > now() - interval '3 days' and status in ('match','price_only','mismatch','not_found')
         order by item_key, checked_at desc) v
  where v.item_key = i.item_key and v.status in ('mismatch','not_found') and i.price = v.our_price;
  get diagnostics n = row_count; r := r || jsonb_build_object('items_verified_wrong', n);
  end if;
  if p_step in (0, 2) then

  delete from public.promotion_items i
  using public.promotions p, public.source_trust t
  where p.id = i.promotion_id and t.source_id = p.source_id and t.level = 'bad'
    and not exists (select 1 from public.price_verifications v where v.item_key = i.item_key and v.status = 'match'
                    and v.our_price = i.price and v.checked_at > now() - interval '3 days');
  get diagnostics n = row_count; r := r || jsonb_build_object('items_untrusted_source', n);
  end if;
  if p_step in (0, 3) then

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

  update public.promotions p set max_discount = null
  from public.source_trust t
  where t.source_id = p.source_id and t.level <> 'ok' and p.max_discount is not null
    and coalesce(p.title, '') || ' ' || coalesce(p.description, '') !~ (p.max_discount::text || '\s*%');
  get diagnostics n = row_count; r := r || jsonb_build_object('promo_max_discount', n);

  delete from public.price_checks where checked_at < now() - interval '30 hours';
  get diagnostics n = row_count; r := r || jsonb_build_object('stale_market_prices', n);

  delete from public.price_history h
  where h.d = today and not exists (select 1 from public.promotion_items i where hashtextextended(i.item_key, 0) = h.k and i.price = h.price);
  get diagnostics n = row_count; r := r || jsonb_build_object('price_history_today_removed', n);
  end if;

  return r || jsonb_build_object('trust', (select jsonb_object_agg(level, c) from (select level, count(*) c from public.source_trust group by 1) x));
end $function$;
