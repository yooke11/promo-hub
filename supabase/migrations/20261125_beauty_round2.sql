-- 2026-11-25 뷰티 2차: 올리브영 상위 브랜드 시험 수집 통과분을 뷰티세일픽에 연결
insert into public.source_verticals(vertical, source_id)
select 'beauty', s from unnest(array['anua','abib','medicube','mediheal','numbuzin','torriden']) s
on conflict do nothing;
