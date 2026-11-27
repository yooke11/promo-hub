-- 2026-11-27 29CM·코오롱몰·패션플러스: 목록의 쿠폰 적용가 대신 상세 페이지 판매가를 읽도록 수집 방식 변경.
-- 이전 방식으로 모은 가격의 대조 결과(불일치)는 지금 수집 방식의 정확도를 나타내지 않으므로
-- 신뢰도(source_trust) 계산에서는 방식 변경 이후 대조 결과만 센다. 기준(10건 이상, 불일치 2% 이하)은 그대로.
-- 이전 정의는 private.def_backup(name='private.purge_inaccurate')에 저장.
create table if not exists private.trust_since(source_id text primary key, since timestamptz not null, reason text);
insert into private.trust_since values
 ('29cm', now(), '가격 읽는 방식 변경(상세 페이지 판매가)'),
 ('kolonmall', now(), '가격 읽는 방식 변경(상세 페이지 판매가)'),
 ('fashionplus', now(), '가격 읽는 방식 변경(상세 페이지 판매가)')
on conflict (source_id) do update set since = excluded.since, reason = excluded.reason;
do $$ declare old text; new text; anchor text := 'where checked_at > now() - interval ''3 days'' and status <> ''blocked''
    group by source_id'; begin
  select pg_get_functiondef('private.purge_inaccurate(integer)'::regprocedure) into old;
  insert into private.def_backup(name, def) values ('private.purge_inaccurate', old);
  new := replace(old, anchor, 'where checked_at > now() - interval ''3 days'' and status <> ''blocked''
      and checked_at > coalesce((select ts.since from private.trust_since ts where ts.source_id = price_verifications.source_id), ''-infinity'')
    group by source_id');
  execute new;
end $$;
