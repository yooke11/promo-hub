"""상품·기획전 카테고리 분류(2026-11-26).

예전에는 기획전 제목+설명(페이지 메뉴 글자까지 섞임)으로 기획전 하나에 카테고리 하나를 붙이고, 상품은 기획전 카테고리를
그대로 물려받았다. 그래서 컬리 '대한민국 수산대전'이 설명 속 메뉴의 '뷰티' 때문에 뷰티로 잡히고, 굴·고등어가 뷰티 필터에 나왔다.
이제는 상품마다 상품명으로 분류하고, 기획전은 상품들의 다수결 → 제목 순으로 정한다(설명은 쓰지 않음).
규칙은 config/category_rules.json 하나로 DB 함수(public.classify_product)와 같이 쓴다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache

from .config import ROOT

DEFAULT = "종합"


@lru_cache(maxsize=1)
def _rules():
    d = json.loads((ROOT / "config" / "category_rules.json").read_text(encoding="utf-8"))
    strip = [(re.compile(p, re.I), c) for p, c in d["strip"]]
    rules = [(c, re.compile(p, re.I)) for c, p in d["rules"]]
    return strip, rules


def classify_product(name: str, prefer: str | None = None) -> str | None:
    """상품명(또는 제목) → 카테고리. 맞는 단어가 하나도 없으면 None. 동점이면 prefer(기획전 제목 분류)를 우선."""
    text = (name or "").lower()
    if not text:
        return None
    strip, rules = _rules()
    score: Counter = Counter()
    for rx, cat in strip:
        n = len(rx.findall(text))
        if n:
            score[cat] += n
            text = rx.sub(" ", text)
    order = {c: i for i, (c, _) in enumerate(rules)}
    for cat, rx in rules:
        n = len(rx.findall(text))
        if n:
            score[cat] += n
    if not score:
        return None
    top = max(score.values())
    tied = [c for c, v in score.items() if v == top]
    if len(tied) > 1 and "식품" in tied:   # '프로틴 샴푸'·'버터 바디로션'처럼 식품어와 다른 분야어가 같은 수면 식품이 아닌 쪽(기획전 제목이 식품이어도)
        tied.remove("식품")
    if prefer in tied:
        return prefer
    return min(tied, key=lambda c: order.get(c, 99))


def classify_promotion(title: str, product_names: list[str], mega_sale: bool = False) -> str:
    """기획전: 대형 행사 → 상품 다수결(분류된 상품 2개 이상, 최다 카테고리 50% 이상) → 제목 → 종합."""
    if mega_sale:
        return "시즌·대형행사"
    by_title = classify_product(title)
    cats = [c for c in (classify_product(n, by_title) for n in product_names) if c]
    if len(cats) >= 2:
        top, n = Counter(cats).most_common(1)[0]
        if n / len(cats) >= 0.5:
            return top
    return by_title or (Counter(cats).most_common(1)[0][0] if cats else DEFAULT)
