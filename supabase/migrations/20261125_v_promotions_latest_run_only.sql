-- 2026-11-25: 사이트에 '마지막 정상 수집'에서 다시 보인 기획전만 노출(허용 오차 1시간 → 5분).
-- 같은 날 여러 번 수집하면 이전 수집에서만 잡힌 문구(필터 강화 전 제목)가 1시간 동안 남던 문제.
-- 되돌리기: 아래 do 블록의 '00:05:00' 과 '01:00:00' 을 바꿔 실행.
do $$
declare d text := pg_get_viewdef('public.v_promotions'::regclass, true);
begin
  execute 'create or replace view public.v_promotions with (security_invoker = true) as ' ||
          replace(d, '''01:00:00''::interval', '''00:05:00''::interval');
end $$;
