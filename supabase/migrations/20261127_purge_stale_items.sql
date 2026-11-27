-- 2026-11-27 기획전은 다시 수집됐는데 상품 목록이 비어 들어오면(ingest 는 빈 목록이면 상품을 교체하지 않음)
-- 옛 수집의 상품·가격이 그대로 남아 화면에 나왔다(코오롱몰 쿠폰가). purge 1단계에서
-- 최근 수집에서 다시 확인되지 않은 상품(상품 last_seen < 기획전 last_seen - 1시간)을 삭제한다.
-- 이전 정의는 private.def_backup(name='private.purge_inaccurate')에 저장.
do $$ declare old text; new text; anchor text := '  delete from public.source_trust where true;'; begin
  select pg_get_functiondef('private.purge_inaccurate(integer)'::regprocedure) into old;
  insert into private.def_backup(name, def) values ('private.purge_inaccurate', old);
  new := replace(old, anchor, '  -- 최근 수집에서 다시 확인되지 않은 상품(기획전은 다시 보였는데 상품은 빠짐)은 가격이 지금과 다를 수 있어 삭제
  delete from public.promotion_items i using public.promotions p
   where p.id = i.promotion_id and i.last_seen < p.last_seen - interval ''1 hour'';
' || anchor);
  execute new;
end $$;
