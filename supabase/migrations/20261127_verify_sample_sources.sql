-- 2026-11-27 verify_sample: 특정 채널만(p_sources) 지정하면 채널당 최대 400개까지 — 수집을 다시 돌리지 않고 화면 상품을 바로 전수 확인.
drop function if exists public.verify_sample(text, int);
create or replace function public.verify_sample(p_token text, p_per_source int default 12, p_sources text[] default null)
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
      and (p_sources is null or p.source_id = any(p_sources))
      and lr.last_good_run is not null and p.last_seen >= lr.last_good_run - interval '1 hour'
      and (p.end_date is null or p.end_date >= (now() at time zone 'Asia/Seoul')::date)
      and not exists (select 1 from public.wrong_prices wp where wp.item_key = i.item_key and wp.price = i.price)
  ) x where x.rn <= least(greatest(p_per_source, 1), case when p_sources is null then 30 else 400 end);
end $$;
revoke all on function public.verify_sample(text, int, text[]) from public;
grant execute on function public.verify_sample(text, int, text[]) to anon, authenticated, service_role;
