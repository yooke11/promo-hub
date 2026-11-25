-- 2026-11-25: v_promotions 가 good_items CTE를 기획전마다 전체 스캔(14k×1k)해 6.6초 → anon 3초 제한 초과 → 사이트가 샘플 모드로 떨어짐.
-- promotion_items 를 promotion_id 인덱스로 바로 조회하도록 변경(0.27초). 컬럼·결과 동일.
create index if not exists ix_items_promo_pos on public.promotion_items (promotion_id, "position");
-- 뷰 본문은 Supabase 마이그레이션 v_promotions_fast_items 참고
