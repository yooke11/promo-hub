"""프로모션 허브 상태 점검 — 사이트가 실제로 쓰는 경로를 사이트와 같은 권한(anon)으로 확인한다.

사용: python scripts/healthcheck.py [--json out.json]
종료 코드 0=정상, 1=문제 있음. 결과 JSON: {"ok": bool, "checks": [{name, ok, ms, detail, fix}]}

점검 항목(실패 시 fix 에 정상화 방법을 적는다)
- site       : 사이트 HTML 200, config.js 에 supabaseUrl
- promotions : 사이트 첫 화면 조회(v_promotions 1000건) 5초 안(전송 포함), HTTP 오류 없음 ← anon 서버 제한 3초 초과 시 500
- sources    : v_sources 조회
- items      : 상품 탭 조회(v_items)
- freshness  : 마지막 수집이 26시간 안
- pipeline   : (한국시간 06:45 이후) 오늘 수집 채널 수 ≥ 운영 채널의 70%, 오늘 키워드·가격비교 실행 기록
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
SITE = os.environ.get("PROMOHUB_SITE", "https://promo-hub-one.vercel.app")
URL = os.environ.get("SUPABASE_URL", "https://wjfbcbiyzoymqqnoemvu.supabase.co")
KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_-DNHcg_lvpePh3aeXGRXGw_qDJAkXI5")
SLOW_MS = 5000  # 응답 전송 포함(미국 러너 기준). 서버 3초 초과는 HTTP 500으로 따로 잡힘

checks: list[dict] = []


def add(name, ok, ms=None, detail="", fix=""):
    checks.append({"name": name, "ok": bool(ok), "ms": ms, "detail": str(detail)[:400], "fix": "" if ok else fix})


def rest(c: httpx.Client, path: str, rng: str | None = None):
    h = {"apikey": KEY}
    if rng:
        h["Range"] = rng
    t = time.monotonic()
    r = c.get(f"{URL}/rest/v1/{path}", headers=h)
    return r, int((time.monotonic() - t) * 1000)


def enabled_count() -> int:
    data = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return sum(1 for s in data["sources"] if s.get("enabled", True))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    now = datetime.now(KST)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    run0 = today0 + timedelta(hours=5)
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        # 1. 사이트
        try:
            r = c.get(SITE + "/")
            cfg = c.get(SITE + "/config.js")
            ok = r.status_code == 200 and "supabaseUrl" in cfg.text
            add("site", ok, None, f"html {r.status_code}, config.js {cfg.status_code}",
                "Vercel 재배포(rootDirectory 'web' 필수) 또는 web/config.js 확인")
        except Exception as e:
            add("site", False, None, e, "Vercel 상태·도메인 확인 후 재배포")
        # 2. 첫 화면 조회 — 사이트와 같은 쿼리
        try:
            r, ms = rest(c, "v_promotions?select=*&status=neq.ended&order=end_date.asc.nullslast", "0-999")
            n = len(r.json()) if r.status_code in (200, 206) else 0
            add("promotions", r.status_code in (200, 206) and n > 0 and ms < SLOW_MS, ms,
                f"HTTP {r.status_code}, {n}건, {ms}ms" + ("" if r.status_code in (200, 206) else f" {r.text[:200]}"),
                "v_promotions 가 느리거나 오류 → 최근 뷰 변경을 되돌리거나 EXPLAIN ANALYZE 로 순차 스캔 제거"
                " (anon statement_timeout 3s 초과 시 사이트가 샘플 모드로 떨어짐). 0건이면 v_live_runs·수집 결과 확인")
        except Exception as e:
            add("promotions", False, None, e, "Supabase 상태 확인")
        for name, path in [("sources", "v_sources?select=*&order=rank.asc"),
                           ("items", "v_items?select=*&order=discount_rate.desc.nullslast&limit=60")]:
            try:
                r, ms = rest(c, path)
                add(name, r.status_code == 200 and ms < SLOW_MS, ms, f"HTTP {r.status_code}, {ms}ms {r.text[:150] if r.status_code != 200 else ''}",
                    f"{path.split('?')[0]} 뷰 오류/지연 → 최근 변경 되돌리기 또는 인덱스 추가")
            except Exception as e:
                add(name, False, None, e, "Supabase 상태 확인")
        # 3. 신선도
        try:
            r, _ = rest(c, "crawl_runs?select=started_at&order=started_at.desc&limit=1")
            last = datetime.fromisoformat(r.json()[0]["started_at"].replace("Z", "+00:00"))
            age = (now - last).total_seconds() / 3600
            add("freshness", age < 26, None, f"마지막 수집 {last.astimezone(KST):%m-%d %H:%M} ({age:.1f}시간 전)",
                "GitHub Actions collect 워크플로 실행 기록 확인(cron 비활성화·토큰 만료·실패)")
        except Exception as e:
            add("freshness", False, None, e, "crawl_runs 조회 실패")
        # 4. 오늘 파이프라인 (06:45 이후)
        if now >= today0 + timedelta(hours=6, minutes=45):
            since = run0.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                r, _ = rest(c, f"crawl_runs?select=source_id,found&started_at=gte.{since}")
                rows = r.json()
                srcs = {x["source_id"] for x in rows}
                good = {x["source_id"] for x in rows if (x.get("found") or 0) > 0}
                need = enabled_count()
                add("pipeline.collect", len(srcs) >= max(1, int(need * 0.7)), None,
                    f"오늘 수집 기록 {len(srcs)}/{need}곳, 기획전 잡힌 곳 {len(good)}곳",
                    "collect 잡 실패·시간 초과 확인 → 원인 고친 뒤 workflow_dispatch 로 재실행")
                r, _ = rest(c, f"promotion_keywords?select=promotion_id&generated_at=gte.{since}&limit=1")
                add("pipeline.keywords", bool(r.json()), None, "오늘 키워드 생성 " + ("있음" if r.json() else "없음"),
                    "keywords 잡 로그 확인(검색광고 키 만료·API 오류) → 고친 뒤 재실행")
                r, _ = rest(c, f"price_runs?select=finished_at,stats&finished_at=gte.{since}&order=finished_at.desc&limit=1")
                pr = r.json()
                st = (pr[0].get("stats") or {}) if pr else {}
                add("pipeline.compare", bool(pr) and not st.get("fatal"), None,
                    f"가격비교 {'있음' if pr else '없음'} matched={st.get('matched')} stopped={st.get('stopped')} fatal={st.get('fatal')}",
                    "compare 잡 로그·price_runs.stats.diag 확인(에누리 차단/구조 변경)")
                r, _ = rest(c, "v_picks?select=pick_date&limit=1")
                pk = r.json() if r.status_code == 200 else []
                add("pipeline.picks", bool(pk) and pk[0]["pick_date"] == now.date().isoformat(), None,
                    f"추천 상품 기준일 {pk[0]['pick_date'] if pk else '없음'}",
                    "collect.yml 의 picks 잡 로그 확인 → rpc/refresh_picks 재실행(토큰 필요) 또는 private.refresh_picks_core() 실행")
            except Exception as e:
                add("pipeline", False, None, e, "Supabase 조회 실패")
    ok = all(x["ok"] for x in checks)
    out = {"ok": ok, "at": now.isoformat(timespec="minutes"), "checks": checks}
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in checks:
        print(("OK  " if x["ok"] else "FAIL") + f" {x['name']}: {x['detail']}" + (f"\n     → {x['fix']}" if not x["ok"] else ""))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
