from promohub.keywords import Keyword, enrich, generate, product_head, product_type, to_rows

PROMO = {"title": "겨울 아우터 기획전 최대 34%", "category": "패션", "benefits": ["할인", "쿠폰"], "max_discount": 34}
ITEMS = [{"name": "디스커버리 올리브 글로우 다운 숏패딩", "brand": "디스커버리"},
         {"name": "컬럼비아 플리스 자켓 WE3220", "brand": "컬럼비아"},
         {"name": "디스커버리 여성 롱패딩", "brand": "디스커버리"}]


def test_product_type():
    assert product_type("라운드랩 독도 토너 500ml 1+1") == "독도 토너"
    assert product_type("디스커버리 올리브 글로우 다운 숏패딩") == "숏패딩"
    assert product_head("디스커버리 여성 롱패딩") == "패딩"
    assert product_type("무선 청소기 X9") == "무선 청소기"


def test_generate_rules():
    kws = generate(PROMO, ITEMS, "G마켓")
    words = [k.keyword for k in kws[:10]]
    assert "패딩 할인" in words                    # 숏·롱패딩 공통 품목
    assert "디스커버리 숏패딩" in words or "디스커버리 롱패딩" in words
    assert "겨울 패딩" in words                    # 시즌 키워드
    assert len({k.keyword.replace(" ", "") for k in kws}) == len(kws)   # 중복 없음


def test_generate_without_items():
    kws = generate({"title": "11월 올영신상위크 선착순 쿠폰 이벤트", "benefits": ["쿠폰"]}, [], "올리브영")
    words = [k.keyword for k in kws]
    assert "올리브영 올영신상위크" in words and not any("최저가" in w for w in words)


def test_enrich_with_volume():
    cands = generate(PROMO, ITEMS, "G마켓")
    rows = [{"relKeyword": "패딩할인", "monthlyPcQcCnt": 1200, "monthlyMobileQcCnt": 8800, "compIdx": "높음"},
            {"relKeyword": "겨울패딩", "monthlyPcQcCnt": 9000, "monthlyMobileQcCnt": 52000, "compIdx": "높음"},
            {"relKeyword": "디스커버리숏패딩", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 20, "compIdx": "낮음"},
            {"relKeyword": "여성롱패딩", "monthlyPcQcCnt": 3000, "monthlyMobileQcCnt": 21000, "compIdx": "중간"}]
    out = enrich(cands, rows, ["패딩"], 10)
    assert out[0].keyword in ("겨울 패딩", "패딩 할인") and out[0].volume >= 10000
    assert any(k.keyword == "여성롱패딩" and k.kind == "related" for k in out)    # 연관 키워드 보강
    rows_ = to_rows("p1", out)
    assert rows_[0]["rank"] == 1 and rows_[0]["kind_label"]
