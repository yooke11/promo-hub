-- 찜 + 알림(2026-11-26): 로그인 없이 브라우저 알림(웹 푸시) 구독과 찜 목록만 저장. 개인정보(이름·전화·이메일) 없음.
-- 표는 RLS 로 막고(정책 없음) 함수로만 읽고 쓴다. 구독 주소(endpoint)가 곧 본인 확인 값이다.
create table if not exists public.push_subs (
  id bigserial primary key,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  vertical text,
  created_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);
create table if not exists public.push_watch (
  sub_id bigint not null references public.push_subs(id) on delete cascade,
  item_key text not null,
  name text, url text, image_url text, source_name text,
  base_price int,            -- 찜할 때 가격(DB 기준)
  last_price int,            -- 마지막으로 알린 가격
  notified_end date,         -- 마감 알림을 보낸 기획전 마감일
  created_at timestamptz not null default now(),
  primary key (sub_id, item_key)
);
alter table public.push_subs enable row level security;
alter table public.push_watch enable row level security;

-- 브라우저가 호출: 구독 정보 + 찜 목록(최대 200개)을 통째로 맞춘다
create or replace function public.push_save(p_endpoint text, p_p256dh text, p_auth text, p_vertical text, p_items jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare sid bigint; n int;
begin
  if p_endpoint is null or p_endpoint !~ '^https://' or length(p_endpoint) > 1000
     or coalesce(length(p_p256dh), 0) not between 20 and 200 or coalesce(length(p_auth), 0) not between 8 and 100 then
    raise exception 'bad subscription' using errcode = '22023';
  end if;
  if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) > 200 then
    raise exception 'too many items' using errcode = '22023';
  end if;
  insert into public.push_subs (endpoint, p256dh, auth, vertical) values (p_endpoint, p_p256dh, p_auth, left(p_vertical, 20))
  on conflict (endpoint) do update set p256dh = excluded.p256dh, auth = excluded.auth, vertical = excluded.vertical, last_seen = now()
  returning id into sid;
  delete from public.push_watch w where w.sub_id = sid
    and not exists (select 1 from jsonb_array_elements(p_items) x where x->>'item_key' = w.item_key);
  insert into public.push_watch (sub_id, item_key, name, url, image_url, source_name, base_price, last_price)
  select sid, left(x->>'item_key', 500), left(x->>'name', 200), left(x->>'url', 1000), left(x->>'image_url', 1000), left(x->>'source_name', 60),
         cur.price, cur.price
  from jsonb_array_elements(p_items) x
  left join lateral (select min(i.price)::int price from public.promotion_items i where i.item_key = x->>'item_key' and i.price > 0) cur on true
  where coalesce(x->>'item_key', '') <> ''
  on conflict (sub_id, item_key) do nothing;
  select count(*) into n from public.push_watch where sub_id = sid;
  return jsonb_build_object('ok', true, 'watching', n);
end $$;

create or replace function public.push_delete(p_endpoint text) returns void
language sql security definer set search_path = public as $$
  delete from public.push_subs where endpoint = p_endpoint;
$$;

-- 매일 수집 뒤(토큰 필요): 보낼 알림 — 찜한 뒤(또는 마지막 알림 뒤) 가격이 내렸거나, 담긴 기획전이 내일 끝나는 상품
-- 가격 대조에서 틀린 것으로 나온 상품·채널(price_trust)은 가격 알림에서 뺀다
create or replace function public.push_due(p_token text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare tr jsonb; low text[]; bad text[]; out jsonb;
begin
  if not exists (select 1 from private.ingest_tokens where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  tr := public.price_trust();
  low := array(select jsonb_array_elements_text(coalesce(tr->'low_sources', '[]')));
  bad := array(select jsonb_array_elements_text(coalesce(tr->'bad_urls', '[]')));
  with live as (
    select v.item_key, min(v.price) price, min(v.end_date) end_date,
           bool_or(v.source_id = any(low) or v.url = any(bad)) untrusted
    from public.v_items v
    where v.item_key in (select distinct item_key from public.push_watch) and v.price > 0
    group by v.item_key
  ), due as (
    select s.id sub_id, s.endpoint, s.p256dh, s.auth, w.item_key, w.name, w.url, w.image_url, w.source_name,
           l.price, coalesce(w.last_price, w.base_price) prev, l.end_date,
           case when not l.untrusted and coalesce(w.last_price, w.base_price) > l.price then 'drop'
                when l.end_date = (now() at time zone 'Asia/Seoul')::date + 1 and w.notified_end is distinct from l.end_date then 'ending' end kind
    from public.push_watch w join public.push_subs s on s.id = w.sub_id join live l on l.item_key = w.item_key
  )
  select coalesce(jsonb_agg(to_jsonb(due)), '[]') into out from due where kind is not null;
  return out;
end $$;

-- 보낸 결과 기록: 보낸 알림(가격·마감일 갱신), 만료된 구독(브라우저가 거절 410/404) 삭제
create or replace function public.push_done(p_token text, p_sent jsonb, p_gone bigint[]) returns void
language plpgsql security definer set search_path = public, extensions as $$
begin
  if not exists (select 1 from private.ingest_tokens where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')) then
    raise exception 'invalid ingest token' using errcode = '28000';
  end if;
  update public.push_watch w set
    last_price = case when x->>'kind' = 'drop' then (x->>'price')::int else w.last_price end,
    notified_end = case when x->>'kind' = 'ending' then (x->>'end_date')::date else w.notified_end end
  from jsonb_array_elements(coalesce(p_sent, '[]')) x
  where w.sub_id = (x->>'sub_id')::bigint and w.item_key = x->>'item_key';
  delete from public.push_subs where id = any(coalesce(p_gone, '{}'));
  -- 90일 넘게 다시 열지 않은 구독은 정리
  delete from public.push_subs where last_seen < now() - interval '90 days';
end $$;

revoke all on function public.push_save(text,text,text,text,jsonb), public.push_delete(text), public.push_due(text), public.push_done(text,jsonb,bigint[]) from public;
grant execute on function public.push_save(text,text,text,text,jsonb), public.push_delete(text) to anon, authenticated;
grant execute on function public.push_due(text), public.push_done(text,jsonb,bigint[]) to anon, authenticated;
