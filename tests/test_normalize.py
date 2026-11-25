from datetime import date

from promohub.normalize import (canonical_url, classify_category, classify_kind, extract_benefits,
                                extract_max_discount, parse_date_value, parse_period, status_of)

REF = date(2026, 11, 24)


def test_period_short_with_dow():
    assert parse_period("11.20(목) ~ 11.30(일)", REF) == (date(2026, 11, 20), date(2026, 11, 30))


def test_period_full():
    assert parse_period("기간: 2026.11.24 - 2026.12.31", REF) == (date(2026, 11, 24), date(2026, 12, 31))


def test_period_korean():
    assert parse_period("11월 25일 ~ 12월 3일까지", REF) == (date(2026, 11, 25), date(2026, 12, 3))


def test_period_year_rollover():
    assert parse_period("12.20 ~ 01.05", REF) == (date(2026, 12, 20), date(2027, 1, 5))


def test_period_until_only():
    assert parse_period("~12.07", REF) == (None, date(2026, 12, 7))
    assert parse_period("12월 15일까지", REF) == (None, date(2026, 12, 15))


def test_period_with_time_and_day_only_end():
    assert parse_period("11.28 10:00 ~ 30일", REF) == (date(2026, 11, 28), date(2026, 11, 30))


def test_period_next_year_january_seen_in_november():
    assert parse_period("1.2 ~ 1.10", REF) == (date(2027, 1, 2), date(2027, 1, 10))


def test_period_none():
    assert parse_period("겨울 아우터 기획전", REF) == (None, None)


def test_date_values():
    assert parse_date_value("20261207") == date(2026, 12, 7)
    assert parse_date_value("2026-12-04T10:59:59") == date(2026, 12, 4)
    assert parse_date_value(1764000000000) is not None
    assert parse_date_value("abc") is None


def test_canonical_url():
    a = canonical_url("https://m.gmarket.co.kr/n/promotion/winter-outer?utm_campaign=x")
    b = canonical_url("https://www.gmarket.co.kr/n/promotion/winter-outer/")
    assert a == b


def test_benefits_discount():
    t = "브랜드 패딩 쿠폰 최대 20% + 카드 즉시할인 7%, 1+1, 무료배송"
    assert extract_max_discount(t) == 20
    assert set(extract_benefits(t)) >= {"할인", "쿠폰", "카드혜택", "1+1", "무료배송"}


def test_classify():
    assert classify_category("빅스마일데이 최대 70%") == "시즌·대형행사"
    assert classify_category("겨울 아우터 기획전") == "패션"
    assert classify_category("설화수 뷰티 선물세트") == "뷰티"
    assert classify_kind("매일 룰렛 돌리고 경품 응모") == "이벤트"
    assert classify_kind("겨울 아우터 기획전") == "기획전"


def test_status():
    assert status_of(date(2026, 11, 20), date(2026, 11, 26), REF) == "ending_soon"
    assert status_of(date(2026, 11, 20), date(2026, 12, 26), REF) == "active"
    assert status_of(date(2026, 12, 1), None, REF) == "upcoming"
    assert status_of(None, date(2026, 11, 1), REF) == "ended"
    assert status_of(None, None, REF) == "unknown"


def test_noise_titles():
    from promohub.normalize import is_meaningful_title, is_mall_name
    for t in ["더보기 더보기 플러스 아이콘", "Attention Required!", "CJ더마켓 : CJ제일제당 공식몰", "신라인터넷면세점",
              "왼쪽 슬라이드 보기 오른쪽 슬라이드 보기", "상세페이지로 이동", "기획전·이벤트", "전체보기", "EVENT", "Promotion"]:
        assert not is_meaningful_title(t), t
    for t in ["11월 책그리고꽃 : 황금빛 꽃다발", "99마켓", "키링콜렉션", "출석체크하고 쿠폰&포인트 GET!"]:
        assert is_meaningful_title(t), t
    assert is_mall_name("교보문고", "교보문고") and is_mall_name("롯데하이마트", "하이마트")
    assert not is_mall_name("교보문고 『트렌드+』 GRAND OPEN", "교보문고")


def test_fix_url_and_junk_titles():
    from promohub.normalize import fix_url, is_meaningful_title
    assert fix_url("https://gateway.10x10.co.kr/event/eventmain.asp?eventid=133724") == "https://www.10x10.co.kr/event/eventmain.asp?eventid=133724"
    assert fix_url("https://capi.brandi.co.kr/v1/web/37044") is None
    assert fix_url("https://www.costco.co.kr/events") is None
    assert fix_url("https://www.samsung.com/sec/eventList/benefitzone/") is None
    assert fix_url("https://www.kshop.co.kr/display/specialplan/detail?spdpId=1") is not None
    for t in ["1123_popup_top_search1.gif", "2026-11-01", "9650 메인배너 이미지", "APP 다운", "이벤트/쿠폰",
              "Pg 이벤트 상세", "이벤트 외부 링크", "기획전 모두보기", "매장 상담 예약", "IKEA 코리아 뉴스룸"]:
        assert not is_meaningful_title(t), t
    for t in ["슈아뜰리에에 어드벤트캘린더", "출석체크", "신라블프 ~90% SALE", "11월의 굿즈"]:
        assert is_meaningful_title(t), t


def test_title_cleanup_suffix_and_repeat():
    from promohub.normalize import clean_title, is_meaningful_title, fix_url
    assert clean_title("수어 상담 예약 | LG전자 : BEST SHOP") == "수어 상담 예약"
    assert not is_meaningful_title(clean_title("수어 상담 예약 | LG전자 : BEST SHOP"))
    assert clean_title("Home entertainment Home entertainment") == "Home entertainment"
    assert clean_title("크리스마스 선물 추천 인형 키링 모음.zip|~50%") == "크리스마스 선물 추천 인형 키링 모음.zip|~50%"
    assert not is_meaningful_title("@m****7") and not is_meaningful_title("기획전37066 바로가기")
    assert fix_url("https://v3.account.samsung.com/x") is None
