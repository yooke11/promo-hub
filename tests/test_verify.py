from promohub.verify import judge, structured_prices, text_amounts


def test_structured_jsonld_and_meta():
    ld = ['{"@context":"https://schema.org","@type":"Product","offers":{"@type":"Offer","price":"15990","priceCurrency":"KRW"}}']
    assert structured_prices(ld, {"product:price:amount": "15,990"}) == {15990}


def test_judge_match_and_price_only():
    assert judge(13500, 27000, set(), "정가 27,000원 판매가 13,500원")[0] == "match"
    assert judge(13500, 27000, {13500}, "13,500원")[0] == "price_only"
    assert judge(15990, None, {15990}, "")[0] == "match"


def test_judge_mismatch_unit_price():
    # 코스트코 사례: 우리가 824원으로 잘못 읽었다면 페이지 구조화 가격 15,990원과 달라 mismatch
    assert judge(824, 15990, {15990}, "15,990원 100mℓ당 824원")[0] == "mismatch"
    assert judge(824, None, {15990}, "15,990원")[0] == "mismatch"
    assert judge(5000, 14990, set(), "14,990원 9,990원")[0] == "not_found"


def test_text_amounts():
    assert text_amounts("1,234원 / 56,000원 / 2026.11.26") >= {1234, 56000}


def test_structured_only_ignores_other_card_prices():
    # 코오롱몰: 추천 상품 카드의 쿠폰가 63,500원이 본문에 있어도 판매가(JSON-LD)는 74,700원
    assert judge(63500, None, {74700}, "74% 63,500원 249,000원")[0] == "match"
    assert judge(63500, None, {74700}, "74% 63,500원 249,000원", structured_only=True)[0] == "mismatch"
    assert judge(74700, None, {74700}, "", structured_only=True)[0] == "match"
