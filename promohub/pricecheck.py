"""기획전 상품의 '웹 최저가' 비교.

흐름: Supabase v_price_targets(진행 중 기획전 상품, 미조회 또는 3일 경과) → 네이버 쇼핑 검색 API로 같은 상품 검색
     → 이름·용량 매칭으로 같은 상품만 추림 → 같은 쇼핑몰 판매처는 빼고 최저가 산출 → ingest_prices RPC로 저장.

환경변수: SUPABASE_URL, SUPABASE_ANON_KEY, PROMOHUB_INGEST_TOKEN, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
네이버 검색 API는 하루 25,000회 한도 → 기본 하루 3,000개 상품만 조회(3일 주기로 순환).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx

log = logging.getLogger("promohub")
NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"

# 쇼핑몰 이름 → 네이버 쇼핑 mallName에 나오는 표기(같은 쇼핑몰 판매처 제외용)
MALL_ALIASES = {
    "coupang": ["쿠팡"], "gmarket": ["g마켓", "지마켓"], "auction": ["옥션"], "11st": ["11번가"],
    "ssg": ["ssg", "이마트", "신세계몰"], "lotteon": ["롯데on", "롯데온", "롯데마트"], "navershopping": ["네이버"],
    "gsshop": ["gsshop", "gs샵", "gs shop"], "cjonstyle": ["cj온스타일", "cjonstyle"], "hmall": ["현대hmall", "hmall", "현대홈쇼핑"],
    "lotteimall": ["롯데홈쇼핑", "롯데아이몰"], "musinsa": ["무신사"], "oliveyoung": ["올리브영"], "kurly": ["컬리"],
    "29cm": ["29cm"], "wconcept": ["w컨셉", "wconcept"], "lfmall": ["lf몰", "lfmall"], "ssfshop": ["ssf"],
    "himart": ["하이마트"], "samsung": ["삼성전자", "삼성닷컴"], "lge": ["lg전자"], "danawa": ["다나와"],
    "homeplus": ["홈플러스"], "thehyundai": ["더현대", "현대백화점"], "nsmall": ["ns홈쇼핑", "nsmall"],
    "hnsmall": ["홈앤쇼핑"], "skstoa": ["sk스토아"], "kshop": ["kt알파", "k쇼핑"], "shinsegaetv": ["신세계라이브", "신세계tv"],
    "gongyoung": ["공영쇼핑"], "kakaogift": ["카카오"], "daisomall": ["다이소"], "yes24": ["예스24", "yes24"],
}

_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|g|kg|mg|매|개입|개|입|팩|롤|p|pcs|ea|인치|형|cm|mm|포|정|캡슐|구|병|박스|세트|인분|켤레|족)\b", re.I)
_NOISE_RE = re.compile(r"\[[^\]]*\]|\([^)]*(?:쿠폰|특가|무료|배송|증정|단독|할인|이벤트|당일|한정)[^)]*\)|"
                       r"(?:무료배송|당일발송|오늘출발|특가|단독|한정수량|기획|최저가|정품|공식|best|new|핫딜|타임딜)", re.I)
_STOP = {"세트", "기획", "상품", "용", "the", "and", "of", "1개", "선택", "옵션", "택1", "모음", "외"}


def clean_query(name: str, brand: str = "") -> str:
    t = html.unescape(name or "")
    t = _NOISE_RE.sub(" ", t)
    t = re.sub(r"[/|·,~+★☆♥▶◆■●]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if brand and brand.lower() not in t.lower():
        t = f"{brand} {t}"
    return t[:60]


def _tokens(t: str) -> set[str]:
    t = html.unescape(re.sub(r"<[^>]+>", "", t or "")).lower()
    t = _UNIT_RE.sub(lambda m: f" {m.group(1)}{m.group(2).lower()} ", t)
    toks = re.findall(r"[0-9a-z가-힣.]+", t)
    return {x for x in toks if len(x) >= 2 and x not in _STOP}


def _units(t: str) -> set[str]:
    return {f"{float(a):g}{b.lower()}" for a, b in _UNIT_RE.findall(html.unescape(t or "").lower())}


def match_score(ours: str, theirs: str) -> float:
    """0~1. 용량·수량 표기가 다르면 0(다른 상품). 나머지는 토큰 겹침(우리 상품명 기준 재현율 위주)."""
    u1, u2 = _units(ours), _units(theirs)
    if u1 and u2 and not (u1 <= u2 or u2 <= u1):
        return 0.0
    a, b = _tokens(ours), _tokens(theirs)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    recall = inter / len(a)            # 우리 이름의 단어가 상대 제목에 얼마나 있나
    jacc = inter / len(a | b)
    return round(0.7 * recall + 0.3 * jacc, 3)


def same_mall(source_id: str, source_name: str, mall: str) -> bool:
    m = re.sub(r"\s+", "", (mall or "").lower())
    keys = MALL_ALIASES.get(source_id, []) + [re.sub(r"\s+|\(.*\)", "", source_name.lower())]
    return any(k and re.sub(r"\s+", "", k) in m for k in keys)


@dataclass
class PriceResult:
    item_key: str
    query: str
    market_lowest: Optional[int] = None
    market_mall: str = ""
    market_url: str = ""
    market_title: str = ""
    market_count: int = 0
    match_score: Optional[float] = None
    offers: list = field(default_factory=list)
    status: str = "ok"


def evaluate(target: dict, items: list[dict], min_score: float = 0.55) -> PriceResult:
    """네이버 검색 결과 items에서 같은 상품만 골라 최저가 산출."""
    name, price = target["name"], target.get("price")
    q = clean_query(name, target.get("brand", ""))
    res = PriceResult(item_key=target["item_key"], query=q)
    offers = []
    for it in items:
        title = html.unescape(re.sub(r"<[^>]+>", "", it.get("title", "")))
        try:
            lp = int(it.get("lprice") or 0)
        except ValueError:
            continue
        if lp <= 0:
            continue
        sc = match_score(f"{target.get('brand','')} {name}", title)
        if sc < min_score:
            continue
        if price and not (price * 0.3 <= lp <= price * 3):   # 구성품·대용량 등 엉뚱한 가격 배제
            continue
        mall = it.get("mallName") or ""
        if mall in ("네이버", ""):           # 가격비교 묶음(카탈로그) — 최저가 그대로 사용
            mall = "네이버 가격비교"
        if same_mall(target.get("source_id", ""), target.get("source_name", ""), mall):
            continue
        offers.append({"mall": mall, "price": lp, "title": title[:120], "url": it.get("link", ""), "score": sc})
    if not offers:
        res.status = "no_match"
        return res
    offers.sort(key=lambda o: (o["price"], -o["score"]))
    best = offers[0]
    res.market_lowest, res.market_mall, res.market_url, res.market_title = best["price"], best["mall"], best["url"], best["title"]
    res.market_count = len(offers)
    res.match_score = max(o["score"] for o in offers)
    res.offers = offers[:5]
    return res


class NaverShop:
    def __init__(self, client_id: str | None = None, secret: str | None = None, qps: float = 8.0):
        self.headers = {"X-Naver-Client-Id": client_id or os.environ["NAVER_CLIENT_ID"],
                        "X-Naver-Client-Secret": secret or os.environ["NAVER_CLIENT_SECRET"]}
        self.gap = 1.0 / qps
        self.last = 0.0
        self.calls = 0

    def search(self, query: str, display: int = 30) -> list[dict]:
        wait = self.gap - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        for attempt in range(3):
            r = httpx.get(NAVER_SHOP_URL, params={"query": query, "display": display, "sort": "sim"},
                          headers=self.headers, timeout=15)
            self.calls += 1
            if r.status_code == 200:
                return r.json().get("items", [])
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"네이버 검색 API {r.status_code}: {r.text[:200]}")
        return []


def _sb_headers():
    key = os.environ["SUPABASE_ANON_KEY"]
    h = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_"):
        h["Authorization"] = f"Bearer {key}"
    return h


def fetch_targets(limit: int) -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/v_price_targets"
    out, page = [], 1000
    for start in range(0, limit, page):
        h = dict(_sb_headers(), Range=f"{start}-{min(start + page, limit) - 1}")
        r = httpx.get(url, params={"select": "*", "order": "checked_at.asc.nullsfirst"}, headers=h, timeout=60)
        r.raise_for_status()
        part = r.json()
        out += part
        if len(part) < page:
            break
    return out[:limit]


def send_results(rows: list[PriceResult]) -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/ingest_prices"
    n = 0
    for i in range(0, len(rows), 100):
        body = {"p_token": os.environ["PROMOHUB_INGEST_TOKEN"], "p_rows": [asdict(r) for r in rows[i:i + 100]]}
        r = httpx.post(url, content=json.dumps(body, ensure_ascii=False).encode(), headers=_sb_headers(), timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"ingest_prices 실패: {r.status_code} {r.text[:200]}")
        n += int(r.json() or 0)
    return n


def run(limit: int = 3000, client: NaverShop | None = None) -> dict:
    client = client or NaverShop()
    targets = fetch_targets(limit)
    log.info("가격 비교 대상 %d개", len(targets))
    results, buf = [], []
    stats = {"targets": len(targets), "matched": 0, "no_match": 0, "error": 0, "cheaper": 0}
    for t in targets:
        try:
            res = evaluate(t, client.search(clean_query(t["name"], t.get("brand", ""))))
        except Exception as e:
            if "검색 API 401" in str(e) or "검색 API 403" in str(e):
                raise
            res = PriceResult(item_key=t["item_key"], query=t["name"][:60], status="error")
            log.warning("검색 실패 %s: %s", t["name"][:30], e)
        stats[{"ok": "matched"}.get(res.status, res.status)] += 1
        if res.market_lowest and t.get("price") and t["price"] <= res.market_lowest:
            stats["cheaper"] += 1
        buf.append(res)
        if len(buf) >= 100:
            send_results(buf); results += buf; buf = []
    if buf:
        send_results(buf); results += buf
    stats["api_calls"] = client.calls
    return stats
