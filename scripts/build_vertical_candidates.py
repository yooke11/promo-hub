"""분야별(식품·장보기 / 뷰티 / 패션) 소비자용 페이지를 위한 추가 후보 → config/candidates_verticals.yaml.

이미 운영 중인 채널(sources.yaml enabled)은 넣지 않는다. 시험 수집(collect.yml config=candidates_verticals.yaml)으로
기획전이 3건 이상 잡히는 곳만 scripts/apply_verticals.py 가 sources.yaml 에 추가한다.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

# (id, 이름, 유형, 분야, 도메인, 진입 URL)
C = [
    # ── 식품·장보기 ──
    ("rankingdak", "랭킹닭컴", "vertical", "food", "rankingdak.com", "https://www.rankingdak.com/"),
    ("nongshimmall", "농심몰", "brand", "food", "nongshimmall.com", "https://www.nongshimmall.com/"),
    ("kgcshop", "정관장몰", "brand", "food", "kgcshop.co.kr", "https://www.kgcshop.co.kr/"),
    ("jungoneshop", "정원이샵(대상)", "brand", "food", "jungoneshop.com", "https://www.jungoneshop.com/"),
    ("maeildirect", "매일다이렉트", "brand", "food", "maeildirect.com", "https://www.maeildirect.com/"),
    ("harimmall", "하림몰", "brand", "food", "harimmall.com", "https://www.harimmall.com/"),
    ("ourhomemall", "아워홈몰", "brand", "food", "ourhomemall.co.kr", "https://www.ourhomemall.co.kr/"),
    ("samyangshop", "삼양식품몰", "brand", "food", "samyangshop.com", "https://www.samyangshop.com/"),
    ("cookatmarket", "쿠캣마켓", "vertical", "food", "cookatmarket.com", "https://www.cookatmarket.com/"),
    ("thebanchan", "더반찬", "vertical", "food", "thebanchan.co.kr", "https://www.thebanchan.co.kr/"),
    ("fresheasy", "프레시지", "vertical", "food", "fresheasy.co.kr", "https://www.fresheasy.co.kr/"),
    ("meatbox", "미트박스", "vertical", "food", "meatbox.co.kr", "https://www.meatbox.co.kr/"),
    ("choroc", "초록마을", "vertical", "food", "choroc.com", "https://www.choroc.com/"),
    ("nonghyupmall", "농협몰", "openmarket", "food", "nonghyupmall.com", "https://www.nonghyupmall.com/"),
    ("epost", "우체국쇼핑", "openmarket", "food", "mall.epost.go.kr", "https://mall.epost.go.kr/"),
    # ── 뷰티 ──
    ("amoremall", "아모레몰", "brand", "beauty", "amoremall.com", "https://www.amoremall.com/kr/ko/display/event"),
    ("etude", "에뛰드", "brand", "beauty", "etude.com", "https://www.etude.com/kr/ko/display/event"),
    ("tonystreet", "토니모리", "brand", "beauty", "tonystreet.com", "https://www.tonystreet.com/"),
    ("missha", "미샤", "brand", "beauty", "beautynet.co.kr", "https://missha.beautynet.co.kr/"),
    ("clubclio", "클리오", "brand", "beauty", "clubclio.co.kr", "https://clubclio.co.kr/"),
    ("romand", "롬앤", "brand", "beauty", "romand.co.kr", "https://romand.co.kr/"),
    ("roundlab", "라운드랩", "brand", "beauty", "roundlab.co.kr", "https://roundlab.co.kr/"),
    ("manyo", "마녀공장", "brand", "beauty", "manyo.co.kr", "https://manyo.co.kr/"),
    ("torriden", "토리든", "brand", "beauty", "torriden.com", "https://torriden.com/"),
    ("medicube", "메디큐브", "brand", "beauty", "medicube.co.kr", "https://medicube.co.kr/"),
    ("chicor", "시코르", "vertical", "beauty", "chicor.com", "https://www.chicor.com/"),
    ("drg", "닥터지", "brand", "beauty", "drg.co.kr", "https://www.drg.co.kr/"),
    # ── 패션 ──
    ("halfclub", "하프클럽", "fashion", "fashion", "halfclub.com", "https://www.halfclub.com/"),
    ("sivillage", "SI빌리지", "fashion", "fashion", "sivillage.com", "https://www.sivillage.com/"),
    ("thehandsome", "더한섬닷컴", "fashion", "fashion", "thehandsome.com", "https://www.thehandsome.com/ko"),
    ("topten", "탑텐몰", "fashion", "fashion", "topten10mall.com", "https://topten10mall.com/kr/front/main"),
    ("spao", "스파오", "fashion", "fashion", "spao.com", "https://spao.com/"),
    ("nbkorea", "뉴발란스", "fashion", "fashion", "nbkorea.com", "https://www.nbkorea.com/"),
    ("giordano", "지오다노", "fashion", "fashion", "giordano.co.kr", "https://www.giordano.co.kr/"),
    ("xexymix", "젝시믹스", "fashion", "fashion", "xexymix.com", "https://www.xexymix.com/"),
    ("andar", "안다르", "fashion", "fashion", "andar.co.kr", "https://andar.co.kr/"),
    ("crocs", "크록스", "fashion", "fashion", "crocs.co.kr", "https://www.crocs.co.kr/"),
    ("discovery", "디스커버리", "fashion", "fashion", "discovery-expedition.com", "https://www.discovery-expedition.com/"),
    ("mlbkorea", "MLB", "fashion", "fashion", "mlb-korea.com", "https://www.mlb-korea.com/"),
    ("underarmour", "언더아머", "fashion", "fashion", "underarmour.co.kr", "https://www.underarmour.co.kr/"),
    ("k2", "K2", "fashion", "fashion", "k2.co.kr", "https://www.k2.co.kr/"),
    ("aland", "에이랜드", "fashion", "fashion", "a-land.co.kr", "https://www.a-land.co.kr/"),
]


def main():
    base = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    live = {s["id"] for s in base["sources"] if s.get("enabled", True)}
    out = []
    for i, (sid, name, ctype, vert, dom, url) in enumerate(C):
        assert sid not in live, sid
        out.append({"id": sid, "name": name, "channel_type": ctype, "rank": 200 + i, "vertical": vert,
                    "domains": [dom], "mobile": False, "entry_urls": [url]})
    doc = {"defaults": base["defaults"], "common_include_patterns": base["common_include_patterns"],
           "common_exclude_patterns": base["common_exclude_patterns"], "sources": out}
    head = "# 자동 생성: scripts/build_vertical_candidates.py — 분야별 페이지(식품·뷰티·패션) 추가 후보. 시험 수집 후 통과한 곳만 sources.yaml 로 옮긴다.\n"
    (ROOT / "config" / "candidates_verticals.yaml").write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(out), "candidates")


if __name__ == "__main__":
    main()
