"""로컬 JS 렌더링 사이트로 Playwright 수집 파이프라인 전체를 검증 (브라우저 미설치 시 skip)."""
import asyncio
import functools
import http.server
import threading
from pathlib import Path

import pytest

from promohub.config import load_config
from promohub.normalize import normalize

pw = pytest.importorskip("playwright.async_api")
HERE = Path(__file__).parent
PORT = 8765


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE / "e2e_site"))
    handler.log_message = lambda *a, **k: None
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    except OSError:
        yield  # 이미 떠 있음
        return
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield
    srv.shutdown()


def test_collect_js_site(site):
    from promohub.collector import collect_source
    src = load_config(HERE / "e2e_sources.yaml").get("testmall")

    async def go():
        async with pw.async_playwright() as p:
            try:
                b = await p.chromium.launch()
            except Exception as e:
                pytest.skip(f"chromium 없음: {e}")
            try:
                return await collect_source(b, src)
            finally:
                await b.close()

    promos = {p.title: p for p in (normalize(r) for r in asyncio.run(go())) if p}
    assert "연말 가전 기획전 최대 40%" in promos            # JSON에서 제목 확보(DOM alt='배너')
    assert promos["연말 가전 기획전 최대 40%"].end_date.isoformat() == "2026-12-15"
    food = promos["홈파티 식품전"]
    assert food.end_date.isoformat() == "2026-12-24"       # 상세 페이지에서 기간 보강
    # 기획전 안의 판매 상품: DOM 카드(정적) + JS로 그린 목록(JSON 응답) 모두
    f = {p.name: p for p in food.products}
    assert f["한우 1++ 등심 300g"].price == 39900 and f["한우 1++ 등심 300g"].original_price == 49900
    assert f["와인 3종 세트"].price == 59000
    g = {p.name: p for p in promos["연말 가전 기획전 최대 40%"].products}
    assert g["무선 청소기 X9"].price == 299000 and g["무선 청소기 X9"].original_price == 459000
    assert g["무선 청소기 X9"].url.endswith("/goods/g1.html")   # DOM 링크와 JSON 정보가 합쳐짐
