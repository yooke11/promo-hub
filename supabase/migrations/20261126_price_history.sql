-- 가격 기록 + 단위 가격 화면 연결 + 찜 알림 키(2026-11-26). 실제 적용한 SQL 과 같은 내용.
-- (1) 가격 기록: 바뀐 날만 한 줄, 60일 보관 → 무료 요금제에서 수 MB 수준
create table if not exists public.price_history (k bigint not null, d date not null, price int not null, primary key (k, d));
alter table public.price_history enable row level security;
create index if not exists ix_price_history_k_d on public.price_history (k, d desc);
create table if not exists public.price_lows (k bigint primary key, low_days int not null, prev_min int not null, updated_at timestamptz not null default now());
alter table public.price_lows enable row level security;
create policy price_lows_read on public.price_lows for select to anon, authenticated using (true);
grant select on public.price_lows to anon, authenticated;
-- public.record_prices(p_token): 수집 토큰 확인 → 오늘 보이는 상품 가격(상품별 최저)을 마지막 기록과 다를 때만 기록,
--   60일 지난 기록 삭제, price_lows 재계산(기록 14일 이상 + 최근 30일 중 지금보다 비쌌던 때가 있고 지금이 최저인 상품).
--   본문은 DB 함수 정의(pg_get_functiondef('public.record_prices(text)')) 참고. 매일 picks 잡 시작 때 호출.

-- (2) 단위 가격: promotion_items.unit_basis/unit_total/unit_word(트리거 trg_item_unit, parse_unit) → v_items 끝에
--   unit_basis, unit_total, unit_word(base), low_days, prev_min, unit_price, unit_label, unit_price_100
alter table public.promotion_items add column if not exists unit_basis text, add column if not exists unit_total numeric, add column if not exists unit_word text;
create or replace function private.set_item_unit() returns trigger
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  r := public.parse_unit(new.name);
  new.unit_basis := r.basis; new.unit_total := r.total; new.unit_word := r.unit;
  return new;
end $$;
drop trigger if exists trg_item_unit on public.promotion_items;
create trigger trg_item_unit before insert or update of name on public.promotion_items for each row execute function private.set_item_unit();

-- (3) 추천에도 단위 가격·최저가: product_picks 에 unit_price, unit_label, low_days, prev_min 추가, refresh_picks_for 의 insert 에 포함, v_picks 재생성
alter table public.product_picks add column if not exists unit_price int, add column if not exists unit_label text, add column if not exists low_days int, add column if not exists prev_min int;

-- (4) 찜 알림 키: 서버 함수 send-alerts 가 처음 호출 때 만들어 private.app_keys 에 둔다(사람·대화·저장소를 거치지 않음)
create table if not exists private.app_keys (name text primary key, value text not null, created_at timestamptz not null default now());
-- public.vapid_public()(누구나), public.vapid_private()·vapid_store()(service_role 만)

-- (5) 상품 보기 중복 제거(2026-11-26): 같은 상품이 여러 기획전에 있으면 한 줄만
create or replace view public.v_products with (security_invoker = true) as
select distinct on (x.dk) x.*, count(*) over (partition by x.dk) as promo_count
from (
  select v.*, case when length(coalesce(v.nkey, '')) >= 6 then v.source_id || '|' || v.nkey || '|' || coalesce(v.price::text, '-') else v.item_key end as dk
  from public.v_items v
) x
order by x.dk, (x.price is null), x.price, x.end_date nulls last, x.promotion_id;
grant select on public.v_products to anon, authenticated;
