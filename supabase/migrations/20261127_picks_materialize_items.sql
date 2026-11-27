-- 2026-11-27 추천 계산(refresh_picks_for)이 13초 걸려 picks 작업이 시간 초과(57014)로 실패.
-- 원인: v_items(검증 관문 포함)를 진행 중 기획전과 조인할 때 행 수를 1~3개로 잘못 추정해 cross_low 를 중첩 반복.
-- 조치: live 와 v_items 를 먼저 한 번만 계산(materialized)해 두고 조인 → 1.0초.
-- 이전 정의는 private.def_backup(name='private.refresh_picks_for')에 저장.
create table if not exists private.def_backup(name text, def text, saved_at timestamptz default now());
do $$ declare old text; new text; begin
  select pg_get_functiondef('private.refresh_picks_for(text,text[],integer,integer,integer,numeric,integer)'::regprocedure) into old;
  insert into private.def_backup(name, def) values ('private.refresh_picks_for', old);
  new := replace(old, 'with live as (select id, title, url, end_date from public.v_promotions where status <> ''ended''),',
                      'with live as materialized (select id, title, url, end_date from public.v_promotions where status <> ''ended''),
  vi as materialized (select * from public.v_items),');
  new := replace(new, 'from public.v_items i join live l', 'from vi i join live l');
  execute new;
end $$;
