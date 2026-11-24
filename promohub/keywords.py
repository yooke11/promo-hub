"""기획전·이벤트별 검색광고 추천 키워드(최대 10개).

1) 규칙 기반 후보: 기획전 제목·카테고리·혜택·담긴 상품(브랜드·품목)에서
   브랜드+품목 / 품목+혜택 / 시즌·행사명 / 구매의도(추천·최저가) / 상품 롱테일 키워드를 만든다.
2) (선택) 네이버 검색광고 API(키워드 도구)로 월간 검색량·경쟁도를 붙이고 연관 키워드를 보강한 뒤 재정렬.
   환경변수 NAVER_AD_API_KEY, NAVER_AD_SECRET, NAVER_AD_CUSTOMER_ID 가 있을 때만.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, asdict, field
from typing import Optional

import httpx

from .pricecheck import _UNIT_RE

KIND_LABEL = {"brand": "브랜드+품목", "benefit": "품목+혜택", "event": "시즌·행사", "intent": "구매의도",
              "longtail": "상품 롱테일", "category": "카테고리", "related": "연관 검색어"}

_STOPWORDS = set("""기획 기획전 이벤트 특가 단독 증정 무료 무료배송 배송 당일 신상 세트 할인 쿠폰 혜택 최대 선착순 한정 모음
선택 옵션 택1 1개 2개 3개 외 공식 정품 국내 해외 new best 추천 인기 오늘 단하루 타임딜 특집 페어 위크 대전 리뷰
메인 배너 메인배너 이미지 컬렉션 베스트 모음 쇼케이스 브랜드 발표 당첨자 당첨 안내 참여 혜택가 구성 포함 증정품
스페셜 특별한 바로가기 전체보기 더보기 조회 상담 예약 멤버십 포인트 고객 데이 알아보기 만나는 promotion online only special event sale shop""".split())
_CAT_WORD = re.compile(r"(의류|잡화|가전|식품|화장품|용품|선물세트|가구|침구|패션|뷰티|신발|주방|생활|리빙|캠핑|골프|아웃도어|유아|키즈|반려)$")
_SEASON = re.compile(r"(겨울|여름|봄|가을|연말|크리스마스|설날|설|추석|명절|블랙프라이데이|블프|새해|신학기|어버이날|가정의\s*달|발렌타인|화이트데이|빼빼로|수능|휴가|캠핑)")
_EVENT_HINT = re.compile(r"(데이|페스타|페스티벌|위크|세일|대축제|대전|페어|빅스마일|십일절|블랙프라이데이|블프|무진장|올영)")
_TYPE_HEADS = re.compile(
    r"(패딩|코트|자켓|재킷|니트|가디건|맨투맨|후드|티셔츠|셔츠|팬츠|청바지|데님|슬랙스|스커트|원피스|레깅스|운동화|러닝화|스니커즈|부츠|"
    r"가방|백팩|지갑|모자|머플러|목도리|장갑|양말|속옷|잠옷|파자마|"
    r"토너|스킨|로션|에센스|세럼|앰플|크림|선크림|선스틱|쿠션|파운데이션|립스틱|틴트|마스카라|클렌저|클렌징폼|폼클렌징|마스크팩|샴푸|트리트먼트|바디워시|바디로션|향수|핸드크림|"
    r"한우|등심|안심|삼겹살|목살|돼지고기|소고기|닭가슴살|연어|새우|굴비|갈치|과일|사과|배|귤|감귤|딸기|샤인머스캣|포도|밀키트|김치|라면|생수|커피|원두|우유|요거트|견과|홍삼|영양제|유산균|비타민|프로틴|"
    r"청소기|로봇청소기|공기청정기|가습기|제습기|에어프라이어|전자레인지|냉장고|세탁기|건조기|식기세척기|노트북|모니터|태블릿|스마트폰|이어폰|헤드폰|tv|티비|안마기|전기요|히터|"
    r"이불|베개|매트리스|소파|침대|커튼|러그|수건|프라이팬|냄비|밀폐용기|텀블러|세제|휴지|물티슈|기저귀|분유|장난감|사료|캣타워)", re.I)


@dataclass
class Keyword:
    keyword: str
    kind: str
    score: float
    reason: str = ""
    pc: Optional[int] = None
    mobile: Optional[int] = None
    comp: str = ""

    @property
    def volume(self) -> Optional[int]:
        return None if self.pc is None and self.mobile is None else (self.pc or 0) + (self.mobile or 0)


def _clean(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]+>", " ", t or "")
    t = _UNIT_RE.sub(" ", t)
    t = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _words(t: str) -> list[str]:
    return [w for w in _clean(t).split() if len(w) >= 2 and w.lower() not in _STOPWORDS and not w.isdigit()]


def _head_of(word: str) -> str:
    """단어가 품목명으로 '끝나면' 그 품목(숏패딩→패딩). 절임배추처럼 중간에 들어간 건 제외."""
    for m in _TYPE_HEADS.finditer(word):
        if m.end() == len(word):
            return m.group(0)
    return ""


def product_type(name: str) -> str:
    """상품명에서 품목명(예: '라운드랩 독도 토너 500ml' → '독도 토너', '구스다운 숏패딩' → '숏패딩')."""
    words = _clean(name).split()
    hit = None
    for idx, w in enumerate(words):
        if _head_of(w):
            hit = idx                     # 마지막으로 나온 품목 단어
    if hit is None:
        return ""
    w, prev = words[hit], (words[hit - 1] if hit > 0 else "")
    # '토너'처럼 품목 단어만 있으면 앞의 짧은 수식어(독도·무선·경량 등)를 붙인다
    if _head_of(w) == w and prev and 2 <= len(prev) <= 3 and prev.lower() not in _STOPWORDS and not re.search(r"\d", prev):
        return f"{prev} {w}"
    return w


_KO = re.compile(r"^[가-힣]{2,8}$")


_ENDING = re.compile(r"(을|를|은|는|의|에|도|할|한|까지|부터|하는|있는|없는|않아도|지는|하게|롭게|스러운|같은|처럼|으로|에서|해요|하기|되는|된)$")


def ko_nouns(t: str) -> list[str]:
    """한글 명사 후보(조사·어미로 끝나는 단어 제외)."""
    return [w for w in _words(t) if _KO.match(w) and w not in _STOPWORDS and not _ENDING.search(w)]


def product_head(name: str) -> str:
    """일반 품목명(숏패딩·롱패딩 → 패딩)."""
    heads = [_head_of(w) for w in _clean(name).split()]
    heads = [h for h in heads if h]
    return heads[-1] if heads else ""


def _norm(k: str) -> str:
    return re.sub(r"\s+", "", k.lower())


def generate(promo: dict, items: list[dict], channel: str, limit: int = 10) -> list[Keyword]:
    """promo: {title, category, benefits[], max_discount}, items: [{name, brand, price}], channel: 쇼핑몰명"""
    title = promo.get("title", "")
    benefits = promo.get("benefits") or []
    types = Counter(t for t in (product_type(i.get("name", "")) for i in items) if t and t.lower() not in _STOPWORDS)
    brand_set = {(i.get("brand") or "").strip() for i in items}
    # 사전에 없는 품목(피아노·선물세트 등): 여러 상품명·제목에 반복되는 한글 단어
    noun_freq = Counter(w for i in items for w in set(ko_nouns(i.get("name", ""))) if w not in brand_set)
    title_nouns = [w for w in ko_nouns(title) if not _EVENT_HINT.search(w) and not _SEASON.fullmatch(w)]
    for w in title_nouns:
        if noun_freq.get(w, 0) >= 1:       # 상품명에도 나오는 제목 단어만 품목으로 인정
            noun_freq[w] += 2
    if len(types) < 2:
        for w, c in noun_freq.most_common(3):
            if c >= 2 and w not in types and not any(w in t for t in types):
                types[w] = c
    brands = Counter(b.strip() for b in (i.get("brand") or "" for i in items) if b and len(b.strip()) >= 2)
    brand_types = Counter((i.get("brand", "").strip(), product_type(i.get("name", ""))) for i in items
                          if i.get("brand") and product_type(i.get("name", "")))
    title_words = _words(title)
    season = _SEASON.findall(title)
    n_items = max(len(items), 1)
    cands: dict[str, Keyword] = {}

    def add(k: str, kind: str, score: float, reason: str):
        k = re.sub(r"\s+", " ", k).strip()
        if len(_norm(k)) < 2 or len(k) > 25:
            return
        key = _norm(k)
        if key not in cands or cands[key].score < score:
            cands[key] = Keyword(k, kind, round(score, 3), reason)

    heads = Counter(h for h in (product_head(i.get("name", "")) for i in items) if h)
    top_types = [t for t, _ in types.most_common(4)]
    # 여러 상품에 공통인 일반 품목(숏패딩·롱패딩 → 패딩)을 앞세운다
    common = [h for h, c in heads.most_common(2) if c >= 2 and h not in top_types]
    top_types = (common + top_types)[:4]
    for h in common:
        types[h] = heads[h]
    if not top_types and any(_head_of(w) for w in _clean(title).split()):   # 상품을 못 읽은 기획전: 제목에 품목이 있을 때만
        top_types = [product_type(title)]

    # 브랜드+품목
    for (b, t), c in brand_types.most_common(3):
        add(f"{b} {t}", "brand", 0.9 + 0.3 * c / n_items, f"기획전 상품 {c}개가 {b} {t}")
    for b, c in brands.most_common(2):
        add(f"{b} 할인" if "할인" in benefits else f"{b} 세일", "brand", 0.7 + 0.3 * c / n_items, f"주요 브랜드({c}개 상품)")
    # 품목+혜택
    for i, t in enumerate(top_types[:3]):
        share = types.get(t, 1) / n_items
        if promo.get("max_discount"):
            add(f"{t} 할인", "benefit", 0.85 + 0.2 * share - 0.05 * i, f"최대 {promo['max_discount']}% 할인 기획전")
        if "1+1" in benefits:
            add(f"{t} 1+1", "benefit", 0.8 - 0.05 * i, "1+1 혜택")
        if "쿠폰" in benefits and i == 0:
            add(f"{t} 쿠폰", "benefit", 0.6, "쿠폰 제공")
        add(f"{t} 특가", "benefit", 0.7 + 0.2 * share - 0.05 * i, "기획전 대표 품목")
    # 시즌·행사
    for s in dict.fromkeys(season):
        for t in top_types[:2]:
            add(f"{s} {t}", "event", 0.8, f"제목의 시즌 키워드 '{s}'")
    ev = [w for w in title_words if _EVENT_HINT.search(w)]
    if ev:
        add(" ".join(ev[:2]), "event", 0.65 if items else 0.9, "행사명")
        add(f"{channel} {ev[0]}", "event", 0.6 if items else 0.85, "쇼핑몰+행사명(자사 광고용)")
    if not items and not top_types:
        add(f"{channel} 기획전", "event", 0.7, "쇼핑몰 기획전 탐색 검색어")
        add(f"{channel} 쿠폰" if "쿠폰" in benefits else f"{channel} 할인", "event", 0.68, "혜택 탐색 검색어")
        for w in [w for w in title_nouns if not _CAT_WORD.search(w)][:2]:
            add(f"{channel} {w}", "event", 0.5, "기획전 제목 단어")
    # 구매의도
    for t in top_types[:2]:
        add(f"{t} 추천", "intent", 0.62, "비교·탐색 단계 검색어")
        add(f"{t} 최저가", "intent", 0.6, "가격 비교 의도")
    # 제목의 카테고리성 단어(여성의류·선물세트·캠핑용품…)
    for w in title_nouns:
        if _CAT_WORD.search(w):
            add(w, "category", 0.78, "기획전 제목의 카테고리")
            if promo.get("max_discount") or "할인" in benefits:
                add(f"{w} 할인", "category", 0.74, "카테고리+혜택")
            if season:
                add(f"{season[0]} {w}", "event", 0.76, "시즌+카테고리")
    # 상품 롱테일(가장 대표 상품)
    for i in items[:3]:
        ws = _words(i.get("name", ""))
        if len(ws) >= 2:
            add(" ".join(([i["brand"]] if i.get("brand") and i["brand"] not in ws else []) + ws[:3]), "longtail", 0.55,
                "기획전 대표 상품명")
    # 짧은 제목(행사명이 아닌 것)은 그 자체가 좋은 키워드: '카시오 피아노', '비식품 선물세트'
    tw = _words(title)
    if (1 <= len(tw) <= 3 and not _EVENT_HINT.search(title) and len(_norm(" ".join(tw))) >= 3
            and any(_KO.match(w) and not _ENDING.search(w) for w in tw) and not any(re.search(r"\d{3,}", w) for w in tw)):
        add(" ".join(tw), "category", 0.88, "기획전 제목")
    ranked = sorted(cands.values(), key=lambda k: -k.score)
    caps = {"brand": 3, "benefit": 3, "event": 3, "intent": 2, "longtail": 2, "category": 2}
    used: Counter = Counter()
    picked, rest = [], []
    for k in ranked:
        (picked if used[k.kind] < caps.get(k.kind, 2) else rest).append(k)
        used[k.kind] += 1
    return (picked + rest)[: max(limit * 2, 20)]   # 종류를 고르게, 검색량 보강 전 여유분


class SearchAd:
    """네이버 검색광고 API 키워드 도구(/keywordstool)."""
    BASE = "https://api.searchad.naver.com"

    def __init__(self, key=None, secret=None, customer=None):
        self.key = key or os.environ["NAVER_AD_API_KEY"]
        self.secret = secret or os.environ["NAVER_AD_SECRET"]
        self.customer = customer or os.environ["NAVER_AD_CUSTOMER_ID"]

    def _headers(self, method: str, uri: str) -> dict:
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(self.secret.encode(), f"{ts}.{method}.{uri}".encode(), hashlib.sha256).digest()).decode()
        return {"X-Timestamp": ts, "X-API-KEY": self.key, "X-Customer": str(self.customer), "X-Signature": sig}

    def stats(self, hints: list[str]) -> list[dict]:
        uri = "/keywordstool"
        out = []
        for i in range(0, len(hints), 5):     # 한 번에 힌트 5개까지
            part = [_norm(h) for h in hints[i:i + 5] if _norm(h)]
            r = None
            for base in (self.BASE, "https://api.naver.com"):   # 공식 주소 → 구 주소 순으로 시도
                try:
                    r = httpx.get(base + uri, params={"hintKeywords": ",".join(part), "showDetail": "1"},
                                  headers=self._headers("GET", uri), timeout=20)
                except httpx.HTTPError:
                    continue
                if r.status_code != 404:
                    break
            if r is None or r.status_code != 200:
                raise RuntimeError(f"검색광고 API {getattr(r, 'status_code', '접속 실패')}: {getattr(r, 'text', '')[:200]}")
            out += r.json().get("keywordList", [])
            time.sleep(0.3)
        return out


def _num(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    return 5 if str(v).strip().startswith("<") else int(re.sub(r"\D", "", str(v)) or 0)   # "< 10"


def enrich(cands: list[Keyword], rows: list[dict], top_types: list[str], limit: int = 10) -> list[Keyword]:
    """검색광고 API 결과로 검색량을 붙이고, 품목이 들어간 연관 키워드를 보강해 재정렬."""
    by = {_norm(r.get("relKeyword", "")): r for r in rows}
    for k in cands:
        r = by.get(_norm(k.keyword))
        if r:
            k.pc, k.mobile, k.comp = _num(r.get("monthlyPcQcCnt")), _num(r.get("monthlyMobileQcCnt")), r.get("compIdx", "")
    have = {_norm(k.keyword) for k in cands}
    tt = [_norm(t) for t in top_types if t]
    for r in rows:
        rk = r.get("relKeyword", "")
        if _norm(rk) in have or not any(t in _norm(rk) for t in tt):
            continue
        k = Keyword(rk, "related", 0.5, "검색광고 연관 키워드", _num(r.get("monthlyPcQcCnt")), _num(r.get("monthlyMobileQcCnt")), r.get("compIdx", ""))
        cands.append(k)
        have.add(_norm(rk))

    def final(k: Keyword) -> float:
        if k.volume is None:
            return k.score * 0.4           # 검색량 미확인(검색광고 도구에 없음)은 뒤로
        if k.volume < 30:
            return k.score * 0.3           # 거의 검색되지 않는 키워드
        comp_pen = {"높음": 0.85, "중간": 0.95}.get(k.comp, 1.0)
        return k.score * (0.6 + 0.4 * min(math.log10(k.volume) / 5, 1)) * comp_pen

    ranked = sorted(cands, key=final, reverse=True)
    # 검색량이 확인됐는데 월 20회 미만이면 광고 효용이 거의 없어 뺀다(최소 3개는 남김)
    kept = [k for k in ranked if k.volume is None or k.volume >= 20]
    if len(kept) < 3:
        kept = ranked[:3]
    return kept[:limit]


LAST_AD_ERROR: list[str] = []


def recommend(promo: dict, items: list[dict], channel: str, ad: SearchAd | None = None, limit: int = 10) -> list[Keyword]:
    cands = generate(promo, items, channel, limit)
    if ad and cands:
        types = [t for t, _ in Counter(product_type(i.get("name", "")) for i in items).most_common(3) if t]
        try:
            rows = ad.stats([k.keyword for k in cands[:15]])
            return enrich(cands, rows, types, limit)
        except Exception as e:
            if len(LAST_AD_ERROR) < 3:
                LAST_AD_ERROR.append(str(e)[:200])
    return cands[:limit]


def to_rows(promotion_id: str, kws: list[Keyword]) -> list[dict]:
    return [dict(asdict(k), promotion_id=promotion_id, rank=i + 1, kind_label=KIND_LABEL.get(k.kind, k.kind))
            for i, k in enumerate(kws)]


# ── 실행: 새로 수집된 기획전에 키워드 생성 → Supabase 저장 ─────────────────
def run(limit: int = 500) -> dict:
    import json as _json
    from .pricecheck import _sb_headers
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    h = _sb_headers()
    targets = httpx.get(f"{base}/v_kw_targets", params={"select": "*", "limit": str(limit)}, headers=h, timeout=60).json()
    ad = None
    if all(os.environ.get(k) for k in ("NAVER_AD_API_KEY", "NAVER_AD_SECRET", "NAVER_AD_CUSTOMER_ID")):
        ad = SearchAd()
    stats = {"targets": len(targets), "saved": 0, "with_volume": 0, "searchad": bool(ad)}
    for t in targets:
        items = httpx.get(f"{base}/promotion_items", params={"select": "name,brand,price", "promotion_id": f"eq.{t['id']}",
                                                              "order": "position.asc", "limit": "40"}, headers=h, timeout=30).json()
        kws = recommend(t, items, t.get("source_name", ""), ad)
        if not kws:
            continue
        stats["with_volume"] += sum(1 for k in kws if k.volume is not None)
        body = {"p_token": os.environ["PROMOHUB_INGEST_TOKEN"], "p_promotion_id": t["id"], "p_rows": to_rows(t["id"], kws)}
        r = httpx.post(f"{base}/rpc/ingest_keywords", content=_json.dumps(body, ensure_ascii=False).encode(), headers=h, timeout=30)
        if r.status_code == 200:
            stats["saved"] += 1
    stats["searchad_errors"] = LAST_AD_ERROR
    return stats
