"""뷰티 2차 후보(올리브영 상위 브랜드 + VT코스메틱) → config/candidates_beauty2.yaml (2026-11-25).

1차에서 빠진 이유가 '패턴 불일치'인 곳(토리든·달바는 고도몰)을 고도몰 패턴으로 다시 시도한다.
수집 금지(robots.txt) 확인된 곳은 넣지 않는다. 도메인이 확실치 않은 곳은 후보 도메인을 함께 넣어 시험 수집으로 가린다.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CAFE24 = [r"project\.html", r"/board/(event|gallery)[^/]*/", r"/article/[^/]+/\d+/\d+", r"/exhibit", r"/promotion"]
GODO = [r"goods_list\.php\?cateCd=", r"board/(list|view)\.php\?.*bdId=(promotion|event)", r"htmid=[^&]*event"]
EX = [r"/product/detail\.html", r"product_no=", r"/product/[^?]+/\d+/category/", r"goods_view\.php"]

# (id, 이름, 도메인들, 진입 URL들)
C = [
    # 1차 시험(2026-11-25): VT는 수집 서버 접속 자체가 끊김(ERR_CONNECTION_CLOSED), 닥터지 접속 거부,
    # 스킨1004는 해외(영문)몰, 달바·라운드랩·에스네이처는 진행 기획전이 없어 뺐다.
    # 상품 카테고리(cate_no) 전체를 기획전으로 잡던 패턴은 빼고, 기획전으로 확인된 분류 번호만 넣는다.
    ("medicube", "메디큐브", ["themedicube.co.kr"],
     ["https://themedicube.co.kr/product/list.html?cate_no=1230", "https://themedicube.co.kr/board/event/list.html?board_no=8"],
     [r"cate_no=1230\b", r"/event/[\w-]+\.html"]),
    ("mediheal", "메디힐", ["medihealshop.com"],
     ["https://www.medihealshop.com/", "https://www.medihealshop.com/board/event/list.html?board_no=3001&category_no=1"], []),
    ("numbuzin", "넘버즈인", ["numbuzin.com"],
     ["https://numbuzin.com/product/list.html?cate_no=101", "https://numbuzin.com/board/event/list.html?board_no=5"],
     [r"cate_no=101\b"]),
    ("torriden", "토리든", ["torriden.com"],
     ["https://torriden.com/goods/goods_list.php?cateCd=011", "https://torriden.com/board/list.php?bdId=promotion&period=current"], []),
    ("anua", "아누아", ["anua.kr"], ["https://anua.kr/", "https://anua.kr/board/event/list.html"], []),
]


def main():
    base = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    live = {s["id"] for s in base["sources"] if s.get("enabled", True)}
    out = []
    for i, (sid, name, doms, urls, extra) in enumerate(C):
        assert sid not in live, sid
        out.append({"id": sid, "name": name, "channel_type": "brand", "rank": 340 + i, "vertical": "beauty",
                    "domains": doms, "mobile": False, "entry_urls": urls,
                    "include_patterns": CAFE24 + GODO + extra, "exclude_patterns": EX + [r"period=end", r"write\.html", r"event_result"]})
    doc = {"defaults": base["defaults"], "common_include_patterns": base["common_include_patterns"],
           "common_exclude_patterns": base["common_exclude_patterns"], "sources": out}
    (ROOT / "config" / "candidates_beauty2.yaml").write_text(
        "# 자동 생성: scripts/build_beauty_candidates2.py — 뷰티 2차 후보(올리브영 상위 + VT)\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(len(out))


if __name__ == "__main__":
    main()
