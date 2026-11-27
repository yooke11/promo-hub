-- 2026-11-27 대조 표본이 화면용 v_items(신뢰도 관문)에서만 뽑혀, 신뢰도 미달 채널은 다시 검증될 기회가 없었다.
-- 토큰이 있는 수집기만 쓰는 관문 없는 표본 RPC(표시용 아님). 틀린 가격으로 확인된 상품은 제외.
create or replace function public.verify_sample(p_token text, p_per_source int default 12)
returns table(item_key text, source_id text, url text, price int, original_price int)
language plpgsql security definer set search_path = public, extensions as $$
begin
  if not exists (select 1 from private.ingest_tokens
                 where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  return query
  select x.item_key, x.source_id, x.url, x.price, x.original_price from (
    select i.item_key, p.source_id, i.url, i.price, i.original_price,
           row_number() over (partition by p.source_id order by random()) rn
    from public.promotion_items i
    join public.promotions p on p.id = i.promotion_id
    join public.v_live_runs lr on lr.source_id = p.source_id
    where i.price > 0 and i.url like 'http%'
      and lr.last_good_run is not null and p.last_seen >= lr.last_good_run - interval '1 hour'
      and (p.end_date is null or p.end_date >= (now() at time zone 'Asia/Seoul')::date)
      and not exists (select 1 from public.wrong_prices wp where wp.item_key = i.item_key and wp.price = i.price)
  ) x where x.rn <= least(greatest(p_per_source, 1), 30);
end $$;
revoke all on function public.verify_sample(text, int) from public;
grant execute on function public.verify_sample(text, int) to anon, authenticated, service_role;
