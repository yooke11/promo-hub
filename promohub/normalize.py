"""정규화: 기간 파싱, 혜택·할인율 추출, 카테고리/유형 분류, URL 정규화, 중복 키."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import Promotion, RawPromotion

KST = timezone(timedelta(hours=9))

# ── URL ─────────────────────────────────────────────
TRACKING_PARAMS = re.compile(
    r"^(utm_.*|jaehuid|ref|refer|referrer|src|source|nv_.*|n_.*|gclid|fbclid|"
    r"trackingid|trackingcd|t_.*|sc_.*|spm|clickid|traceid|ckey|ad.*id|adp|ici|src_.*|mkt_.*|_ga|from|"
    r"pos|position|area|module|click.*|banner.*|tracking.*|ver|scm|pvid|_trk.*)$",
    re.I,
)


def canonical_url(url: str) -> str:
    """추적 파라미터를 지우고 m./www. 차이를 통일해 같은 기획전을 하나로 묶는다."""
    p = urlparse(url.strip())
    host = p.netloc.lower()
    host = re.sub(r"^(m|www|mw|mobile)\.", "", host)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not TRACKING_PARAMS.match(k)]
    query.sort()
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunparse(("https", host, path, "", urlencode(query), ""))


def promo_id(source_id: str, url: str) -> str:
    return hashlib.sha1(f"{source_id}|{canonical_url(url)}".encode()).hexdigest()[:16]


# ── 기간 ────────────────────────────────────────────
_SEP = r"\s*(?:~|∼|〜|-|–|—|부터)\s*"
_DOW = r"(?:\s*\(?[월화수목금토일](?:요일)?\)?)?"
_TIME = r"(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?"

# 2026.11.20 / 2026-11-20 / 2026/11/20 / 26.11.20 / 2026년 11월 20일
_FULL = rf"(?P<{{p}}y>(?:20)?\d{{2}})\s*[.\-/년]\s*(?P<{{p}}m>\d{{1,2}})\s*[.\-/월]\s*(?P<{{p}}d>\d{{1,2}})\s*일?{_DOW}{_TIME}"
# 11.20 / 11/20 / 11월 20일
_SHORT = rf"(?P<{{p}}m>\d{{1,2}})\s*[.\-/월]\s*(?P<{{p}}d>\d{{1,2}})\s*일?{_DOW}{_TIME}"
# 20일 (같은 달)
_DAYONLY = rf"(?P<{{p}}d>\d{{1,2}})\s*일{_DOW}{_TIME}"


def _pat(tpl: str, prefix: str) -> str:
    return tpl.replace("{p}", prefix)


_RANGE_PATTERNS = [
    re.compile(_pat(_FULL, "s") + _SEP + _pat(_FULL, "e")),
    re.compile(_pat(_FULL, "s") + _SEP + _pat(_SHORT, "e")),
    re.compile(_pat(_SHORT, "s") + _SEP + _pat(_SHORT, "e")),
    re.compile(_pat(_SHORT, "s") + _SEP + _pat(_DAYONLY, "e")),
]
_UNTIL_PATTERNS = [
    re.compile(r"(?:~|∼|까지\s*)\s*" + _pat(_FULL, "e")),
    re.compile(r"(?:~|∼)\s*" + _pat(_SHORT, "e")),
    re.compile(_pat(_FULL, "e") + r"\s*까지"),
    re.compile(_pat(_SHORT, "e") + r"\s*까지"),
]


def _year(y: Optional[str], ref: date) -> int:
    if not y:
        return ref.year
    y_int = int(y)
    return y_int + 2000 if y_int < 100 else y_int


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_period(text: str, ref: Optional[date] = None) -> tuple[Optional[date], Optional[date]]:
    """한국 쇼핑몰식 기간 표기를 (시작일, 종료일)로. 연도 생략 시 ref 기준, 해 넘김 보정."""
    if not text:
        return None, None
    ref = ref or datetime.now(KST).date()
    t = re.sub(r"\s+", " ", text)

    for pat in _RANGE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        g = m.groupdict()
        sy = _year(g.get("sy"), ref)
        sm = int(g["sm"])
        start = _safe_date(sy, sm, int(g["sd"]))
        ey = _year(g.get("ey"), ref) if g.get("ey") else sy
        em = int(g["em"]) if g.get("em") else sm
        end = _safe_date(ey, em, int(g["ed"]))
        if start and end and end < start and not g.get("ey"):
            end = _safe_date(ey + 1, em, int(g["ed"]))  # 12.20 ~ 01.05
        if start and not g.get("sy") and (ref - start).days > 200:
            # 연도 없는 1월 날짜를 11월에 본 경우 등: 내년으로 해석
            start = _safe_date(start.year + 1, start.month, start.day)
            end = _safe_date(end.year + 1, end.month, end.day) if end else None
        if start and end:
            return start, end

    for pat in _UNTIL_PATTERNS:
        m = pat.search(t)
        if m:
            g = m.groupdict()
            end = _safe_date(_year(g.get("ey"), ref), int(g["em"]), int(g["ed"]))
            if end and not g.get("ey") and (ref - end).days > 200:
                end = _safe_date(end.year + 1, end.month, end.day)
            if end:
                return None, end
    return None, None


def parse_date_value(v) -> Optional[date]:
    """JSON 필드 값(epoch ms/s, '20261120', '2026-11-20T..')을 date로."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{10,13}", v)):
        n = int(v)
        if n > 10**12:
            n //= 1000
        if 946684800 < n < 4102444800:  # 2000~2100
            return datetime.fromtimestamp(n, KST).date()
        return None
    s = str(v).strip()
    m = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})(\d{0,6})", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    return None


# ── 혜택·할인 ────────────────────────────────────────
BENEFIT_RULES = [
    ("할인", r"\d{1,2}\s*%|할인|세일|sale|특가|최저가|off\b"),
    ("쿠폰", r"쿠폰|coupon"),
    ("적립", r"적립|포인트|캐시백|머니\s*\d|리워드"),
    ("카드혜택", r"카드\s*(?:할인|청구|즉시)|청구할인|무이자"),
    ("경품·추첨", r"경품|추첨|응모|럭키|드로우|룰렛|뽑기|당첨"),
    ("사은품", r"사은품|증정|기프트|gift"),
    ("1+1", r"1\s*\+\s*1|2\s*\+\s*1|원\s*플러스\s*원"),
    ("무료배송", r"무료\s*배송|무배"),
]


def extract_benefits(text: str) -> list[str]:
    t = (text or "").lower()
    return [name for name, pat in BENEFIT_RULES if re.search(pat, t, re.I)]


def extract_max_discount(text: str) -> Optional[int]:
    vals = [int(v) for v in re.findall(r"(\d{1,2})\s*%", text or "") if 0 < int(v) < 100]
    return max(vals) if vals else None


# ── 분류 ────────────────────────────────────────────
CATEGORY_RULES = [
    ("명품", r"명품|럭셔리|luxury|구찌|샤넬|프라다|버버리|몽클레르"),
    ("뷰티", r"뷰티|beauty|화장품|코스메틱|스킨|메이크업|향수|헤어|바디|아모레|설화수|올리브영"),
    ("패션", r"패션|의류|아우터|패딩|코트|니트|신발|슈즈|스니커즈|가방|잡화|언더웨어|속옷|데님|스타일|룩|fw|ss\b|캠페인"),
    ("식품", r"식품|푸드|먹거리|신선|과일|정육|한우|수산|간편식|밀키트|김치|커피|간식|건강식품|홍삼|영양제"),
    ("가전·디지털", r"가전|디지털|tv|노트북|pc|모니터|스마트폰|갤럭시|아이폰|애플|태블릿|청소기|냉장고|세탁기|에어컨|건조기|이어폰|카메라|게임"),
    ("가구·인테리어", r"가구|인테리어|침대|매트리스|소파|리빙\s*페어|홈데코|조명|커튼"),
    ("생활·주방", r"생활|주방|키친|세제|휴지|욕실|수납|청소|생필품|리빙"),
    ("유아동", r"유아|아동|키즈|kids|베이비|출산|육아|기저귀|장난감|완구"),
    ("스포츠·레저", r"스포츠|아웃도어|골프|러닝|캠핑|등산|피트니스|요가|스키|자전거"),
    ("여행·티켓", r"여행|항공|호텔|숙박|투어|티켓|공연|레저권|패키지"),
    ("반려동물", r"반려|펫|pet|강아지|고양이|사료"),
    ("도서·취미", r"도서|책|문구|취미|음반|악기"),
]
EVENT_KIND_RE = re.compile(r"응모|추첨|출석|룰렛|댓글|경품|퀴즈|미션|게임|뽑기|럭키드로우|드로우|참여|당첨|공모")
MEGA_SALE_RE = re.compile(r"빅스마일|블랙\s*프라이데이|블프|와우\s*세일|십일절|11절|무진장|대축제|페스타|festa|페스티벌|빅세일|쇼핑\s*축제|코리아\s*세일|연중\s*최대")


def classify_category(text: str) -> str:
    t = (text or "").lower()
    if MEGA_SALE_RE.search(t):
        return "시즌·대형행사"
    for name, pat in CATEGORY_RULES:
        if re.search(pat, t, re.I):
            return name
    return "종합"


def classify_kind(text: str) -> str:
    return "이벤트" if EVENT_KIND_RE.search(text or "") else "기획전"


# ── 상태 ────────────────────────────────────────────
def status_of(start: Optional[date], end: Optional[date], today: Optional[date] = None) -> str:
    today = today or datetime.now(KST).date()
    if start and start > today:
        return "upcoming"
    if end and end < today:
        return "ended"
    if end and (end - today).days <= 3:
        return "ending_soon"
    if start or end:
        return "active"
    return "unknown"


# ── 조립 ────────────────────────────────────────────
_NOISE_TITLE = re.compile(r"^(더보기|바로가기|자세히|more|view|click|go|이동|배너|banner|이미지|image|\s)*$", re.I)


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip(" -|·>")
    return t[:120]


def is_meaningful_title(t: str) -> bool:
    return bool(t) and len(t) >= 4 and not _NOISE_TITLE.match(t)


def normalize(raw: RawPromotion, ref: Optional[date] = None) -> Optional[Promotion]:
    p = _normalize(raw, ref)
    if p and p.products:
        rates = [x.discount_rate for x in p.products if getattr(x, "discount_rate", None)]
        if rates and (p.max_discount or 0) < max(rates):
            p.max_discount = max(rates)
            if "할인" not in p.benefits:
                p.benefits.insert(0, "할인")
    return p


def _normalize(raw: RawPromotion, ref: Optional[date] = None) -> Optional[Promotion]:
    title = clean_title(raw.title)
    if not is_meaningful_title(title):
        return None
    blob = " ".join([title, raw.description or "", raw.period_text or ""])
    start = parse_date_value(raw.start_hint)
    end = parse_date_value(raw.end_hint)
    if not (start and end):
        ps, pe = parse_period(raw.period_text or blob, ref)
        start, end = start or ps, end or pe
    return Promotion(
        id=promo_id(raw.source_id, raw.url),
        source_id=raw.source_id,
        url=raw.url,
        title=title,
        kind=classify_kind(blob),
        category=classify_category(blob),
        benefits=extract_benefits(blob),
        max_discount=extract_max_discount(blob),
        start_date=start,
        end_date=end,
        image_url=raw.image_url or "",
        description=clean_title(raw.description)[:200] if raw.description else "",
        period_text=clean_title(raw.period_text)[:80] if raw.period_text else "",
        products=list(raw.products or []),
    )
