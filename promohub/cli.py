"""명령행 진입점.

  python -m promohub.cli collect [--only gmarket,musinsa] [--headed]
  python -m promohub.cli probe gmarket          # 한 채널만 수집해 결과를 표로 확인(저장 안 함)
  python -m promohub.cli serve [--port 8000]
  python -m promohub.cli export data/promotions.json
"""
from __future__ import annotations

import argparse
from pathlib import Path
import asyncio
import json
import logging
import os
import sys

from .config import ROOT, load_config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promohub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--only", default="")
    c.add_argument("--headed", action="store_true", help="브라우저 창을 띄워서 수집(디버깅용)")
    c.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    c.add_argument("--shard", default="", help="i/n — 채널을 n묶음으로 나눠 i번째(0부터)만 수집. 병렬 실행용")
    c.add_argument("--sink", choices=["local", "supabase", "both"], default="",
                   help="저장 위치. 기본: Supabase 환경변수가 있으면 supabase, 없으면 local")
    p = sub.add_parser("probe")
    p.add_argument("source")
    p.add_argument("--headed", action="store_true")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    pc = sub.add_parser("compare", help="기획전 상품의 웹 최저가(에누리 가격비교) 비교 → Supabase 저장")
    pc.add_argument("--budget", type=float, default=None, help="최대 실행 시간(초). 넘으면 그때까지 결과만 저장")
    pc.add_argument("--limit", type=int, default=400)
    kw = sub.add_parser("keywords", help="새로 수집된 기획전에 검색광고 추천 키워드(최대 10개) 생성 → Supabase 저장")
    kw.add_argument("--limit", type=int, default=500)
    pk = sub.add_parser("picks", help="추천 상품 계산 + 상품 페이지 대조(가격 확인된 상품만 최종 추천)")
    pk.add_argument("--sample", type=int, default=6, help="채널마다 무작위로 대조할 상품 수(가격 정확도 측정)")
    pk.add_argument("--budget", type=float, default=900, help="상품 페이지 대조 시간 예산(초, 단계마다)")
    e = sub.add_parser("export")
    e.add_argument("out")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    db = os.environ.get("PROMOHUB_DB", str(ROOT / "data" / "promohub.db"))

    if args.cmd == "picks":
        _run_picks(args)
        return

    if args.cmd == "collect":
        from .collector import run
        from .remote import RemoteSink, remote_configured
        from .store import Store
        only = [x for x in args.only.split(",") if x] or None
        mode = args.sink or ("supabase" if remote_configured() else "local")
        store = Store(db) if mode in ("local", "both") else None
        sink = RemoteSink() if mode in ("supabase", "both") else None
        shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
        summary = asyncio.run(run(load_config(args.config), store, only, headless=not args.headed, sink=sink, shard=shard,
                                  config_name=Path(args.config).name))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if summary and all("error" in v for v in summary.values()):
            sys.exit(1)

    elif args.cmd == "probe":
        from playwright.async_api import async_playwright
        from .collector import collect_source
        from .normalize import normalize
        src = load_config().get(args.source)

        async def _probe():
            async with async_playwright() as pw:
                b = await pw.chromium.launch(headless=not args.headed)
                try:
                    return await collect_source(b, src)
                finally:
                    await b.close()

        raws = asyncio.run(_probe())
        promos = [p for p in (normalize(r) for r in raws) if p]
        for pr in promos:
            period = f"{pr.start_date or '?'} ~ {pr.end_date or '?'}"
            print(f"- [{pr.kind}/{pr.category}] {pr.title[:50]:<50} | {period} | {pr.url[:90]}")
        print(f"\n후보 {len(raws)}건 → 정규화 {len(promos)}건")
        if not promos:
            print("결과가 없으면 --headed 로 화면을 보고 config/sources.yaml 의 include_patterns 를 조정하세요.")

    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("promohub.api:app", host=args.host, port=args.port)

    elif args.cmd == "compare":
        from .pricecheck import run as compare_run
        print(json.dumps(compare_run(args.limit, budget_s=args.budget), ensure_ascii=False, default=str))

    elif args.cmd == "keywords":
        from .keywords import run as kw_run
        print(json.dumps(kw_run(args.limit), ensure_ascii=False))

    elif args.cmd == "export":
        from .store import Store
        st = Store(db)
        data = {"sources": st.sources(), "items": st.query(limit=5000)}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        print(f"{len(data['items'])}건 → {args.out}")




def _rpc(name: str, body: dict):
    import httpx
    from .verify import _sb
    base, h = _sb()
    import time
    for attempt in range(3):   # 방금 대량 저장한 직후 첫 호출은 3초 제한에 걸릴 수 있다 → 잠시 뒤 다시(두 번째부터는 1초대)
        r = httpx.post(f"{base}/rest/v1/rpc/{name}", json=body, headers=h, timeout=60)
        if r.status_code == 500 and "57014" in r.text and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        break
    if r.status_code != 200:
        raise RuntimeError(f"{name} 실패: {r.status_code} {r.text[:200]}")
    return r.json()


def _run_picks(args):
    """추천 3단계: 계산 → 페이지 대조 → 불일치 빼고 재계산 → 새로 들어온 것 대조 → 확인된 것만 최종 추천."""
    import httpx
    from .verify import _sb, fetch_targets, send, summarize, verify
    tok = os.environ["PROMOHUB_INGEST_TOKEN"]
    base, h = _sb()
    verts = sorted({r["vertical"] for r in httpx.get(base + "/rest/v1/source_verticals", params={"select": "vertical"},
                                                       headers=h, timeout=30).json()})
    verts = ["all"] + verts
    mobile = {s.id for s in load_config().sources if s.mobile}
    done: dict[str, dict] = {}
    report = {}
    for stage in (0, 1, 2):
        if stage == 2:
            # 2026-11-27 운영 원칙: 확인되지 않은 숫자·상품이 아닌 항목은 사이트에 내보내기 전에 지운다(가격 대조 직후, 최종 추천 앞)
            report["purge"] = {}
            for step in (1, 2, 3):   # 3초 제한 안에 들도록 나눠서
                report["purge"].update(_rpc("purge_inaccurate", {"p_token": tok, "p_step": step}) or {})
            print("부정확 데이터 삭제:", report["purge"], flush=True)
            # 가격 기록은 지우고 남은(확인된) 가격으로만 — '최근 N일 중 최저가' 근거
            try:
                report["prices"] = _rpc("record_prices", {"p_token": tok})
                print("가격 기록:", report["prices"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("가격 기록 실패:", e, flush=True)
        counts = {v: _rpc("refresh_picks_v", {"p_token": tok, "p_vertical": v, "p_strict": stage}) for v in verts}
        report[f"stage{stage}"] = counts
        print(f"추천 {stage}단계:", counts, flush=True)
        if stage == 2:
            break
        targets = [t for t in fetch_targets(args.sample if stage == 0 else 0) if t["item_key"] not in done]
        rows = asyncio.run(verify(targets, mobile, budget_s=args.budget))
        for r in rows:
            done[r["item_key"]] = r
        send(rows)
        report[f"verify{stage}"] = summarize(rows)
        print(f"상품 페이지 대조 {stage}:", json.dumps(report[f"verify{stage}"], ensure_ascii=False), flush=True)
    # 찜 알림: 가격이 내렸거나 내일 마감인 찜 상품을 브라우저 알림으로(Supabase 서버 함수 send-alerts)
    try:
        r = httpx.post(f"{base}/functions/v1/send-alerts", json={"token": tok}, headers=h, timeout=120)
        report["alerts"] = r.json() if r.status_code == 200 else {"status": r.status_code}
        print("찜 알림:", report["alerts"], flush=True)
    except Exception as e:  # noqa: BLE001
        print("찜 알림 실패:", e, flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not sum(report["stage2"].values()):
        raise SystemExit("최종 추천 0개 — 대조 결과 확인 필요")


if __name__ == "__main__":
    sys.exit(main())
