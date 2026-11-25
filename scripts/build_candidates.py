"""채널 유형별 후보 쇼핑몰 목록 → config/candidates.yaml 생성.

- 유형 안의 순서 = 트래픽 추정 순위(2026-11 작성, Similarweb·와이즈앱 공개치와 업계 통념 기반 추정).
- config/sources.yaml 에 이미 있는 50곳은 넣지 않는다(그쪽 rank가 우선).
- 시험 수집(collect.yml 의 config=candidates.yaml) 결과로 scripts/apply_selection.py 가 유형별 상위 20곳을 고른다.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

# (id, 이름, 도메인, 진입 URL)  — 유형별, 트래픽 추정 순
C = {
    "openmarket": [
        ("kakaostore", "카카오쇼핑", "store.kakao.com", "https://store.kakao.com/"),
        ("enuri", "에누리", "enuri.com", "https://www.enuri.com/"),
        ("interpark", "인터파크쇼핑", "interpark.com", "https://shopping.interpark.com/"),
        ("halfclub", "하프클럽", "halfclub.com", "https://www.halfclub.com/"),
    ],
    "crossborder": [
        ("amazon", "아마존", "amazon.com", "https://www.amazon.com/"),
        ("ebay", "이베이", "ebay.com", "https://www.ebay.com/"),
        ("qoo10", "큐텐", "qoo10.com", "https://www.qoo10.com/"),
        ("yesstyle", "예스스타일", "yesstyle.com", "https://www.yesstyle.com/ko/home.html"),
        ("asos", "아소스", "asos.com", "https://www.asos.com/"),
        ("farfetch", "파페치", "farfetch.com", "https://www.farfetch.com/kr/"),
        ("ssense", "센스", "ssense.com", "https://www.ssense.com/ko-kr"),
        ("mytheresa", "마이테레사", "mytheresa.com", "https://www.mytheresa.com/kr/ko/women"),
    ],
    "department": [
        ("lottedfs", "롯데면세점", "lottedfs.com", "https://kor.lottedfs.com/"),
        ("shilladfs", "신라면세점", "shilladfs.com", "https://www.shilladfs.com/estore/kr/ko"),
        ("ssgdfs", "신세계면세점", "ssgdfs.com", "https://www.ssgdfs.com/kr/main/initMain"),
        ("hddfs", "현대백화점면세점", "hddfs.com", "https://www.hddfs.com/shop/dm/main.do"),
        ("akmall", "AK몰", "akmall.com", "https://www.akmall.com/"),
        ("galleria", "갤러리아몰", "galleria.co.kr", "https://dept.galleria.co.kr/"),
        ("elandmall", "이랜드몰", "elandmall.co.kr", "https://www.elandmall.co.kr/"),
        ("emart", "이마트몰", "emart.ssg.com", "https://emart.ssg.com/"),
        ("lottemart", "롯데마트몰", "lottemartmall.com", "https://www.lotteon.com/p/display/main/lottemart"),
    ],
    "homeshopping": [
        ("shoppingnt", "쇼핑엔티", "shoppingntmall.com", "https://www.shoppingntmall.com/"),
        ("wshop", "W쇼핑", "wshop.co.kr", "https://www.wshop.co.kr/"),
    ],
    "fashion": [
        ("fashionplus", "패션플러스", "fashionplus.co.kr", "https://www.fashionplus.co.kr/"),
        ("sivillage", "SI빌리지", "sivillage.com", "https://www.sivillage.com/"),
        ("thehandsome", "더한섬닷컴", "thehandsome.com", "https://www.thehandsome.com/ko"),
        ("hiver", "하이버", "hiver.co.kr", "https://www.hiver.co.kr/"),
        ("spao", "스파오", "spao.com", "https://spao.com/"),
        ("topten", "탑텐몰", "topten10mall.com", "https://topten10mall.com/kr/front/main"),
        ("zara", "자라", "zara.com", "https://www.zara.com/kr/"),
        ("hm", "H&M", "hm.com", "https://www2.hm.com/ko_kr/index.html"),
        ("nbkorea", "뉴발란스", "nbkorea.com", "https://www.nbkorea.com/"),
        ("northface", "노스페이스", "thenorthfacekorea.co.kr", "https://www.thenorthfacekorea.co.kr/"),
        ("fila", "휠라", "fila.co.kr", "https://www.fila.co.kr/"),
        ("musinsastandard", "무신사 스탠다드", "musinsastandard.com", "https://www.musinsastandard.com/"),
    ],
    "vertical": [
        ("kyobobook", "교보문고", "kyobobook.co.kr", "https://www.kyobobook.co.kr/"),
        ("aladin", "알라딘", "aladin.co.kr", "https://www.aladin.co.kr/"),
        ("idus", "아이디어스", "idus.com", "https://www.idus.com/"),
        ("cjthemarket", "CJ더마켓", "cjthemarket.com", "https://www.cjthemarket.com/"),
        ("jeongyookgak", "정육각", "jeongyookgak.com", "https://www.jeongyookgak.com/"),
        ("rankingdak", "랭킹닭컴", "rankingdak.com", "https://www.rankingdak.com/"),
        ("petfriends", "펫프렌즈", "pet-friends.co.kr", "https://www.pet-friends.co.kr/"),
        ("aboutpet", "어바웃펫", "aboutpet.co.kr", "https://www.aboutpet.co.kr/"),
        ("mujikorea", "무인양품", "mujikorea.net", "https://www.mujikorea.net/"),
        ("hanssem", "한샘몰", "hanssem.com", "https://mall.hanssem.com/"),
        ("hellonature", "헬로네이처", "hellonature.co.kr", "https://www.hellonature.co.kr/"),
        ("ypbooks", "영풍문고", "ypbooks.co.kr", "https://www.ypbooks.co.kr/"),
    ],
    "brand": [
        ("apple", "애플", "apple.com", "https://www.apple.com/kr/"),
        ("amoremall", "아모레몰", "amoremall.com", "https://www.amoremall.com/kr/ko/display/main"),
        ("dyson", "다이슨", "dyson.co.kr", "https://www.dyson.co.kr/"),
        ("etland", "전자랜드", "etland.co.kr", "https://www.etland.co.kr/"),
        ("kgcshop", "정관장몰", "kgcshop.co.kr", "https://www.kgcshop.co.kr/"),
        ("dongwonmall", "동원몰", "dongwonmall.com", "https://www.dongwonmall.com/"),
        ("pulmuone", "풀무원샵", "pulmuoneshop.co.kr", "https://shop.pulmuone.co.kr/"),
        ("otokimall", "오뚜기몰", "otokimall.com", "https://www.otokimall.com/"),
        ("iloom", "일룸", "iloom.com", "https://www.iloom.com/"),
        ("coway", "코웨이", "coway.com", "https://www.coway.com/"),
        ("cuckoo", "쿠쿠몰", "cuckoo.co.kr", "https://www.cuckoo.co.kr/"),
        ("innisfree", "이니스프리", "innisfree.com", "https://www.innisfree.com/kr/ko/"),
        ("nongshimmall", "농심몰", "nongshimmall.com", "https://www.nongshimmall.com/"),
    ],
}


def main():
    base = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    have = {s["id"] for s in base["sources"]}
    out, rank = [], 100
    for ctype, rows in C.items():
        for i, (sid, name, dom, url) in enumerate(rows):
            if sid in have:
                continue   # 이미 운영 채널로 옮겨진 후보
            rank += 1
            out.append({"id": sid, "name": name, "channel_type": ctype, "rank": rank, "type_order": i + 1,
                        "domains": [dom], "mobile": False, "entry_urls": [url]})
    doc = {"defaults": base["defaults"], "common_include_patterns": base["common_include_patterns"],
           "common_exclude_patterns": base["common_exclude_patterns"], "sources": out}
    head = ("# 자동 생성: scripts/build_candidates.py — 채널 유형별 신규 후보(유형 안 순서 = 트래픽 추정 순).\n"
            "# 시험 수집 결과로 scripts/apply_selection.py 가 sources.yaml 에 옮길 곳을 고른다.\n")
    (ROOT / "config" / "candidates.yaml").write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(out), "candidates")


if __name__ == "__main__":
    main()
