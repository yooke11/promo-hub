from promohub.categorize import classify_product as c, classify_promotion as p


def test_products():
    assert c("[삼삼물산] 전 국민이 좋아하는 통영굴 200g (중굴, 생물)") == "식품"
    assert c("[] 순살 고등어 레몬제스트 60g, 3개 + 백설 햄스빌 베이컨 110g") == "식품"
    assert c("[TV상품] [동국제약] 멜라토닝샷앰플 30ml*3") == "뷰티"
    assert c("하겐다즈 아이스크림 바닐라") == "식품"            # '크림'이 들어 있어도 식품
    assert c("UNO 오리지널 핫도그 400G") == "식품"              # '도그'가 들어 있어도 반려동물 아님
    assert c("오리털 패딩") == "패션"
    assert c("[로르서울] 램스킨 헝가리구스 다운") == "패션"
    assert c("뉴발란스 여성 스포츠 양말 5족") == "패션"
    assert c("보이러 전기요 1인용") == "가전·디지털"
    assert c("XT-6 GTX") is None


def test_promotion_uses_products_not_description():
    # 컬리 '대한민국 수산대전'은 설명(페이지 메뉴)에 '뷰티'가 있어도 상품이 굴·굴비면 식품
    assert p("🌊대한민국 수산대전🎏", ["통영굴 200g", "생굴 420g", "영광굴비 180g"]) == "식품"
    assert p("건강한 피부 본연의 힘 끌레드벨 X 동국제약", ["멜라토닝샷앰플", "콜라겐 크림"]) == "뷰티"
    assert p("블랙프라이데이", [], mega_sale=True) == "시즌·대형행사"
