-- 장애 대응 2026-11-28: v_items 가 anon 3초 제한 초과(7.5초, health items FAIL).
-- 원인: base CTE 행 수를 1로 잘못 추정 → cross_low(GROUP BY)를 4,660번 반복 계산(830만 행 비교).
-- 조치: 채널 간 최저가/채널 수를 조인 대신 창 함수로 한 번에 계산. 컬럼·값 동일. 되돌리기: *_before.sql
create or replace view public.v_items as  WITH base AS (
         SELECT i.promotion_id,
            i.item_key,
            i."position",
            i.name,
            i.brand,
            i.url,
            i.image_url,
            i.price,
                CASE
                    WHEN (EXISTS ( SELECT 1
                       FROM source_trust st2
                      WHERE st2.source_id = p.source_id AND st2.level = 'price'::text)) AND NOT (EXISTS ( SELECT 1
                       FROM verified_prices vp2
                      WHERE vp2.item_key = i.item_key AND vp2.price = i.price)) THEN NULL::integer
                    ELSE i.original_price
                END AS original_price,
                CASE
                    WHEN (EXISTS ( SELECT 1
                       FROM source_trust st2
                      WHERE st2.source_id = p.source_id AND st2.level = 'price'::text)) AND NOT (EXISTS ( SELECT 1
                       FROM verified_prices vp2
                      WHERE vp2.item_key = i.item_key AND vp2.price = i.price)) THEN NULL::integer
                    ELSE i.discount_rate
                END AS discount_rate,
            p.title AS promotion_title,
            p.url AS promotion_url,
            p.end_date,
            COALESCE(i.category, p.category) AS category,
            i.category_by_name,
            i.unit_basis,
            i.unit_total,
            i.unit_word,
            p.kind,
            s.id AS source_id,
            s.name AS source_name,
            s.channel_type,
            s.rank AS source_rank,
            norm_name(i.name) AS nkey
           FROM promotion_items i
             JOIN promotions p ON p.id = i.promotion_id
             JOIN sources s ON s.id = p.source_id
             JOIN v_live_runs lr ON lr.source_id = p.source_id
          WHERE (p.end_date IS NULL OR p.end_date >= (now() AT TIME ZONE 'Asia/Seoul'::text)::date) AND (p.end_date IS NOT NULL OR p.start_date IS NOT NULL OR p.last_seen >= (now() - '2 days'::interval)) AND lr.last_good_run IS NOT NULL AND p.last_seen >= (lr.last_good_run - '01:00:00'::interval) AND i.price > 0 AND NOT (EXISTS ( SELECT 1
                   FROM wrong_prices wp
                  WHERE wp.item_key = i.item_key AND wp.price = i.price)) AND (EXISTS ( SELECT 1
                   FROM source_trust st
                  WHERE st.source_id = p.source_id AND (st.level <> 'bad'::text OR (EXISTS ( SELECT 1
                           FROM verified_prices vp
                          WHERE vp.item_key = i.item_key AND vp.price = i.price)))))
        ), bx AS (
         SELECT base.*,
                CASE WHEN length(base.nkey) >= 6 THEN min(base.price) OVER (PARTITION BY base.nkey) END AS cl_lowest,
                CASE WHEN length(base.nkey) >= 6 THEN dense_rank() OVER (PARTITION BY base.nkey ORDER BY base.source_id)
                                                    + dense_rank() OVER (PARTITION BY base.nkey ORDER BY base.source_id DESC) - 1 END AS cl_channels
           FROM base
        )
 SELECT b.promotion_id,
    b.item_key,
    b."position",
    b.name,
    b.brand,
    b.url,
    b.image_url,
    b.price,
    b.original_price,
    b.discount_rate,
    b.promotion_title,
    b.promotion_url,
    b.end_date,
    b.category,
    b.kind,
    b.source_id,
    b.source_name,
    b.channel_type,
    b.source_rank,
    b.nkey,
    lower((((((b.name || ' '::text) || b.brand) || ' '::text) || b.promotion_title) || ' '::text) || b.source_name) AS search_text,
    pc.market_lowest,
    pc.market_mall,
    pc.market_url,
    pc.market_count,
    pc.status AS price_status,
    pc.checked_at AS price_checked_at,
        CASE
            WHEN pc.market_lowest > 0 AND b.price IS NOT NULL THEN round((b.price - pc.market_lowest)::numeric * 100::numeric / pc.market_lowest::numeric, 1)
            ELSE NULL::numeric
        END AS vs_market_pct,
        CASE
            WHEN b.cl_channels > 1 THEN b.cl_lowest
            ELSE NULL::integer
        END AS cross_lowest,
        CASE
            WHEN b.cl_channels > 1 THEN b.cl_channels
            ELSE NULL::bigint
        END AS cross_channels,
    b.category_by_name,
    pl.low_days,
    pl.prev_min,
        CASE
            WHEN b.price > 0 AND b.unit_total > 0::numeric THEN
            CASE
                WHEN b.unit_basis = ANY (ARRAY['g'::text, 'ml'::text]) THEN round(b.price::numeric * 100::numeric / b.unit_total)::integer
                ELSE round(b.price::numeric / b.unit_total)::integer
            END
            ELSE NULL::integer
        END AS unit_price,
        CASE b.unit_basis
            WHEN 'g'::text THEN '100g당'::text
            WHEN 'ml'::text THEN '100ml당'::text
            WHEN 'ea'::text THEN ('1'::text || b.unit_word) || '당'::text
            ELSE NULL::text
        END AS unit_label,
        CASE
            WHEN b.price > 0 AND b.unit_total > 0::numeric AND (b.unit_basis = ANY (ARRAY['g'::text, 'ml'::text])) THEN round(b.price::numeric * 100::numeric / b.unit_total)::integer
            ELSE NULL::integer
        END AS unit_price_100
   FROM bx b
     LEFT JOIN price_checks pc ON pc.item_key = b.item_key
     LEFT JOIN price_lows pl ON pl.k = hashtextextended(b.item_key, 0::bigint);
