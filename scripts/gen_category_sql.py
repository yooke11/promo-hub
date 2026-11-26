"""config/category_rules.json → DB 함수 public.classify_product(text) SQL 생성 (파이썬 categorize.py 와 같은 규칙).

  python scripts/gen_category_sql.py > /tmp/classify.sql
파이썬 정규식의 \\b(단어 경계)는 PostgreSQL 에서 \\y 로 바꾼다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def q(s: str) -> str:
    return "'" + s.replace("\\b", "\\y").replace("'", "''") + "'"


def main():
    d = json.loads((ROOT / "config" / "category_rules.json").read_text(encoding="utf-8"))
    strip_p = ",".join(q(p) for p, _ in d["strip"])
    strip_c = ",".join(q(c) for _, c in d["strip"])
    cats = ",".join(q(c) for c, _ in d["rules"])
    pats = ",".join(q(p) for _, p in d["rules"])
    print(f"""create or replace function public.classify_product(p_name text, p_prefer text default null) returns text
language plpgsql immutable set search_path = public as $$
-- 자동 생성: scripts/gen_category_sql.py (규칙 원본 config/category_rules.json). 손으로 고치지 말 것.
declare
  sp text[] := array[{strip_p}];
  sc text[] := array[{strip_c}];
  cs text[] := array[{cats}];
  ps text[] := array[{pats}];
  t text := lower(coalesce(p_name, ''));
  sc_score int[] := array_fill(0, array[array_length(cs, 1)]);
  n int; i int; j int; best int := 0; besti int := 0; pidx int;
begin
  if t = '' then return null; end if;
  for i in 1 .. array_length(sp, 1) loop
    select count(*) into n from regexp_matches(t, sp[i], 'gi');
    if n > 0 then
      j := array_position(cs, sc[i]);
      if j is not null then sc_score[j] := sc_score[j] + n; end if;
      t := regexp_replace(t, sp[i], ' ', 'gi');
    end if;
  end loop;
  for i in 1 .. array_length(cs, 1) loop
    select count(*) into n from regexp_matches(t, ps[i], 'gi');
    sc_score[i] := sc_score[i] + n;
  end loop;
  for i in 1 .. array_length(cs, 1) loop
    if sc_score[i] > best then best := sc_score[i]; besti := i; end if;
  end loop;
  if besti = 0 then return null; end if;
  pidx := array_position(cs, p_prefer);
  if cs[besti] = '식품' then   -- 식품어와 다른 분야어가 같은 수면 식품이 아닌 쪽(기획전 제목이 식품이어도)
    for i in 1 .. array_length(cs, 1) loop
      if i <> besti and sc_score[i] = best then
        if pidx is not null and pidx <> besti and sc_score[pidx] = best then return p_prefer; end if;
        return cs[i];
      end if;
    end loop;
  end if;
  if pidx is not null and sc_score[pidx] = best then return p_prefer; end if;   -- 동점이면 기획전 제목 분류 우선
  return cs[besti];
end $$;""")


if __name__ == "__main__":
    main()
