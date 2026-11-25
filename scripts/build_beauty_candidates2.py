"""뷰티 2차 후보(올리브영 상위 브랜드 + VT코스메틱) → config/candidates_beauty2.yaml (2026-11-25).

1차에서 빠진 이유가 '패턴 불일치'인 곳(토리든·달바는 고도몰)을 고도몰 패턴으로 다시 시도한다.
수집 금지(robots.txt) 확인된 곳은 넣지 않는다. 도메인이 확실치 않은 곳은 후보 도메인을 함께 넣어 시험 수집으로 가린다.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CAFE24 = [r"project\.html", r"/board/(event|gallery)[^/]*/", r"/article/[^/]+/\d+/\d+", r"/exhibit", r"/promotion",
          r"/product/list\.html\?cate_no="]
GODO = [r"goods_list\.php\?cateCd=", r"board/(list|view)\.php\?.*bdId=(promotion|event)", r"htmid=[^&]*event"]
EX = [r"/product/detail\.html", r"product_no=", r"/product/[^?]+/\d+/category/", r"goods_view\.php"]

# (id, 이름, 도메인들, 진입 URL들)
C = [
    ("vtcosmetics", "VT코스메틱", ["vtcosmetics.com", "vt-cosmetics.co.kr"],
     ["https://www.vtcosmetics.com/", "https://www.vtcosmetics.com/board/event/list.html", "https://www.vtcosmetics.com/product/project.html"]),
    ("torriden", "토리든", ["torriden.com"],
     ["https://torriden.com/board/list.php?bdId=promotion&period=current", "https://torriden.com/goods/goods_list.php?cateCd=011"]),
    ("dalba", "달바", ["dalba.co.kr"],
     ["https://www.dalba.co.kr/main/html.php?htmid=story/event.html", "https://www.dalba.co.kr/"]),
    ("roundlab", "라운드랩", ["roundlab.co.kr"],
     ["https://roundlab.co.kr/board/gallery/list.html?board_no=12&category_no=1", "https://roundlab.co.kr/product/list.html?cate_no=79"]),
    ("medicube", "메디큐브", ["themedicube.co.kr"],
     ["https://themedicube.co.kr/", "https://themedicube.co.kr/board/event/list.html"]),
    ("mediheal", "메디힐", ["medihealshop.com", "mediheal.com"],
     ["https://www.medihealshop.com/", "https://mediheal.com/"]),
    ("anua", "아누아", ["anua.kr", "anua.co.kr"], ["https://anua.kr/", "https://www.anua.co.kr/"]),
    ("skin1004", "스킨1004", ["skin1004.com", "skin1004.co.kr"], ["https://skin1004.com/", "https://www.skin1004.co.kr/"]),
    ("numbuzin", "넘버즈인", ["numbuzin.com"], ["https://numbuzin.com/", "https://numbuzin.com/board/event/list.html"]),
    ("drg", "닥터지", ["drg.co.kr"], ["https://www.drg.co.kr/"]),
    ("snature", "에스네이처", ["snature.co.kr"], ["https://snature.co.kr/"]),
    ("abib", "아비브", ["abib.co.kr", "abib.com"], ["https://abib.com/", "https://abib.co.kr/board/event/list.html"]),
]


def main():
    base = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    live = {s["id"] for s in base["sources"] if s.get("enabled", True)}
    out = []
    for i, (sid, name, doms, urls) in enumerate(C):
        assert sid not in live, sid
        out.append({"id": sid, "name": name, "channel_type": "brand", "rank": 340 + i, "vertical": "beauty",
                    "domains": doms, "mobile": False, "entry_urls": urls,
                    "include_patterns": CAFE24 + GODO, "exclude_patterns": EX})
    doc = {"defaults": base["defaults"], "common_include_patterns": base["common_include_patterns"],
           "common_exclude_patterns": base["common_exclude_patterns"], "sources": out}
    (ROOT / "config" / "candidates_beauty2.yaml").write_text(
        "# 자동 생성: scripts/build_beauty_candidates2.py — 뷰티 2차 후보(올리브영 상위 + VT)\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(out))


if __name__ == "__main__":
    main()
