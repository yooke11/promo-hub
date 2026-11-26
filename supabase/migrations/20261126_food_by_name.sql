-- 6차(2026-11-26): 장보기픽은 상품명으로 식품이 확인된 상품만(쇼핑몰 대표 분류를 물려받은 상품 제외)
-- classify_product: 생활·주방에 퍼실|피죤|다우니|페브리즈|샤프란|락스|파워젤|세탁|표백|캡슐 세제|식기 세척|섬유 탈취 추가(config/category_rules.json)
-- 6차: 장보기픽은 '상품명으로 식품이 확인된' 상품만(쇼핑몰 대표 분류를 물려받은 상품은 제외) — 식품몰의 세제(퍼실 등)가 섞이던 문제
alter table public.promotion_items add column if not exists category_by_name boolean not null default false;

create or replace function private.set_item_category() returns trigger
language plpgsql security definer set search_path = public as $$
declare t text; v text; dflt text; c text;
begin
  select p.title, sv.vertical, sd.category into t, v, dflt
  from public.promotions p
  left join public.source_verticals sv on sv.source_id = p.source_id
  left join public.source_default_category sd on sd.source_id = p.source_id
  where p.id = new.promotion_id limit 1;
  c := public.classify_product(new.name, public.classify_product(t));
  new.category_by_name := c is not null;
  new.category := coalesce(c, dflt, case v when 'fashion' then '패션' when 'beauty' then '뷰티' end, '기타');
  return new;
end $$;

update public.promotion_items i
set category = coalesce(c.cat, i.category), category_by_name = c.cat is not null
from (select i2.promotion_id, i2.item_key, public.classify_product(i2.name, public.classify_product(p.title)) cat
      from public.promotion_items i2 join public.promotions p on p.id = i2.promotion_id) c
where c.promotion_id = i.promotion_id and c.item_key = i.item_key
  and (i.category_by_name is distinct from (c.cat is not null) or (c.cat is not null and i.category is distinct from c.cat));

-- v_items 끝에 category_by_name 추가
do $$
declare d text := pg_get_viewdef('public.v_items'::regclass, true);
begin
  if position('category_by_name' in d) = 0 then
    d := replace(d, 'COALESCE(i.category, p.category) AS category,', 'COALESCE(i.category, p.category) AS category, i.category_by_name,');
    d := replace(d, E'\n   FROM base b\n', E',\n    b.category_by_name\n   FROM base b\n');
    if position('b.category_by_name' in d) = 0 then raise exception 'v_items anchor'; end if;
    execute 'create or replace view public.v_items with (security_invoker = true) as ' || d;
  end if;
end $$;

-- 장보기 기획전 목록
do $$
declare d text := pg_get_viewdef('public.v_promotions'::regclass, true);
  f text := ' i2.category = ''식품'' AND i2.category_by_name AND i2.price IS NOT NULL AND i2.name !~* ''^(장바구니(\s*담기)?|재입고(\s*(신청|알림))?)$'' AND i2.name !~ ''\*{2,}\s*고객님'' AND';
begin
  d := replace(d, 'WHERE i2.promotion_id = p.id AND', 'WHERE i2.promotion_id = p.id AND' || f);
  d := replace(d, 'WHERE i.promotion_id = p.id AND', 'WHERE i.promotion_id = p.id AND' || replace(f, 'i2.', 'i.'));
  d := replace(d, 'WHERE lr.last_good_run IS NOT NULL', 'WHERE (COALESCE(agg.item_count, 0) > 0 OR p.category = ''식품'') AND lr.last_good_run IS NOT NULL');
  execute 'create or replace view public.v_promotions_food with (security_invoker = true) as ' || d;
end $$;
grant select on public.v_promotions_food to anon, authenticated;

-- 장보기 추천
do $$
declare d text := pg_get_functiondef('private.refresh_picks_for(text,text[],int,int,int,numeric,int)'::regprocedure);
begin
  if position('b.category_by_name' in d) = 0 then
    d := replace(d, '(v <> ''food'' or b.category = ''식품'')', '(v <> ''food'' or (b.category = ''식품'' and b.category_by_name))');
    if position('b.category_by_name' in d) = 0 then raise exception 'picks anchor'; end if;
    execute d;
  end if;
end $$;
