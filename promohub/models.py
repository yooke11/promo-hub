from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


CHANNEL_TYPES = {
    "openmarket": "오픈마켓·종합몰",
    "crossborder": "해외직구",
    "department": "백화점·대형마트",
    "homeshopping": "홈쇼핑",
    "fashion": "패션",
    "vertical": "뷰티·리빙·식품",
    "brand": "가전·브랜드몰",
}


@dataclass
class RawPromotion:
    """추출 단계 결과(정규화 전). 출처가 DOM이든 JSON이든 같은 모양으로 모은다."""
    source_id: str
    url: str
    title: str = ""
    image_url: str = ""
    period_text: str = ""
    description: str = ""
    start_hint: Optional[str] = None   # JSON에서 바로 얻은 시작일 값(문자열/epoch)
    end_hint: Optional[str] = None
    origin: str = "dom"                # dom | json | detail
    products: list = field(default_factory=list)   # products.Product 목록


@dataclass
class Promotion:
    id: str
    source_id: str
    url: str
    title: str
    kind: str                     # 기획전 | 이벤트
    category: str
    benefits: list[str] = field(default_factory=list)
    max_discount: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    image_url: str = ""
    description: str = ""
    period_text: str = ""
    products: list = field(default_factory=list)

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("products", None)
        d["benefits"] = ",".join(self.benefits)
        d["start_date"] = self.start_date.isoformat() if self.start_date else None
        d["end_date"] = self.end_date.isoformat() if self.end_date else None
        return d
