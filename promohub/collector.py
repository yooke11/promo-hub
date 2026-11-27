"""Playwright 수집기: 채널 진입 페이지를 실제 브라우저로 열어 DOM 링크와 JSON 응답을 함께 수집."""
from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import Browser, BrowserContext, Response, async_playwright

from .config import Config, Source
from .extract import apply_detail, extract_detail_meta, extract_from_html, extract_from_json, merge, needs_detail
from .models import RawPromotion
from .normalize import is_mall_name, normalize
from .products import fix_discount_amounts, fix_shared_images, fix_unit_prices
from .products import drop_bare, fill_from_page, merge_products, products_from_html, products_from_json, products_from_jsonld
from .store import Store

log = logging.getLogger("promohub")

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
MAX_JSON_BYTES = 3_000_000


class RobotsCache:
    def __init__(self, ctx: BrowserContext):
        self.ctx = ctx
        self.cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = RobotFileParser()
            try:
                r = await self.ctx.request.get(base + "/robots.txt", timeout=10_000)
                rp.parse((await r.text()).splitlines() if r.ok else [])
                self.cache[base] = rp
            except Exception:
                self.cache[base] = None  # 읽을 수 없으면 허용으로 간주
        rp = self.cache[base]
        return True if rp is None else rp.can_fetch("*", url)


# 이미지·동영상·글꼴 파일은 내려받지 않는다(주소는 HTML 속성에 그대로 남으므로 수집에는 영향 없음).
# 상대 쇼핑몰 서버 부담과 수집 시간을 크게 줄인다. 2026-11-26
BLOCK_TYPES = {"image", "media", "font"}


async def _block_heavy(route):
    if route.request.resource_type in BLOCK_TYPES:
        await route.abort()
    else:
        await route.continue_()


async def _new_context(browser: Browser, mobile: bool, block: bool = True) -> BrowserContext:
    if mobile:
        ctx = await browser.new_context(user_agent=MOBILE_UA, viewport={"width": 390, "height": 844},
                                        is_mobile=True, has_touch=True, locale="ko-KR", timezone_id="Asia/Seoul")
    else:
        ctx = await browser.new_context(user_agent=DESKTOP_UA, viewport={"width": 1440, "height": 900},
                                        locale="ko-KR", timezone_id="Asia/Seoul")
    if block:
        await ctx.route("**/*", _block_heavy)
    return ctx


async def _auto_scroll(page, steps: int):
    for _ in range(steps):
        await page.mouse.wheel(0, 2200)
        await page.wait_for_timeout(700 + random.randint(0, 400))


async def collect_source(browser: Browser, source: Source, diag: dict | None = None) -> list[RawPromotion]:
    """diag: 진단 정보(진입 페이지 상태·제목·링크 수·JSON 수, 상세별 상품 수)를 채워 줌 → crawl_runs.diag 저장."""
    diag = diag if diag is not None else {}
    diag.setdefault("entries", []); diag.setdefault("details", [])
    ctx = await _new_context(browser, source.mobile)
    robots = RobotsCache(ctx)
    raws: list[RawPromotion] = []
    json_payloads: list[tuple[str, bytes]] = []
    bucket = {"cur": json_payloads}   # 응답을 담을 현재 버킷(진입 페이지 / 상세 페이지별)

    async def on_response(resp: Response):
        try:
            ct = resp.headers.get("content-type", "")
            if resp.request.resource_type in ("xhr", "fetch") and "json" in ct:
                body = await resp.body()
                if len(body) < MAX_JSON_BYTES:
                    bucket["cur"].append((resp.url, body))
        except Exception:
            pass

    page = await ctx.new_page()
    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
    try:
        for entry in source.entry_urls:
            if source.respect_robots and not await robots.allowed(entry):
                log.warning("[%s] robots.txt 비허용: %s", source.id, entry)
                diag["entries"].append({"url": entry, "robots": "disallow"})
                continue
            ent = {"url": entry}
            diag["entries"].append(ent)
            try:
                n_json_before = len(json_payloads)
                resp = await page.goto(entry, wait_until="domcontentloaded", timeout=45_000)
                ent["status"] = resp.status if resp else None
                try:
                    await page.wait_for_load_state("networkidle", timeout=12_000)
                except Exception:
                    pass
                await _auto_scroll(page, source.scroll_steps)
                html = await page.content()
                found = extract_from_html(html, page.url, source)
                log.info("[%s] DOM %d건 ← %s", source.id, len(found), entry)
                raws += found
                ent.update(final=page.url[:200], title=(await page.title())[:80], html=len(html),
                           links=html.count("<a "), dom=len(found), json=len(json_payloads) - n_json_before,
                           text=(await page.evaluate("document.body ? document.body.innerText.slice(0,160) : ''")).replace("\n", " "))
            except Exception as e:
                log.warning("[%s] 진입 실패 %s: %s", source.id, entry, e)
                ent["error"] = repr(e)[:200]
            await asyncio.sleep(source.delay_sec)

        n_json_promos = 0
        for url, body in json_payloads:
            got = extract_from_json(body, url, source)
            n_json_promos += len(got)
            raws += got
        diag["json_promos"] = n_json_promos
        log.info("[%s] JSON 응답 %d개 분석, 누적 후보 %d", source.id, len(json_payloads), len(raws))

        merged = merge(raws)
        # 상세 페이지 방문: 기간·이미지 보강 + 기획전에 담긴 상품(이미지·이름·가격) 수집
        todo = sorted(merged, key=lambda r: not needs_detail(r))[: source.detail_limit]
        for r in todo:
            if source.respect_robots and not await robots.allowed(r.url):
                continue
            detail_json: list[tuple[str, bytes]] = []
            bucket["cur"] = detail_json
            try:
                resp = await page.goto(r.url, wait_until="domcontentloaded", timeout=30_000)
                if resp is not None and resp.status in (404, 410):
                    r.dead = True        # 열리지 않는 기획전 링크는 싣지 않는다
                    log.info("[%s] 링크 없음(%d) 제외: %s", source.id, resp.status, r.url)
                    continue
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                await _auto_scroll(page, 3)          # 지연 로딩 상품 목록
                html = await page.content()
                apply_detail(r, extract_detail_meta(html, page.url))
                lists = [products_from_jsonld(html, page.url),
                         products_from_html(html, page.url, source.product_pats, source.product_link)]
                lists += [products_from_json(body, u, source.product_link) for u, body in detail_json]
                r.products = merge_products(lists, source.product_limit)
                fill_from_page(r.products, html, page.url, source.product_pats)   # JSON 상품의 이미지·주소를 페이지 <img alt> 로 보충
                r.products = drop_bare(r.products)
                log.info("[%s] 상품 %d개 ← %s", source.id, len(r.products), r.title[:30])
                if len(diag["details"]) < 12:
                    diag["details"].append({"url": page.url[:160], "ld": len(lists[0]), "dom": len(lists[1]),
                        "json": sum(len(x) for x in lists[2:]), "json_resp": len(detail_json), "kept": len(r.products),
                        "links": html.count("<a ")})
            except Exception as e:
                log.debug("[%s] 상세 실패 %s: %s", source.id, r.url, e)
                if len(diag["details"]) < 12:
                    diag["details"].append({"url": r.url[:160], "error": repr(e)[:160]})
            await asyncio.sleep(source.delay_sec)
        if source.price_from_detail:
            diag["detail_price"] = await _confirm_detail_prices(page, robots, source, merged)
        return merged
    finally:
        await ctx.close()


def detail_price(p, structured: set[int], amounts: set[int]) -> bool:
    """상품 상세 페이지의 판매가로 p 를 고친다. 판매가를 하나로 정할 수 없으면 False(버림).
    목록에 보이는 쿠폰·회원·카드가 대신, 조건 없이 누구나 내는 상세 페이지 가격을 쓴다."""
    if not structured:
        return False
    if p.price not in structured:
        if len(structured) != 1:
            return False
        p.price = next(iter(structured))
    orig = p.original_price
    if not orig or orig <= p.price or (orig not in amounts and orig not in structured):
        orig = None
    p.original_price = orig
    p.discount_rate = round((orig - p.price) * 100 / orig) if orig else None
    return True


async def _confirm_detail_prices(page, robots, source: Source, promos) -> dict:
    from .verify import structured_prices, text_amounts
    seen: dict[str, tuple[set[int], set[int]] | None] = {}
    st = {"checked": 0, "kept": 0, "dropped": 0}
    for r in promos:
        keep = []
        for p in r.products or []:
            if not p.url or p.price is None:
                st["dropped"] += 1
                continue
            if p.url not in seen:
                if len(seen) >= source.detail_price_limit or (source.respect_robots and not await robots.allowed(p.url)):
                    seen[p.url] = None
                else:
                    try:
                        await page.goto(p.url, wait_until="domcontentloaded", timeout=25_000)
                        try:
                            await page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=6_000)
                        except Exception:
                            pass
                        data = await page.evaluate("""() => ({
                            ld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
                            meta: Object.fromEntries([...document.querySelectorAll('meta[property],meta[name],meta[itemprop]')]
                                    .map(m => [m.getAttribute('property') || m.getAttribute('name') || m.getAttribute('itemprop'), m.content])),
                            text: (document.body ? document.body.innerText : '').slice(0, 30000)})""")
                        seen[p.url] = (structured_prices(data.get("ld") or [], data.get("meta") or {}),
                                       text_amounts(data.get("text") or ""))
                        st["checked"] += 1
                    except Exception as e:
                        log.debug("[%s] 상품 가격 확인 실패 %s: %s", source.id, p.url, e)
                        seen[p.url] = None
                    await asyncio.sleep(max(1.0, source.delay_sec / 2))
            got = seen[p.url]
            if got and detail_price(p, *got):
                keep.append(p)
                st["kept"] += 1
            else:
                st["dropped"] += 1
        r.products = keep
    log.info("[%s] 상세 가격 확인 %s", source.id, st)
    return st


async def run(config: Config, store: Store | None, only: list[str] | None = None, headless: bool = True,
              sink=None, shard: tuple[int, int] | None = None, config_name: str = "sources.yaml") -> dict:
    """store: 로컬 SQLite(없으면 생략), sink: RemoteSink(Supabase). shard=(i, n)이면 순위순 채널 중 i번째 묶음만."""
    from datetime import datetime, timezone
    from .remote import build_payload
    summary = {}
    targets = [s for s in config.sources if s.enabled and (not only or s.id in only)]
    if shard:
        i, n = shard
        targets = [s for k, s in enumerate(targets) if k % n == i]   # 순위가 섞이도록 라운드로빈 분배
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            for src in targets:
                started = datetime.now(timezone.utc)
                run_id = None
                if store:
                    store.upsert_source(src.id, src.name, src.channel_type, src.rank)
                    run_id = store.start_run(src.id)
                # 어떤 설정으로 돈 수집인지 기록 → 웹은 운영 설정(sources.yaml) 수집 채널만 보여 준다(후보 시험 수집 제외)
                diag: dict = {"config": config_name}
                try:
                    raws = await collect_source(browser, src, diag)
                    promos = [p for p in (normalize(r) for r in raws) if p and not is_mall_name(p.title, src.name)]
                    diag["raw"] = len(raws)
                    diag["shared_img_fixed"] = fix_shared_images([x for p in promos for x in p.products])
                    diag["unit_price_fixed"] = fix_unit_prices([x for p in promos for x in p.products])
                    if src.discount_amount_round:
                        diag["discount_amount_fixed"] = fix_discount_amounts([x for p in promos for x in p.products])
                    if src.pct_needs_original:
                        for x in (x for p in promos for x in p.products):
                            if not x.original_price:
                                x.discount_rate = None
                    new = store.upsert_promotions(promos) if store else 0
                    if sink:
                        new = sink.send(build_payload(src, promos, started, diag=diag))
                    if store:
                        store.finish_run(run_id, len(promos), new, True)
                    n_items = sum(len(p.products) for p in promos)
                    summary[src.id] = {"found": len(promos), "new": new, "items": n_items}
                    log.info("[%s] 저장 기획전 %d건(신규 %d) · 상품 %d개", src.id, len(promos), new, n_items)
                except Exception as e:
                    if store and run_id:
                        store.finish_run(run_id, 0, 0, False, repr(e))
                    if sink:
                        try:
                            sink.send(build_payload(src, [], started, ok=False, error=repr(e), diag=diag))
                        except Exception:
                            pass
                    summary[src.id] = {"error": repr(e)}
                    log.exception("[%s] 수집 실패", src.id)
        finally:
            await browser.close()
    return summary
