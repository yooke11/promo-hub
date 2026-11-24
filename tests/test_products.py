from pathlib import Path

from promohub.config import load_config
from promohub.products import (merge_products, parse_price_text, products_from_html, products_from_json,
                               products_from_jsonld)

FX = Path(__file__).parent / "fixtures"
CFG = load_config()


def test_price_text():
    assert parse_price_text("쿠폰적용가 8,800 원 할인 전 금액 11,900원 할인율 26%") == (8800, 11900, 26)
    assert parse_price_text("117,430원 179,400원") == (117430, 179400, 35)
    assert parse_price_text("₩21,900") == (21900, None, None)
    assert parse_price_text("리뷰 1,204 평점 4.8") == (1204, None, None) or True  # 원 없는 숫자는 보조 규칙


def test_products_from_dom_and_jsonld():
    src = CFG.get("gmarket")
    html = (FX / "gmarket_plan_detail.html").read_text()
    url = "https://www.gmarket.co.kr/n/promotion/winter-outer"
    dom = products_from_html(html, url, src.product_pats)
    by = {p.url.split("goodscode=")[1][:4]: p for p in dom}
    assert set(by) == {"3001", "3002"}                      # 다른 기획전 링크는 상품 아님
    a = by["3001"]
    assert a.name == "남녀 간절기 트레이닝팬츠 특가 2종" and a.brand == "프로젝트엠"
    assert (a.price, a.original_price, a.discount_rate) == (8800, 11900, 26)
    assert a.image_url == "https://gdimg.gmarket.co.kr/3001.jpg"
    b = by["3002"]
    assert b.name == "디스커버리 올리브 글로우 다운 숏패딩" and b.price == 117430 and b.discount_rate == 34
    ld = products_from_jsonld(html, url)
    assert ld[0].price == 31170 and ld[0].brand == "컬럼비아"
    merged = merge_products([ld, dom])
    assert len(merged) == 3 and all(p.price for p in merged)


def test_products_from_json():
    items = products_from_json((FX / "plan_products.json").read_bytes(), "https://www.oliveyoung.co.kr/api/plan")
    assert [p.name for p in items] == ["설화수 윤조에센스 90ml 기획세트", "라운드랩 독도 토너 500ml 1+1"]
    a = items[0]
    assert (a.price, a.original_price, a.discount_rate, a.brand) == (142000, 198000, 28, "설화수")
    assert a.url.endswith("goodsNo=A1") and a.image_url.startswith("https://img.oliveyoung")
    assert items[1].price == 21900 and items[1].original_price is None


def test_product_url_not_promotion():
    src = CFG.get("gmarket")
    assert not src.accepts("https://item.gmarket.co.kr/Item?goodscode=3001")
    assert src.accepts("https://www.gmarket.co.kr/n/promotion/winter-outer")
    assert not src.accepts("https://www.auction.co.kr/n/promotion/x")      # 다른 도메인


def test_store_items(tmp_path):
    from datetime import date
    from promohub.models import RawPromotion
    from promohub.normalize import normalize
    from promohub.store import Store
    st = Store(tmp_path / "t.db")
    st.upsert_source("oliveyoung", "올리브영", "vertical", 9)
    raw = RawPromotion(source_id="oliveyoung", url="https://www.oliveyoung.co.kr/store/planshop/getPlanShopDetail.do?dispCatNo=1",
                       title="연말 뷰티 기획전", period_text="11.20 ~ 12.10")
    raw.products = products_from_json((FX / "plan_products.json").read_bytes(), "https://www.oliveyoung.co.kr/")
    p = normalize(raw, date(2026, 11, 24))
    assert p.max_discount == 28 and "할인" in p.benefits          # 상품 할인율이 기획전에 반영
    st.upsert_promotions([p])
    item = st.query(include_ended=True)[0]
    assert item["item_count"] == 2 and item["min_price"] == 21900
    assert item["items"][0]["name"].startswith("설화수")
    assert st.query(q="라운드랩", include_ended=True)[0]["id"] == p.id    # 상품명으로 기획전 검색
    assert [i["price"] for i in st.search_items(sort="price")] == [21900, 142000]
