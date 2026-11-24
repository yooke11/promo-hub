from datetime import date
from pathlib import Path

from promohub.config import load_config
from promohub.extract import extract_detail_meta, extract_from_html, extract_from_json, merge
from promohub.normalize import normalize
from promohub.store import Store

FX = Path(__file__).parent / "fixtures"
CFG = load_config()
REF = date(2026, 11, 24)


def test_dom_extraction_gmarket():
    src = CFG.get("gmarket")
    raws = extract_from_html((FX / "gmarket_main.html").read_text(), "https://m.gmarket.co.kr/", src)
    raws = merge(raws)
    by = {r.url.split("?")[0].rsplit("/", 1)[-1]: r for r in raws}
    # 상품 상세·로그인·장바구니는 제외
    assert all("goodscode" not in r.url and "login" not in r.url for r in raws)
    assert len(raws) == 3, [r.url for r in raws]

    big = by["tab1"]
    assert big.title == "빅스마일데이 최대 70% 할인"
    assert big.image_url.startswith("https://image.gmarket.co.kr/")
    assert "11.20" in big.period_text

    outer = by["winter-outer"]
    assert outer.title.startswith("겨울 아우터 기획전")   # '더보기' 링크보다 긴 제목 유지
    assert outer.image_url.endswith("/img/outer.jpg")

    roulette = by["lucky-roulette"]
    assert "룰렛" in roulette.title                         # alt='배너' 는 버리고 카드 텍스트 사용
    p = normalize(roulette, REF)
    assert p.kind == "이벤트" and p.end_date == date(2026, 12, 31)


def test_json_extraction_musinsa():
    src = CFG.get("musinsa")
    raws = extract_from_json((FX / "musinsa_banners.json").read_bytes(), "https://www.musinsa.com/api/main", src)
    titles = sorted(r.title for r in raws)
    assert titles == ["러닝 페어", "무진장 겨울 블랙프라이데이"]   # /products/ 는 제외
    promos = {p.title: p for p in (normalize(r, REF) for r in raws)}
    mj = promos["무진장 겨울 블랙프라이데이"]
    assert (mj.start_date, mj.end_date) == (date(2026, 11, 20), date(2026, 12, 4))
    assert mj.category == "시즌·대형행사" and mj.max_discount == 80
    run = promos["러닝 페어"]
    assert run.end_date == date(2026, 12, 7) and run.category == "스포츠·레저"
    assert run.url == "https://www.musinsa.com/campaign/runningfair"


def test_detail_meta():
    html = """<html><head><meta property="og:title" content="연말 홈파티 식품 기획전 | GS SHOP">
    <meta property="og:image" content="/img/party.jpg"></head>
    <body><div>행사기간 2026.12.01(월) ~ 2026.12.24(수)</div></body></html>"""
    m = extract_detail_meta(html, "https://www.gsshop.com/shop/event/1")
    assert m["title"] == "연말 홈파티 식품 기획전"
    assert m["image_url"] == "https://www.gsshop.com/img/party.jpg"
    assert "2026.12.01" in m["period_text"]


def test_store_roundtrip(tmp_path):
    st = Store(tmp_path / "t.db")
    st.upsert_source("musinsa", "무신사", "mall")
    src = CFG.get("musinsa")
    raws = extract_from_json((FX / "musinsa_banners.json").read_bytes(), "https://www.musinsa.com/", src)
    promos = [normalize(r, REF) for r in raws]
    assert st.upsert_promotions(promos) == 2
    assert st.upsert_promotions(promos) == 0          # 재수집 시 중복 생성 안 됨
    items = st.query(include_ended=True)
    assert len(items) == 2 and items[0]["source_name"] == "무신사"
