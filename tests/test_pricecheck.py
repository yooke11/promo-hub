from promohub.pricecheck import clean_query, evaluate, match_score, same_mall

T = {"item_key": "k1", "name": "[단독] 라운드랩 독도 토너 500ml 1+1 기획", "brand": "라운드랩", "price": 21900,
     "source_id": "oliveyoung", "source_name": "올리브영"}


def items(*rows):
    return [{"title": t, "lprice": str(p), "mallName": m, "link": f"https://x/{i}"} for i, (t, p, m) in enumerate(rows)]


def test_clean_query():
    assert clean_query(T["name"], T["brand"]) == "라운드랩 독도 토너 500ml 1 1"


def test_match_units():
    assert match_score("독도 토너 500ml", "라운드랩 <b>독도</b> 토너 500ml") > 0.8
    assert match_score("독도 토너 500ml", "라운드랩 독도 토너 200ml") == 0.0      # 용량 다르면 다른 상품
    assert match_score("독도 토너 500ml", "토리든 다이브인 세럼") < 0.3


def test_evaluate_lowest_excluding_same_mall():
    r = evaluate(T, items(
        ("라운드랩 독도 토너 500ml 1+1", 19800, "올리브영"),       # 같은 쇼핑몰 → 제외
        ("라운드랩 독도 토너 500ml 1+1 기획세트", 23500, "11번가"),
        ("라운드랩 독도 토너 500ml 1+1", 22900, "쿠팡"),
        ("라운드랩 독도 토너 200ml", 9900, "G마켓"),               # 용량 다름 → 제외
        ("독도 토너 500ml 공병", 2000, "기타몰"),                   # 가격 비정상 → 제외
    ))
    assert r.status == "ok" and r.market_lowest == 22900 and r.market_mall == "쿠팡" and r.market_count == 2
    assert [o["mall"] for o in r.offers] == ["쿠팡", "11번가"]


def test_no_match():
    r = evaluate(T, items(("전혀 다른 상품 샴푸 1L", 15000, "쿠팡")))
    assert r.status == "no_match" and r.market_lowest is None


def test_same_mall():
    assert same_mall("gsshop", "GS SHOP", "GS SHOP") and same_mall("11st", "11번가", "11번가")
    assert not same_mall("11st", "11번가", "쿠팡")


def test_parse_enuri_html_and_evaluate():
    from promohub.pricecheck import parse_enuri_html
    html = """<ul class="goods-list">
      <li class="prodItem"><a href="/detail.jsp?modelno=111"><img src="//img.enuri.info/1.jpg" alt="라운드랩 독도 토너 500ml"></a>
        <a href="/detail.jsp?modelno=111" class="tit">라운드랩 독도 토너 500ml 1+1</a><span class="price">최저가 <em>20,500</em>원</span><span>판매처 32</span></li>
      <li class="prodItem"><a href="/detail.jsp?modelno=222" class="tit">라운드랩 독도 토너 200ml</a><span class="price">9,900원</span></li>
    </ul>"""
    items = parse_enuri_html(html, "https://www.enuri.com/search.jsp?keyword=x")
    assert {(i["title"], i["lprice"]) for i in items} == {("라운드랩 독도 토너 500ml 1+1", "20500"), ("라운드랩 독도 토너 200ml", "9900")}
    r = evaluate(T, items)
    assert r.market_lowest == 20500 and r.market_mall == "에누리 최저가"       # 200ml는 용량 달라 제외
