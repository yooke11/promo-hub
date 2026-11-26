-- 단위 가격(2026-11-26): 상품명에서 용량을 '확실히' 읽힐 때만 계산 — 애매하면 null(틀린 숫자보다 안 보이는 게 낫다)
-- basis 'g'|'ml'|'ea', total 총량(g·ml·개수), unit (ea 일 때 '개'|'포'|'캔'|'병'|'봉'|'팩'|'캡슐'|'정')
create or replace function public.parse_unit(p_name text, out basis text, out total numeric, out unit text)
language plpgsql immutable set search_path = public as $$
declare
  t text := lower(coalesce(p_name, ''));
  m text[]; vals numeric[] := '{}'; b text; v numeric; rest text; head text; mult numeric := 1; cnt int;
  wv text := '(\d+(?:\.\d+)?)\s*(kg|mg|g|ml|l)(?![a-wyz])';                           -- 200gX4 의 x 는 허용
  cu text := '(개입|개|입|구|팩|봉|캔|병|포|캡슐|정|박스|통|세트|box|ea)(?![가-힣a-z])';  -- 개수 단위
begin
  basis := null; total := null; unit := null;
  if t = '' then return; end if;
  t := replace(replace(replace(t, '×', 'x'), '*', 'x'), '＊', 'x');
  t := regexp_replace(t, '(\d),(\d{3})', '\1\2', 'g');                                  -- 1,050 → 1050
  if t ~ '\d\s*\+\s*\d' then return; end if;                                            -- 1+1, 2+1 묶음
  if t ~ '\d+(\.\d+)?\s*(kg|g|ml|l)\s*(/|~|또는|or|택\s*1)\s*\d' then return; end if;    -- '2kg / 4kg' 옵션

  -- 무게·부피: 값이 둘 이상이면 애매(같은 값 반복은 허용)
  for m in select regexp_matches(t, wv, 'g') loop
    if m[2] = 'mg' then continue; end if;
    v := m[1]::numeric * case m[2] when 'kg' then 1000 when 'l' then 1000 else 1 end;
    b := case when m[2] in ('kg','g') then 'g' else 'ml' end;
    if basis is not null and (basis <> b or not (v = any(vals))) then basis := null; return; end if;
    basis := b; vals := vals || v;
  end loop;

  if basis is not null then
    v := vals[1];
    head := substring(t from '^(.*?)\d+(?:\.\d+)?\s*(?:kg|g|ml|l)(?![a-wyz])');       -- 용량 앞
    rest := substring(t from '\d+(?:\.\d+)?\s*(?:kg|g|ml|l)(?![a-wyz])(.*)$');           -- 첫 용량 뒤
    rest := regexp_replace(rest, '^.*\d+(?:\.\d+)?\s*(?:kg|g|ml|l)(?![a-wyz])', '');     -- 같은 용량이 또 있으면 마지막 뒤
    -- 용량 바로 뒤의 'x N(단위)' 또는 'N단위'만 곱함
    if rest ~ '^\s*\)?\s*x\s*\d+' then
      mult := substring(rest from '^\s*\)?\s*x\s*(\d+)')::numeric;
      rest := regexp_replace(rest, '^\s*\)?\s*x\s*\d+\s*(' || cu || ')?', '');
    elsif rest ~ ('^\s*[,(]?\s*\d+\s*' || cu) then
      mult := substring(rest from '^\s*[,(]?\s*(\d+)')::numeric;
      rest := regexp_replace(rest, '^\s*[,(]?\s*\d+\s*' || cu, '');
    end if;
    -- 다른 곳에 개수 표기가 또 있으면(예: 4입X4개, 3박스) 애매
    select count(*) into cnt from regexp_matches(coalesce(head,'') || ' ' || coalesce(rest,''), '\d+\s*' || cu, 'g');
    if cnt > 0 or rest ~ '^\s*\)?\s*x\s*\d' then basis := null; return; end if;
    total := v * mult;
    if total < 5 or total > 100000 then basis := null; total := null; end if;
    return;
  end if;

  -- 무게·부피가 없으면 개수만: 개수 표기가 하나(또는 'N입 x M개')일 때
  select count(*) into cnt from regexp_matches(t, '\d+\s*' || cu, 'g');
  if cnt = 2 and t ~ '(\d+)\s*입\s*x\s*(\d+)\s*개' then
    m := regexp_match(t, '(\d+)\s*입\s*x\s*(\d+)\s*개');
    basis := 'ea'; unit := '개'; total := m[1]::numeric * m[2]::numeric;
  elsif cnt = 1 then
    m := regexp_match(t, '(\d+)\s*' || cu);
    if m[2] in ('박스','통','세트','box') then return; end if;                           -- 상자 수는 단위 가격 의미 없음
    mult := 1;
    if t ~ ('\d+\s*' || m[2] || '\s*x\s*\d+') then mult := substring(t from '\d+\s*' || m[2] || '\s*x\s*(\d+)')::numeric; end if;
    basis := 'ea'; total := m[1]::numeric * mult;
    unit := case when m[2] in ('개입','입','구','개','ea') then '개' else m[2] end;
  end if;
  if basis = 'ea' and (total < 2 or total > 1000) then basis := null; total := null; unit := null; end if;
end $$;
