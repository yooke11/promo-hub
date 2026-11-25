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
    e = sub.add_parser("export")
    e.add_argument("out")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    db = os.environ.get("PROMOHUB_DB", str(ROOT / "data" / "promohub.db"))

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


if __name__ == "__main__":
    sys.exit(main())
