"""뷰티 브랜드 공식몰 후보 → config/candidates_beauty.yaml (2026-11-25).

수집 금지(robots.txt)·접속 차단으로 확인된 곳(올리브영·아모레몰·시코르·마녀공장)은 넣지 않는다.
카페24 기반 브랜드몰은 기획전이 /product/project.html, 이벤트가 /board/event/ 등에 있어 패턴을 더한다.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CAFE24 = [r"project\.html", r"/board/(event|gallery)[^/]*/", r"/article/[^/]+/\d+/\d+", r"/exhibit", r"/promotion"]
# 카페24 상품 상세는 기획전이 아니다(정샘물·비플레인에서 상품이 기획전으로 잡혔던 문제)
CAFE24_EX = [r"/product/detail\.html", r"product_no=", r"/product/[^?]+/\d+/category/"]

# (id, 이름, 도메인, 진입 URL들, 카페24 여부)
C = [
    ("sulwhasoo", "설화수", "sulwhasoo.com", ["https://www.sulwhasoo.com/kr/ko/"], False),
    ("hera", "헤라", "hera.com", ["https://www.hera.com/kr/ko/"], False),
    ("laneige", "라네즈", "laneige.com", ["https://www.laneige.com/kr/ko/"], False),
    ("iope", "아이오페", "iope.com", ["https://www.iope.com/kr/ko/"], False),
    ("etude", "에뛰드", "etude.com", ["https://www.etude.com/kr/ko/"], False),
    ("aestura", "에스트라", "aestura.com", ["https://www.aestura.com/kr/ko/"], False),
    ("clubclio", "클리오", "clubclio.co.kr", ["https://clubclio.co.kr/"], True),
    ("romand", "롬앤", "romand.co.kr", ["https://romand.co.kr/", "https://romand.co.kr/board/event/list.html"], True),
    ("torriden", "토리든", "torriden.com", ["https://torriden.com/", "https://torriden.com/board/event/list.html"], True),
    ("medicube", "메디큐브", "medicube.co.kr", ["https://medicube.co.kr/", "https://medicube.co.kr/board/event/list.html"], True),
    ("tonystreet", "토니모리", "tonystreet.com", ["https://www.tonystreet.com/", "https://www.tonystreet.com/event/eventList.do"], False),
    ("banilaco", "바닐라코", "banila.com", ["https://banila.com/", "https://banila.com/board/gallery/list.html?board_no=8"], True),
    ("stylenanda", "3CE 스타일난다", "stylenanda.com", ["https://www.stylenanda.com/"], True),
    ("jsmbeauty", "정샘물", "jsmbeauty.com", ["https://jsmbeauty.com/"], True),
    ("cosrx", "코스알엑스", "cosrx.co.kr", ["https://www.cosrx.co.kr/"], True),
    ("beplain", "비플레인", "beplain.co.kr", ["https://beplain.co.kr/"], True),
    ("dalba", "달바", "dalba.co.kr", ["https://www.dalba.co.kr/"], True),
    ("cellfusionc", "셀퓨전씨", "cellfusionc.co.kr", ["https://cellfusionc.co.kr/"], True),
    ("numbuzin", "넘버즈인", "numbuzin.com", ["https://numbuzin.com/"], True),
    ("fwee", "퓌", "fwee.kr", ["https://fwee.kr/"], True),
    ("hince", "힌스", "hince.co.kr", ["https://hince.co.kr/"], True),
    ("dasique", "데이지크", "dasique.co.kr", ["https://dasique.co.kr/"], True),
    ("amuse", "어뮤즈", "amusemakeup.com", ["https://amusemakeup.com/"], True),
    ("sidmool", "시드물", "sidmool.com", ["https://www.sidmool.com/"], True),
    ("isoi", "아이소이", "isoi.co.kr", ["https://www.isoi.co.kr/"], True),
    ("drg", "닥터지", "drg.co.kr", ["https://www.drg.co.kr/", "https://www.gowoonsesang.com/"], True),
    ("missha", "미샤", "missha.co.kr", ["https://www.missha.co.kr/"], False),
    ("skinfood", "스킨푸드", "theskinfood.com", ["https://www.theskinfood.com/"], True),
]


def main():
    base = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    live = {s["id"] for s in base["sources"] if s.get("enabled", True)}
    out = []
    for i, (sid, name, dom, urls, cafe24) in enumerate(C):
        assert sid not in live, sid
        d = {"id": sid, "name": name, "channel_type": "brand", "rank": 300 + i, "vertical": "beauty",
             "domains": [dom] + (["gowoonsesang.com"] if sid == "drg" else []), "mobile": False, "entry_urls": urls}
        if cafe24:
            d["include_patterns"] = CAFE24
            d["exclude_patterns"] = CAFE24_EX
        out.append(d)
    doc = {"defaults": base["defaults"], "common_include_patterns": base["common_include_patterns"],
           "common_exclude_patterns": base["common_exclude_patterns"], "sources": out}
    (ROOT / "config" / "candidates_beauty.yaml").write_text(
        "# 자동 생성: scripts/build_beauty_candidates.py — 뷰티 브랜드 공식몰 후보(수집 금지 확인된 곳 제외)\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(out))


if __name__ == "__main__":
    main()
