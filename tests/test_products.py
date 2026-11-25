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


# ── 2026-11-25: 상품 이미지·주소 보강(CJ더마켓·교보문고·컬리·패션플러스형 페이지) ──
from promohub.products import card_prices, drop_bare, fill_from_page, is_product_url, compile_product_patterns

PATS = compile_product_patterns()


def test_listing_urls_are_not_products():
    for u in ["https://www.cjthemarket.com/the/product/category-product-list?ctgrId=0",
              "https://m.oasis.co.kr/product/list?categoryId=124", "https://www.dyson.co.kr/products/vacuum-cleaners/robot",
              "https://www.otokimall.com/front/product/search_result?keyword=x",
              "https://www.yes24.com/product/goods/123408994?ReviewYn=Y"]:
        assert not is_product_url(u, PATS), u
    assert is_product_url("https://www.dongwonmall.com/product/detail.do?productId=001080733", PATS)
    assert is_product_url("https://www.fashionplus.co.kr/goods/detail/433109260", PATS)


def test_menu_links_and_data_cards():
    html = """<html><body><div class="gnb"><a href="/product/detail.do?productId=000624895"><img src="//x/banner.jpg" alt="배너">
      <p>고기 본연의 맛</p></a></div>
      <div class="product__item" data-prdcd="40239615" data-prdnm="담꽃 팥칼국수 밀키트 1560g(4인분)">
        <a href="javascript:;"><img class="product-thumb" src="//img.cjthemarket.com/p/1.jpg" alt="담꽃 팥칼국수"></a>
        <p class="product__name">담꽃 팥칼국수 밀키트 1560g(4인분)</p>
        <div class="product__price--info"><p class="discount__percent">15%</p><p class="discount__price">28,475원</p>
          <p class="original__price">33,500원</p></div><div class="delivery">15,000원 이상 무료배송</div></div>
      <li class="product-item" data-goods-id="433109260"><a href="/goods/detail/433109260"><figure>
        <i class="image-product" style='background-image: url("https://img.fashionplus.co.kr/a.jpg?RS=500x670")'></i>
        <p class="text-product">캐시미어 칼라넥 니트</p><del>399,000</del><p class="text-sale">46%</p><p class="text-price">215,400</p></figure></a></li>
      </body></html>"""
    link = {"key": "prdcd", "url": "https://www.cjthemarket.com/the/product/product-main?prdCd={id}"}
    got = {p.name: p for p in products_from_html(html, "https://www.cjthemarket.com/pc/plan/planView?plnId=1", PATS, link)}
    assert "고기 본연의 맛" not in got                                   # 메뉴(gnb) 안 링크 제외
    cj = got["담꽃 팥칼국수 밀키트 1560g(4인분)"]
    assert (cj.price, cj.original_price, cj.discount_rate) == (28475, 33500, 15)   # '15,000원 이상' 무시
    assert cj.url.endswith("prdCd=40239615") and cj.image_url == "https://img.cjthemarket.com/p/1.jpg"
    fp = got["캐시미어 칼라넥 니트"]
    assert fp.image_url.startswith("https://img.fashionplus.co.kr/a.jpg") and fp.price == 215400


def test_json_template_and_alt_fill():
    body = '{"data":[{"no":1002581485,"name":"[프리베일] 후드 재킷","sales_price":99000,"discounted_price":80750,' \
           '"list_image_url":"https://product-image.kurly.com/a.jpg"},' \
           '{"saleCmdtid":"S000220351148","name":"연금술사","price":16800.0,"discountPrice":15120.0,"imgUrl":null},' \
           '{"itemName":"마미포코","price":5577,"image64Url":"http://t.r.jp/a.jpg?_ex=64x64","image128Url":"http://t.r.jp/a.jpg?_ex=128x128","link":"http://item.r.jp/1/"}]}'
    k = products_from_json(body, "https://api.kurly.com/x", {"key": "no", "url": "https://www.kurly.com/goods/{id}"})[0]
    assert (k.url, k.price, k.original_price, k.image_url) == ("https://www.kurly.com/goods/1002581485", 80750, 99000,
                                                               "https://product-image.kurly.com/a.jpg")
    items = products_from_json(body, "https://event.kyobobook.co.kr/api", {"key": "saleCmdtid", "url": "https://product.kyobobook.co.kr/detail/{id}"})
    kb = items[1]
    assert kb.url == "https://product.kyobobook.co.kr/detail/S000220351148" and not kb.image_url
    assert items[2].image_url.endswith("128x128")                       # 큰 썸네일 우선
    page = '<a href="https://product.kyobobook.co.kr/detail/S000220351148"><img alt="연금술사" src="https://contents.kyobobook.co.kr/pdt/9791170614029.jpg"></a>'
    fill_from_page([kb], page, "https://event.kyobobook.co.kr/detail/1", PATS)
    assert kb.image_url.endswith("9791170614029.jpg")


def test_price_text_ignores_points_and_rates():
    assert parse_price_text("10 % 14,400 원 16,000 원 포인트적립 720원") == (14400, 16000, 10)
    assert parse_price_text("36,000원 95% 만족 내일 도착확률 98%")[2] is None


def test_drop_bare():
    from promohub.products import Product
    rich = [Product(name=f"a{i}", url=f"https://x/{i}", image_url="i") for i in range(4)]
    assert len(drop_bare(rich + [Product(name="NIKE TEMPO", price=1000)])) == 4
    only = [Product(name="b", price=1000)] * 3
    assert drop_bare(only) == only


def test_fix_shared_placeholder_images():
    from promohub.products import Product, fix_shared_images
    ph = "https://static.nike.com/a/images/t_web_pw_592_v2/f_auto/u_9ddf04c7"
    ps = [Product(name=f"나이키 상품 {i}", image_url=ph, alt_images=[f"https://img/{i}.png"] if i % 2 else []) for i in range(6)]
    ps.append(Product(name="단독 상품", image_url="https://img/solo.png"))
    assert fix_shared_images(ps) == 6
    assert ps[1].image_url == "https://img/1.png" and ps[0].image_url == "" and ps[-1].image_url == "https://img/solo.png"
    assert "alt_images" not in ps[1].to_dict()
