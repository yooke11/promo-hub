from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.yaml"


@dataclass
class Source:
    id: str
    name: str
    channel_type: str
    entry_urls: list[str]
    include: list[re.Pattern]
    exclude: list[re.Pattern]
    mobile: bool = False
    scroll_steps: int = 8
    detail_limit: int = 40
    delay_sec: float = 2.0
    respect_robots: bool = True
    enabled: bool = True
    rank: int = 999
    domains: list[str] = field(default_factory=list)
    product_pats: list[re.Pattern] = field(default_factory=list)
    product_limit: int = 40
    product_link: dict | None = None   # {key: 상품번호 필드/데이터 속성, url: "...{id}..."} — 상품 주소가 없는 JSON·카드용
    pct_needs_original: bool = False   # 정가 없이 할인율만 잡히면 버림(코스트코: 리뷰·추천 비율이 할인율로 잡힘)

    def on_domain(self, url: str) -> bool:
        if not self.domains:
            return True
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def accepts(self, url: str, text: str = "") -> bool:
        if not self.on_domain(url):
            return False
        if any(p.search(url) for p in self.exclude):
            return False
        if self.product_pats and any(p.search(url) for p in self.product_pats):
            return False   # 상품 상세는 기획전이 아님
        return any(p.search(url) or (text and p.search(text)) for p in self.include)


@dataclass
class Config:
    sources: list[Source] = field(default_factory=list)

    def get(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)


def _compile(pats):
    return [re.compile(p, re.I) for p in (pats or [])]


def load_config(path: Path | str = DEFAULT_CONFIG) -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    d = data.get("defaults", {})
    common_inc = data.get("common_include_patterns", [])
    common_exc = data.get("common_exclude_patterns", [])
    from .products import compile_product_patterns
    out = []
    for s in data["sources"]:
        out.append(Source(
            id=s["id"],
            name=s["name"],
            channel_type=s["channel_type"],
            entry_urls=s["entry_urls"],
            include=_compile((s.get("include_patterns") or []) + common_inc),
            exclude=_compile((s.get("exclude_patterns") or []) + common_exc),
            mobile=s.get("mobile", False),
            scroll_steps=s.get("scroll_steps", d.get("scroll_steps", 8)),
            detail_limit=s.get("detail_limit", d.get("detail_limit", 40)),
            delay_sec=s.get("delay_sec", d.get("delay_sec", 2.0)),
            respect_robots=s.get("respect_robots", d.get("respect_robots", True)),
            enabled=s.get("enabled", True),
            rank=s.get("rank", 999),
            domains=s.get("domains") or [],
            product_pats=compile_product_patterns(s.get("product_patterns")),
            product_limit=s.get("product_limit", d.get("product_limit", 40)),
            product_link=s.get("product_link"),
            pct_needs_original=s.get("pct_needs_original", False),
        ))
    out.sort(key=lambda x: x.rank)
    return Config(out)
