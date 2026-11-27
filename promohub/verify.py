"""상품 페이지 대조 — 사이트에 보여 주는 가격이 실제 판매 페이지와 같은지 확인한다(2026-11-26).

대상
  - pick   : 오늘의 추천 상품(4개 사이트에 가장 크게 보이는 숫자)
  - sample : 채널마다 무작위 상품 몇 개 — 채널별 가격 정확도를 매일 잰다

판정 (상품 페이지를 한 번 열어서)
  - match      : 판매가가 페이지에 있고, 정가를 보여 주는 상품이면 정가도 페이지에 있음
  - price_only : 판매가는 맞지만 정가가 페이지에서 확인되지 않음 → 추천에서는 할인 표시 없이 가격만 보여 줌
  - mismatch   : 페이지의 구조화 가격(JSON-LD·meta)이 우리 가격과 다르고, 우리 가격은 페이지에 없음
  - not_found  : 구조화 가격이 없고 우리 가격도 페이지 글자에 없음
  - blocked    : robots.txt 금지·접속 실패 등으로 확인 못 함
추천 계산(refresh_picks_v 2단계)은 match·price_only 만 쓴다.

부담 줄이기: 이미지·동영상·글꼴은 받지 않고, 같은 쇼핑몰은 동시에 1개·1초 간격으로만 연다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx

from .collector import DESKTOP_UA, MOBILE_UA, RobotsCache, _block_heavy

log = logging.getLogger("promohub")

_AMT = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{3,9})(?![\d,])")
PRICE_META = ("product:price:amount", "og:price:amount", "product:sale_price:amount", "price")


def _sb():
    key = os.environ["SUPABASE_ANON_KEY"]
    h = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_"):
        h["Authorization"] = f"Bearer {key}"
    return os.environ["SUPABASE_URL"].rstrip("/"), h


def _int(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
    if not m:
        return None
    try:
        n = int(float(m.group(0).replace(",", "")))
    except ValueError:
        return None
    return n if 100 <= n < 100_000_000 else None


def structured_prices(ld_texts: list[str], metas: dict[str, str]) -> set[int]:
    """JSON-LD(Product.offers.price/lowPrice/highPrice)와 meta 태그의 가격."""
    out: set[int] = set()

    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            ts = t if isinstance(t, list) else [t]
            if any(x in ("Offer", "AggregateOffer") for x in ts) or "price" in o or "lowPrice" in o:
                for k in ("price", "lowPrice", "highPrice"):
                    n = _int(o.get(k))
                    if n:
                        out.add(n)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for t in ld_texts:
        try:
            walk(json.loads(t))
        except Exception:
            continue
    for k in PRICE_META:
        n = _int(metas.get(k))
        if n:
            out.add(n)
    return out


def text_amounts(text: str) -> set[int]:
    """페이지 글자 속 금액. 단위 가격(100ml당 824원)·할인 금액(5,000원 할인)·배송비 등은 빼고 센다."""
    from .products import _NOT_PRICE_AMT
    text = _NOT_PRICE_AMT.sub(" ", text or "")
    return {int(m.group(1).replace(",", "")) for m in _AMT.finditer(text)}


def judge(our_price: int, our_original: int | None, structured: set[int], text: str,
          structured_only: bool = False) -> tuple[str, str]:
    """(status, detail) — 위 판정 규칙.
    structured_only: 페이지 구조화 가격(JSON-LD)이 있으면 그 값과만 맞춘다(추천 상품 카드의 쿠폰가 등 다른 금액과 우연히 맞는 것 방지)."""
    amounts = text_amounts(text)
    has_price = our_price in structured or (our_price in amounts and not (structured_only and structured))
    if not has_price:
        if structured:
            return "mismatch", f"페이지 가격 {sorted(structured)[:3]} ≠ 우리 {our_price}"
        return "not_found", f"페이지에서 {our_price:,}원을 찾지 못함"
    if our_original and our_original != our_price:
        if our_original in structured or our_original in amounts:
            return "match", ""
        return "price_only", f"정가 {our_original:,}원은 페이지에 없음"
    return "match", ""


_GONE_TEXT = re.compile(r"(판매\s*(가\s*)?(종료|중지|중단)(된|되었|됨)?|판매하지\s*않는|존재하지\s*않는\s*상품|삭제된\s*상품|"
                        r"상품\s*정보가\s*없|찾을\s*수\s*없는\s*상품|단종)")


def _pid(url: str) -> tuple[str, str]:
    """상품 주소의 (경로, 상품번호 쿼리) — 다른 페이지로 넘어갔는지 비교용."""
    u = urlparse(url)
    q = "&".join(sorted(x for x in (u.query or "").split("&") if re.match(r"(goods|product|item|prd)[_-]?(no|id|code|cd)=", x, re.I)))
    return u.path.rstrip("/").lower(), q


def gone_reason(target: str, final: str, text: str) -> str:
    """판매하지 않는 상품이면 이유, 아니면 ''. 상품 페이지가 홈·목록 등 다른 곳으로 넘어가거나 판매 종료 문구가 있을 때."""
    t_path, t_q = _pid(target)
    f_path, f_q = _pid(final)
    ids = [x.split("=", 1)[1] for x in t_q.split("&") if "=" in x]
    if urlparse(final).netloc and (t_q and t_q != f_q) and not any(i and i in final for i in ids):
        return f"상품 페이지가 열리지 않고 다른 페이지로 이동({final[:80]})"
    if not t_q and f_path in ("", "/", "/index.html", "/main", "/main/index") and t_path not in ("", "/"):
        return f"상품 페이지가 열리지 않고 첫 화면으로 이동"
    head = (text or "")[:1500]
    m = _GONE_TEXT.search(head)
    if m:
        return f"판매 종료 표시: {m.group(0)}"
    return ""


async def _check(ctx, robots: RobotsCache, t: dict, structured_only: bool = False) -> dict:
    row = {"item_key": t["item_key"], "source_id": t.get("source_id"), "kind": t["kind"], "url": t["url"],
           "our_price": t["price"], "our_original": t.get("original_price"), "page_price": None}
    try:
        if not await robots.allowed(t["url"]):
            return dict(row, status="blocked", detail="robots.txt 금지")
        page = await ctx.new_page()
        try:
            resp = await page.goto(t["url"], wait_until="domcontentloaded", timeout=30_000)
            if resp and resp.status >= 400:
                return dict(row, status="blocked", detail=f"HTTP {resp.status}")
            try:
                await page.wait_for_load_state("networkidle", timeout=6_000)
            except Exception:
                pass
            gone = gone_reason(t["url"], page.url, await page.evaluate(
                "() => (document.body ? document.body.innerText : '').slice(0, 4000)"))
            if gone:
                return dict(row, status="not_found", detail=gone)
            data = await page.evaluate("""() => ({
                ld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
                meta: Object.fromEntries([...document.querySelectorAll('meta[property],meta[name],meta[itemprop]')]
                        .map(m => [m.getAttribute('property') || m.getAttribute('name') || m.getAttribute('itemprop'), m.content])),
                ip: [...document.querySelectorAll('[itemprop=price]')].map(e => e.getAttribute('content') || e.textContent).slice(0, 3),
                text: (document.body ? document.body.innerText : '').slice(0, 30000)
            })""")
        finally:
            await page.close()
        meta = dict(data.get("meta") or {})
        for i, v in enumerate(data.get("ip") or []):
            meta[f"itemprop{i}"] = v
        st = structured_prices(data.get("ld") or [], meta)
        st |= {n for k, v in meta.items() if k.startswith("itemprop") and (n := _int(v))}
        status, detail = judge(t["price"], t.get("original_price"), st, data.get("text") or "", structured_only)
        pp = t["price"] if t["price"] in st else (min(st) if st else None)
        return dict(row, page_price=pp, status=status, detail=detail)
    except Exception as e:
        return dict(row, status="blocked", detail=f"{type(e).__name__}: {str(e)[:150]}")


def fetch_targets(sample_per_source: int = 6, sources: list[str] | None = None) -> list[dict]:
    base, h = _sb()
    out: dict[str, dict] = {}
    if not sources:   # 특정 채널만 확인할 때는 추천 상품을 섞지 않는다
        r = httpx.get(base + "/rest/v1/v_picks", params={"select": "item_key,source_id,url,price,original_price"},
                      headers=h, timeout=60)
        r.raise_for_status()
        for x in r.json():
            out.setdefault(x["item_key"], dict(x, kind="pick"))
    if sample_per_source:
        # 화면 관문 때문에 숨겨진 채널(신뢰도 미달)도 다시 검증할 수 있도록 관문 없는 표본 RPC 를 쓴다
        tok = os.environ.get("PROMOHUB_INGEST_TOKEN")
        items: list[dict] = []
        if tok:
            rr = httpx.post(base + "/rest/v1/rpc/verify_sample", headers=h, timeout=60,
                            json={"p_token": tok, "p_per_source": sample_per_source, "p_sources": sources})
            if rr.status_code == 200:
                items = rr.json()
        if not items:
            srcs = httpx.get(base + "/rest/v1/v_sources", params={"select": "id"}, headers=h, timeout=60).json()
            for s in srcs:
                try:
                    rr = httpx.get(base + "/rest/v1/v_items", headers=h, timeout=30, params={
                        "select": "item_key,source_id,url,price,original_price", "source_id": f"eq.{s['id']}",
                        "price": "not.is.null", "limit": "60"})
                    got = [x for x in rr.json() if x.get("url", "").startswith("http")] if rr.status_code == 200 else []
                except Exception:
                    got = []
                items += random.sample(got, min(sample_per_source, len(got)))
        for x in items:
            out.setdefault(x["item_key"], dict(x, kind="sample"))
    return [t for t in out.values() if t.get("url", "").startswith("http") and t.get("price")]


def send(rows: list[dict]) -> int:
    base, h = _sb()
    n = 0
    for i in range(0, len(rows), 200):
        body = {"p_token": os.environ["PROMOHUB_INGEST_TOKEN"], "p_rows": rows[i:i + 200]}
        r = httpx.post(base + "/rest/v1/rpc/record_verifications", content=json.dumps(body, ensure_ascii=False).encode(),
                       headers=h, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"record_verifications 실패: {r.status_code} {r.text[:200]}")
        n += int(r.json() or 0)
    return n


async def verify(targets: list[dict], mobile_sources: set[str] | None = None, budget_s: float = 900,
                 per_host_delay: float = 1.0, structured_sources: set[str] | None = None) -> list[dict]:
    from playwright.async_api import async_playwright
    mobile_sources = mobile_sources or set()
    by_host: dict[str, list[dict]] = defaultdict(list)
    for t in targets:
        by_host[urlparse(t["url"]).netloc].append(t)
    results: list[dict] = []
    t0 = time.monotonic()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        sem = asyncio.Semaphore(8)   # 동시에 여는 쇼핑몰 수

        async def host_worker(host: str, items: list[dict]):
            mobile = any(i.get("source_id") in mobile_sources for i in items)
            async with sem:
                ctx = await browser.new_context(
                    user_agent=MOBILE_UA if mobile else DESKTOP_UA, locale="ko-KR", timezone_id="Asia/Seoul",
                    **({"viewport": {"width": 390, "height": 844}, "is_mobile": True} if mobile else {"viewport": {"width": 1440, "height": 900}}))
                await ctx.route("**/*", _block_heavy)
                robots = RobotsCache(ctx)
                try:
                    for t in items:           # 같은 쇼핑몰은 한 번에 하나씩, 간격을 두고
                        if time.monotonic() - t0 > budget_s:
                            results.append({**{k: t.get(k) for k in ("item_key", "source_id", "kind", "url")},
                                            "our_price": t["price"], "our_original": t.get("original_price"),
                                            "page_price": None, "status": "blocked", "detail": "시간 예산 초과"})
                            continue
                        results.append(await _check(ctx, robots, t, t.get("source_id") in (structured_sources or set())))
                        await asyncio.sleep(per_host_delay)
                finally:
                    await ctx.close()

        await asyncio.gather(*(host_worker(h, its) for h, its in by_host.items()))
        await browser.close()
    return results


def summarize(rows: list[dict]) -> dict:
    s: dict = {"total": len(rows)}
    for r in rows:
        s[r["status"]] = s.get(r["status"], 0) + 1
    by_src: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_src[r.get("source_id") or "?"][r["status"]] += 1
    s["bad_sources"] = {k: dict(v) for k, v in by_src.items() if v.get("mismatch", 0) + v.get("not_found", 0) > 0}
    return s
