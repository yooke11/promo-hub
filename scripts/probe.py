"""진단용: 기획전 상세 페이지를 수집기와 같은 방식으로 열어 HTML·JSON 응답·상품 추출 결과를 probe_out/ 에 저장.
사용: python scripts/probe.py "채널id=URL" ... (GitHub Actions probe.yml 에서 실행, 결과는 아티팩트)"""
import asyncio, json, sys, os, re, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promohub.config import load_config
from promohub.collector import RobotsCache, _new_context, _auto_scroll
from promohub.products import drop_bare, fill_from_page, products_from_html, products_from_json, products_from_jsonld, merge_products
from playwright.async_api import async_playwright
OUT = "probe_out"
os.makedirs(OUT, exist_ok=True)
async def one(sid, url, n):
    c = load_config(); src = next(s for s in c.sources if s.id == sid) if any(s.id==sid for s in c.sources) else None
    if src is None:
        src = next(s for s in load_config("config/candidates.yaml").sources if s.id == sid)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await _new_context(b, src.mobile); page = await ctx.new_page()
        if not await RobotsCache(ctx).allowed(url):
            print(f"{sid}_{n} robots 비허용 — 건너뜀"); await b.close(); return
        js = []
        async def on(r):
            try:
                if r.request.resource_type in ("xhr","fetch") and "json" in r.headers.get("content-type",""):
                    js.append((r.url, await r.body()))
            except Exception: pass
        page.on("response", lambda r: asyncio.ensure_future(on(r)))
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try: await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception: pass
        await _auto_scroll(page, 3)
        html = await page.content()
        tag = f"{sid}_{n}"
        await page.screenshot(path=f"{OUT}/{tag}.png", full_page=False)
        open(f"{OUT}/{tag}.html","w").write(html)
        with open(f"{OUT}/{tag}.json","w") as f:
            for u, body in js: f.write(json.dumps({"url":u,"body":body.decode("utf-8","replace")[:200000]}, ensure_ascii=False)+"\n")
        ld = products_from_jsonld(html, page.url); dom = products_from_html(html, page.url, src.product_pats, src.product_link)
        jl = [products_from_json(bd, u, src.product_link) for u, bd in js]
        m = merge_products([ld, dom] + jl, src.product_limit)
        fill_from_page(m, html, page.url, src.product_pats); m = drop_bare(m)
        print(tag, "final", page.url, "ld", len(ld), "dom", len(dom), "json", sum(map(len, jl)), "kept", len(m), "json_resp", len(js))
        for p in m[:8]: print("  ", p.name[:40], "|", p.price, p.original_price, "|", (p.url or "")[:70], "|", (p.image_url or "")[:60])
        await b.close()

async def main(args):
    for n, a in enumerate(args):
        sid, url = a.split("=", 1)
        try:
            await one(sid.strip(), url.strip(), n)
        except Exception as e:
            print(sid, "ERROR", repr(e)[:200])

if __name__ == "__main__":
    args = [x for a in sys.argv[1:] for x in a.split()]
    asyncio.run(main(args))
