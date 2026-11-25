"""기획전 상세 페이지에서 '실제 판매 상품'(이미지·상품명·판매가·정가·할인율·링크)을 뽑는다.

세 경로를 겹쳐 쓴다.
1) DOM 상품 카드: 상품 상세 URL 패턴에 맞는 링크를 감싼 카드에서 이미지·이름·가격 숫자를 읽음
2) JSON: 페이지가 받아온 상품 목록 API 응답에서 이름+가격 필드를 가진 객체
3) JSON-LD(schema.org Product / ItemList)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .normalize import canonical_url, clean_title

GENERIC_PRODUCT_PATTERNS = [
    r"/(vp/)?products?/(?!project\.html|list\.html)[\w-]+", r"/goods/[\w-]+", r"/items?/[\w-]+", r"/prd/", r"/productions/\d+",
    r"/catalog/products/", r"/p/product/", r"/sec/[\w/-]+/buy", r"/item\?",
    r"goodscode=|itemno=|goodsno=|goods_no=|prdid=|itemid=|slitmcd=|pdno=|productno=|product_no=|item_id=|prd_no=|prdno=",
]
_PRICE_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{3,9})\s*(?:원|₩)|(?:₩|￦)\s*(\d{1,3}(?:,\d{3})+|\d{3,9})")
_BARE_PRICE_RE = re.compile(r"(?<![\d.%])(\d{1,3}(?:,\d{3})+)(?![\d%])")
_PCT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*%")
_NOT_NAME = re.compile(r"^(별\s*\d.*|.*개\s*중\s*[\d.]+\s*개.*|\d[\d,]*\s*(원|%)?|무료배송|쿠폰|할인|특가|품절|sold\s*out|new|best|리뷰.*|평점.*|\(?\d+\)?|[★☆\d.]+|장바구니|찜|좋아요|구매.*|.*원\s*~?)$", re.I)
_NAME_NOISE = re.compile(r"(쿠폰\s*적용가|할인\s*전\s*금액|판매가|정상가|할인율|최대\s*혜택가|혜택가|무료배송|평점[\d.]*|후기\s*\(?[\d,]*\)?건?|리뷰\s*[\d,]+)")


_ID_PARAMS = re.compile(r"^(goodscode|itemno|goodsno|goods_no|prdid|itemid|slitmcd|pdno|productno|product_no|item_id|prd_no|"
                        r"prdno|goods_code|goodscode|partnumber|pcode|productid|modelno|model_no|id|no)$", re.I)


def product_key(url: str) -> str:
    """상품 식별 키: 호스트(m./www. 무시)+경로+상품번호 파라미터만. 추적·옵션 파라미터 차이로 중복되지 않게."""
    from urllib.parse import parse_qsl, urlparse
    u = urlparse(url)
    host = re.sub(r"^(m|www|mw|mobile)\.", "", u.netloc.lower())
    ids = sorted((k.lower(), v) for k, v in parse_qsl(u.query) if _ID_PARAMS.match(k))
    if not ids and u.query:   # 모르는 상품번호 파라미터(modelno 등): 추적 파라미터만 빼고 전부 사용
        from .normalize import TRACKING_PARAMS
        ids = sorted((k.lower(), v) for k, v in parse_qsl(u.query) if not TRACKING_PARAMS.match(k))
    return f"{host}{u.path.rstrip('/').lower()}?{'&'.join(f'{k}={v}' for k, v in ids)}"


_JUNK_NAME = re.compile(r"^(상품\s*이미지|이미지|썸네일|thumbnail|image|img|product|상품)$", re.I)


@dataclass
class Product:
    name: str
    url: str = ""
    image_url: str = ""
    price: Optional[int] = None           # 판매가(최종가)
    original_price: Optional[int] = None  # 정가(할인 전)
    discount_rate: Optional[int] = None
    brand: str = ""
    alt_images: list = field(default_factory=list, repr=False)   # 대체 이미지 후보(공용 자리표시 이미지 교체용, 저장 안 함)

    def key(self) -> str:
        return product_key(self.url) if self.url else f"name:{self.name}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("alt_images", None)
        return d


def _to_int(v) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = int(v)
    else:
        # 첫 번째 숫자만 쓴다('6,000-6,000', '6000~6000' 같은 범위·여러 값을 이어 붙이면 60006000원이 된다)
        m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
        if not m:
            return None
        n = int(float(m.group(0).replace(",", "")))
    return n if 100 <= n <= 100_000_000 else None


def finalize_prices(prices: list[int], pct: Optional[int]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    prices = sorted(set(p for p in prices if p))
    if not prices:
        return None, None, None
    price = prices[0]
    original = prices[-1] if len(prices) > 1 and prices[-1] > price else None
    if original and original > price * 20:   # 엉뚱한 숫자(누적판매량 등) 방지
        original = None
    stated = pct
    if stated and original and len(prices) > 2:
        # 적힌 할인율과 맞지 않는 최저 금액(단위 가격·쿠폰가 등)은 버리고, 할인율에 맞는 금액을 판매가로 쓴다
        expect = original * (1 - stated / 100)
        near = [p for p in prices if p < original and abs(p - expect) <= expect * 0.15]
        if near:
            price = min(near, key=lambda p: abs(p - expect))
    if not stated and original:
        pct = round((1 - price / original) * 100)
    if pct is not None and not (0 < pct < 100):
        pct = None
    return price, original, pct


# 가격이 아닌 금액: 적립·포인트·배송비·'n원 이상'·쿠폰 금액·n원 할인
_NOT_PRICE_AMT = re.compile(r"(포인트\s*)?적립\s*(금)?\s*[\d,]+\s*원|[\d,]+\s*원\s*(적립|이상|부터\s*무료|할인\s*쿠폰|쿠폰|캐시백|상당)|"
                            r"(배송비|택배비|쿠폰|캐시백|최대)\s*[\d,]+\s*원|[\d,]+\s*원\s*(off|OFF)|"
                            # 할인 금액(5,000원 할인, 할인 -5,000원, -5,000원) — '할인가 9,990원'은 판매가라 남긴다
                            r"[\d,]+\s*원\s*할인(?!\s*([가전후율률]|적용|[-−–]))|할인\s*(금액)?\s*[:\s]*[-−–]\s*[\d,]+\s*원|(?<![\d,])[-−–]\s*[\d,]+\s*원|"
                            # 단위 가격(100g당 411원, 1개당 569원, (10ml당 120원)) — 판매가로 오인하면 최저가로 잡힌다
                            r"[\d.,]+\s*[가-힣a-zA-Zℓ㎖㎏㎎㎗]{1,3}\s*당\s*[:\s]*[\d,]+\s*원|"
                            r"(단위\s*가격|단가|개당|1개당|\b100\s*(g|ml|mℓ|㎖)\s*당?)\s*[:\s]*[\d,]+\s*원", re.I)
_NOT_PCT = re.compile(r"[\d.]+\s*%\s*(만족|적립|도착|확률|캐시백|페이백|추천|구매)|(만족도?|적립률?|도착\s*확률|확률)\s*[\d.]+\s*%")


def parse_price_text(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    t = re.sub(r"\s+", " ", text or "")
    t = _NOT_PCT.sub(" ", _NOT_PRICE_AMT.sub(" ", t))
    nums = [_to_int(a or b) for a, b in _PRICE_RE.findall(t)]
    if not nums:
        nums = [_to_int(x) for x in _BARE_PRICE_RE.findall(t)]
    pcts = [int(x) for x in _PCT_RE.findall(t) if 0 < int(x) < 100]
    return finalize_prices([n for n in nums if n], max(pcts) if pcts else None)


_GENERIC = set(GENERIC_PRODUCT_PATTERNS)
# 상품 상세가 아닌 목록·카테고리·검색·이벤트 주소(일반 패턴 /product/... 에 걸려도 상품 아님)
NOT_PRODUCT_URL = re.compile(r"(categor|[-_/]list(\b|[-_.?/])|search|brandstore|/brand/|[/-]best\b|best[-_]?product|ranking|"
                             r"review|/cart|login|/event/|/plan/|/exhibition/|/promotion|javascript:|^#)", re.I)


def compile_product_patterns(extra: list[str] | None = None) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in (extra or []) + GENERIC_PRODUCT_PATTERNS]


def is_product_url(url: str, pats: list[re.Pattern]) -> bool:
    """채널 전용 패턴에 맞으면 상품. 일반 패턴은 목록·카테고리 주소가 아니고 상품번호(숫자 3자리+)가 있을 때만."""
    for p in pats:
        if p.search(url):
            if NOT_PRODUCT_URL.search(url):
                return False
            if p.pattern in _GENERIC and not re.search(r"\d{3,}", url):
                continue
            return True
    return False


# 머리말·메뉴·바닥글 안의 링크는 기획전 상품이 아님(카테고리 메뉴의 배너·바로가기)
_CHROME_CLS = re.compile(r"(^|[-_])(gnb|lnb|snb|nav|navi|navigation|header|footer|menu|depth\d?|allmenu|sitemap|quick)([-_]|$)", re.I)


def _in_chrome(tag: Tag) -> bool:
    for anc in tag.parents:
        if not isinstance(anc, Tag) or anc.name in ("body", "html", "[document]"):
            continue
        if anc.name in ("header", "nav", "footer"):
            return True
        tokens = (anc.get("class") or []) + [anc.get("id") or ""]
        if any(_CHROME_CLS.search(x) for x in tokens if x):
            return True
    return False


def _card_for(a: Tag, pats, base: str) -> Tag:
    """같은 상품 링크만 들어 있는 가장 큰 조상 = 상품 카드."""
    own = product_key(urljoin(base, a["href"]))
    node = a
    for _ in range(5):
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in ("body", "html", "ul", "ol", "section", "main"):
            break
        hrefs = {product_key(urljoin(base, x["href"])) for x in parent.find_all("a", href=True)
                 if is_product_url(urljoin(base, x["href"]), pats)}
        if len(hrefs) > 1 or len(parent.get_text(" ", strip=True)) > 400:
            break
        node = parent
        if own not in hrefs:
            break
    return node


_BAD_IMG = re.compile(r"icon|badge|logo|blank|sprite|star|loading|noimg|no_img|spacer|transparent|\{\{", re.I)
_URL_IN = re.compile(r"""url\(\s*['"]?([^'")]+)""")
_IMG_URL = re.compile(r"""(https?:)?//[^\s'"]+?\.(?:jpe?g|png|webp|gif|avif)(?:\?[^\s'"]*)?""", re.I)


def _first_src(v: str, attr: str = "src") -> str:
    """srcset 은 '주소 너비w, 주소 너비w' 꼴이고 주소 안에 쉼표가 들어갈 수 있다(나이키 c_limit,w_592) → 공백 앞까지가 주소."""
    v = v.strip()
    if "srcset" in attr or re.search(r"\s\d+(\.\d+)?[wx](,|$)", v):
        return v.split()[0].rstrip(",")
    return v


def _img_candidates(tag: Tag, base: str) -> list[str]:
    out: list[str] = []
    def add(u):
        u = urljoin(base, u)
        if u not in out:
            out.append(u)
    for img in tag.find_all(["img", "source"]):
        for attr in ("data-src", "data-original", "data-lazy-src", "data-lazy", "src", "srcset", "data-srcset"):
            v = (img.get(attr) or "").strip()
            if v and not v.startswith("data:") and not _BAD_IMG.search(v):
                add(_first_src(v, attr))
    # 배경 이미지(style="background-image:url(...)") · 지연 로딩 속성(data-lazyload="{'_src': ...}")
    for el in [tag] + tag.find_all(True):
        for attr in ("style", "data-bg", "data-background", "data-lazyload", "data-bgset"):
            v = el.get(attr)
            if not v:
                continue
            m = _URL_IN.search(v) or _IMG_URL.search(v)
            u = (m.group(1) if m and m.re is _URL_IN else m.group(0)) if m else ""
            if u and not u.startswith("data:") and not _BAD_IMG.search(u):
                add(u)
    return out[:5]


def _img(tag: Tag, base: str) -> str:
    c = _img_candidates(tag, base)
    return c[0] if c else ""


# 용량·수량이 이름에 있는 상품(485ml x 4, 1L, 10족, 5회분 x 3) — 단위 가격이 판매가로 잡히기 쉽다
_QTY_NAME = re.compile(r"\d+(\.\d+)?\s*(ml|mℓ|㎖|ℓ|l|g|kg|㎏|매|입|개입|족|회분|정|캡슐|롤|팩|포|구)\b|\d+\s*(ml|g|l)?\s*[x×]\s*\d+", re.I)


_NUM_UNIT = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*(ml|mℓ|㎖|ℓ|l|g|kg|㎏|매|입|개입|개|족|회분|정|캡슐|롤|팩|포|구|m)?(?![a-z0-9])(?:\s*[x×*]\s*(\d+))?", re.I)


def _unit_divisors(name: str) -> set[float]:
    """이름의 용량·수량으로 나올 수 있는 단위 가격 나눗수(5족→5, 900ml x 2→18(100ml당)·180(10ml당), 1L→10)."""
    out: set[float] = set()
    for m in _NUM_UNIT.finditer(name or ""):
        n, unit, mult = float(m.group(1)), (m.group(2) or "").lower(), int(m.group(3) or 1)
        if not unit and not m.group(3):
            continue
        tot = n * mult
        if unit in ("l", "ℓ", "kg", "㎏"):
            tot *= 1000
        if unit in ("ml", "mℓ", "㎖", "g", "l", "ℓ", "kg", "㎏"):
            out.update({tot / 100, tot / 10, tot / 1000})
        elif unit == "m":
            out.update({tot, tot / 10, tot / 100, float(mult)})
        else:
            out.update({tot, float(mult), n})
    return {d for d in out if d >= 2}


def fix_unit_prices(products: list["Product"], threshold: int = 85) -> int:
    """단위 가격(100ml당 824원, 1족당 1,998원)을 판매가로 잘못 읽은 상품을 바로잡는다.
    (코스트코 2026-11-25: 15,990원 핸드워시가 '100mℓ당 824원' 때문에 95% 할인 824원으로, 양말 5족 9,990원이 1,998원으로 표시됨)
    - 정가 ÷ 판매가가 이름의 용량·수량(5족, 485ml x 4 → 100ml 단위 19.4)과 맞으면 단위 가격
    - 또는 할인율 85% 이상인 용량·수량 상품
    → 큰 금액을 판매가로 두고 할인 표시는 지운다. 바꾼 개수를 돌려준다."""
    n = 0
    for p in products:
        if not (p.original_price and p.price and p.original_price > p.price):
            continue
        ratio = p.original_price / p.price
        # 비율 3.4배(할인 71%) 이상일 때만 — 2·3배는 반값·1+1 같은 실제 할인과 겹친다
        hit = ratio >= 3.4 and any(abs(ratio - d) <= d * 0.03 for d in _unit_divisors(p.name))
        if hit or (p.discount_rate and p.discount_rate >= threshold and _QTY_NAME.search(p.name or "")):
            p.price, p.original_price, p.discount_rate = p.original_price, None, None
            n += 1
    return n


def fix_discount_amounts(products: list["Product"]) -> int:
    """판매가로 잡힌 값이 1,000원 단위 '할인 금액'인 경우(코스트코: 정가 89,900원·10,000원 할인 → 79,900원)
    판매가 = 정가 - 할인 금액. 코스트코 가격은 90·990원으로 끝나고 할인 금액은 1,000원 단위라 구분된다."""
    n = 0
    for p in products:
        if (p.original_price and p.price and p.price < p.original_price and p.price % 1000 == 0
                and (p.original_price % 1000 or p.price % 10000 == 0)):
            p.price = p.original_price - p.price
            p.discount_rate = round((1 - p.price / p.original_price) * 100)
            n += 1
    return n


def fix_shared_images(products: list["Product"], min_names: int = 4) -> int:
    """여러 상품(이름이 다른 4개 이상)이 같은 이미지 주소를 쓰면 '이미지 준비 중' 같은 공용 자리표시 이미지다.
    대체 후보가 있으면 바꾸고, 없으면 비워서 사이트가 상품명 자리표시로 보여 주게 한다. 바꾼 개수를 돌려준다."""
    names: dict[str, set] = {}
    for p in products:
        if p.image_url:
            names.setdefault(p.image_url, set()).add(_nk_name(p.name))
    shared = {u for u, ns in names.items() if len(ns) >= min_names}
    n = 0
    for p in products:
        if p.image_url in shared:
            p.image_url = next((u for u in p.alt_images if u not in shared), "")
            n += 1
    return n


def _name(card: Tag) -> str:
    for sel in ("[class*=name]", "[class*=title]", "[class*=tit]", "[class*=prd]", "[class*=goods]"):
        el = card.select_one(sel)
        if el:
            t = clean_title(_NAME_NOISE.sub(" ", el.get_text(" ", strip=True)))
            if len(t) >= 4 and not _NOT_NAME.match(t) and not _PRICE_RE.search(t):
                return t
    img = card.find("img", alt=True)
    lines = [clean_title(_NAME_NOISE.sub(" ", l)) for l in card.get_text("\n", strip=True).split("\n")]
    lines = [l for l in lines if len(l) >= 4 and not _NOT_NAME.match(l) and not _PRICE_RE.fullmatch(l.strip())
             and not re.fullmatch(r"[\d,\s원%~]+", l)]
    if lines:
        return max(lines, key=len)
    if img and len(img["alt"].strip()) >= 4 and not _JUNK_NAME.match(img["alt"].strip()):
        return clean_title(img["alt"])
    return ""


_PRICE_CLS = re.compile(r"price|prc|cost|amount|sale|discount|dc[-_]|percent|rate", re.I)
_PRICE_NOT = re.compile(r"delivery|shipping|dlv|point|reward|review|rating|score|count|qty|satisf|arrival|star|coupon[-_]?(info|txt)", re.I)


def card_prices(card: Tag) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """가격·할인율 요소(class 에 price/sale/discount …)의 글자만 읽는다. '15,000원 이상 무료배송' 같은 안내 숫자를 피하려고.
    가격 요소가 없으면 카드 전체 글자."""
    parts = []
    for el in card.find_all(True):
        cls = " ".join(el.get("class") or [])
        if el.name in ("del", "s", "strike") or (cls and _PRICE_CLS.search(cls) and not _PRICE_NOT.search(cls)):
            if not any(el in p.descendants for p in parts if isinstance(p, Tag)):
                parts.append(el)
    # 정가(<del>)만 가격 요소로 잡히고 판매가는 일반 글자인 카드도 있으므로, 판매가 요소가 있을 때만 좁혀 읽는다
    if any(p.name not in ("del", "s", "strike") and parse_price_text(p.get_text(" ", strip=True))[0] for p in parts):
        got = parse_price_text(" ".join(p.get_text(" ", strip=True) for p in parts))
        if got[0]:
            return got
    return parse_price_text(card.get_text(" ", strip=True))


def _brand(card: Tag) -> str:
    el = card.select_one("[class*=brand]")
    return clean_title(el.get_text(" ", strip=True))[:40] if el else ""


_ID_ATTR = re.compile(r"^data-(prd|prod|product|goods|item|sku)[-_]?(cd|code|no|num|id|seq)$", re.I)


def product_link(link: dict | None, values: dict, field: str = "url") -> str:
    """채널 설정 product_link: {key: 상품번호 필드명, url: '...{id}...', image: '...{id}...'} 로 상품 주소(또는 이미지)를 만든다."""
    if not link or not link.get(field):
        return ""
    keys = [k.lower() for k in ([link["key"]] if isinstance(link.get("key"), str) else link.get("key") or [])]
    for k, v in values.items():
        nk = k.lower().removeprefix("data-").replace("-", "").replace("_", "")
        if (not keys or nk in [x.replace("_", "") for x in keys]) and v not in (None, "") and re.fullmatch(r"[\w.-]{2,40}", str(v)):
            return link[field].replace("{id}", str(v))
    return ""


def _data_cards(soup: BeautifulSoup, page_url: str, link: dict | None) -> list[Product]:
    """링크가 javascript: 인 상품 카드: data-prdcd / data-goods-cd 같은 상품번호 속성 + 이미지 + 가격."""
    out: dict[str, Product] = {}
    for el in soup.find_all(lambda x: isinstance(x, Tag) and any(_ID_ATTR.match(a) for a in x.attrs)):
        if el.name in ("button", "input", "a", "span", "i") or _in_chrome(el):
            continue
        attrs = {a: v for a, v in el.attrs.items() if _ID_ATTR.match(a)}
        pid = next(iter(attrs.values()))
        if not pid or pid in out:
            continue
        text = el.get_text(" ", strip=True)
        if len(text) > 500:
            continue
        price, orig, pct = card_prices(el)
        name = clean_title(el.get("data-prdnm") or el.get("data-name") or el.get("data-goods-nm") or "") or _name(el)
        img = _img(el, page_url) or product_link(link, attrs, "image")
        if not name or not (price or img):
            continue
        url = product_link(link, {**attrs, **{a: v for a, v in el.attrs.items() if isinstance(v, str)}})
        if not url:
            a = el.find("a", href=True)
            href = a["href"].strip() if a else ""
            url = urljoin(page_url, href) if href and not href.startswith(("#", "javascript")) else ""
        out[pid] = Product(name=name[:100], url=url, image_url=img, price=price, original_price=orig,
                           discount_rate=pct, brand=_brand(el))
    return list(out.values())


def _alt_index(soup: BeautifulSoup, page_url: str) -> dict[str, tuple[str, str]]:
    """이미지 alt(=상품명) → (이미지, 감싼 링크). JSON 으로만 잡힌 상품의 이미지·주소를 채울 때 쓴다."""
    idx: dict[str, tuple[str, str]] = {}
    for img in soup.find_all("img", alt=True):
        k = _nk_name(img["alt"])
        if len(k) < 3 or k in idx:
            continue
        v = (img.get("data-src") or img.get("data-original") or img.get("src") or "").strip()
        src = urljoin(page_url, _first_src(v)) if v and not v.startswith("data:") and not _BAD_IMG.search(v) else ""
        a = img.find_parent("a", href=True)
        href = a["href"].strip() if a else ""
        idx[k] = (src, urljoin(page_url, href) if href and not href.startswith(("#", "javascript")) else "")
    return idx


def _nk_name(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def fill_from_page(products: list[Product], html: str, page_url: str, pats: list[re.Pattern]) -> None:
    """이미지·주소 없는 상품(JSON 경로)을 같은 페이지의 <img alt="상품명"> 으로 채운다."""
    if not any(not p.image_url or not p.url for p in products):
        return
    idx = _alt_index(BeautifulSoup(html, "html.parser"), page_url)
    for p in products:
        hit = idx.get(_nk_name(p.name))
        if not hit:
            continue
        p.image_url = p.image_url or hit[0]
        if not p.url and hit[1] and is_product_url(hit[1], pats):
            p.url = hit[1]


def drop_bare(products: list[Product]) -> list[Product]:
    """대부분 상품에 이미지·주소가 있는데 둘 다 없는 상품은 다른 응답에서 겹쳐 잡힌 것(예: 영문 상품명)이라 뺀다."""
    rich = [p for p in products if p.image_url or p.url]
    return rich if len(rich) >= max(3, len(products) // 2) else products


def products_from_html(html: str, page_url: str, pats: list[re.Pattern], link: dict | None = None) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    out: dict[str, Product] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(page_url, a["href"].strip())
        if not is_product_url(url, pats) or _in_chrome(a):
            continue
        key = product_key(url)
        card = _card_for(a, pats, page_url)
        price, orig, pct = card_prices(card)
        name = _name(card)
        if not name:
            continue
        cands = _img_candidates(card, page_url)
        p = Product(name=name[:100], url=url, image_url=cands[0] if cands else "", alt_images=cands[1:], price=price,
                    original_price=orig, discount_rate=pct, brand=_brand(card))
        prev = out.get(key)
        if prev is None or (p.price and not prev.price) or (len(p.name) > len(prev.name) and p.price):
            if prev:
                p.image_url = p.image_url or prev.image_url
            out[key] = p
        else:
            prev.image_url = prev.image_url or p.image_url
    seen = {_nk_name(p.name) for p in out.values()}
    extra = [p for p in _data_cards(soup, page_url, link) if _nk_name(p.name) not in seen]
    return list(out.values()) + extra


# ── JSON ─────────────────────────────────────────
NAME_KEYS = re.compile(r"^((goods|item|product|prd|prod|deal|sku)_?(name|nm|title|ttl)|name|title|display_?name)$", re.I)
PRICE_KEYS = re.compile(r"^(final_?price|sales?_?price|sell_?price|origin_?price|selling_?price|discount(ed)?_?price|dc_?price|benefit_?price|"
                        r"coupon_?price|best_?price|price|cur_?price|current_?price|disp_?price|lowest_?price|prc|sale_?prc|sl_?prc|"
                        r"normal_?price|original_?price|org_?price|consumer_?price|list_?price|retail_?price|market_?price|cust_?price|nor_?prc)$", re.I)
ORIG_KEYS = re.compile(r"^(normal|original|org|consumer|list|retail|market|cust|before|origin|nor)_?(price|prc)$", re.I)
RATE_KEYS = re.compile(r"^(discount|dc|sale|benefit)_?(rate|ratio|percent|pct)$", re.I)
PURL_KEYS = re.compile(r"^((link|landing|item|goods|product|detail|click|move|pc|mobile|mo|redirect|share|web)_?(url|link|uri))$|^(url|link|href)$", re.I)
# 이미지 필드: imageUrl, basicImage, list_image_url, image128Url, prdImgUrl, thumbnailUrl, productThumbnailUrlList[0].thumbnailUrl …
PIMG_KEYS = re.compile(r"(image|img|thumbnail|thumb)\w*?(url|path|src|list)?$", re.I)
_PIMG_SKIP = re.compile(r"(count|cnt|yn|type|code|cd|width|height|size|alt|badge|icon|logo|sticker|flag)$", re.I)
BRAND_KEYS = re.compile(r"^(brand|brand_?(name|nm))$", re.I)


def _nk(k: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _get(d: dict, pat: re.Pattern):
    for k, v in d.items():
        if pat.match(_nk(k)) or pat.match(k):
            if isinstance(v, dict):
                v = v.get("name") or v.get("url") or v.get("value")
            if v not in (None, "", [], {}):
                return k, v
    return None, None


def _walk(o, depth=0):
    if depth > 12:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o[:1000]:
            yield from _walk(v, depth + 1)


def _img_like(v) -> str:
    if isinstance(v, dict):
        v = next((x for k, x in v.items() if isinstance(x, str) and re.search(r"url|src|path", k, re.I)), "")
    if isinstance(v, list):
        v = next((_img_like(x) for x in v if _img_like(x)), "")
    if not isinstance(v, str):
        return ""
    v = v.strip()
    if not v or v.startswith("data:") or _BAD_IMG.search(v):
        return ""
    return v if re.search(r"\.(jpe?g|png|webp|gif|avif)(\?|$)|/images?/|image\.|img\.|/thumb", v, re.I) else ""


def _json_img(d: dict) -> str:
    """이미지 후보 필드 중 가장 큰 것(64x64 같은 작은 썸네일보다 128·원본 우선)."""
    cands = []
    for k, v in d.items():
        nk = _nk(k)
        if PIMG_KEYS.search(nk) and not _PIMG_SKIP.search(nk):
            u = _img_like(v)
            if u:
                m = re.search(r"(\d{2,4})", nk) or re.search(r"(\d{2,4})x\d{2,4}", u)
                size = int(m.group(1)) if m else 500
                cands.append((size, u))
    return max(cands)[1] if cands else ""


def products_from_json(payload, page_url: str, link_tpl: dict | None = None) -> list[Product]:
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    out = []
    for d in _walk(payload):
        _, name = _get(d, NAME_KEYS)
        if not isinstance(name, str) or len(name.strip()) < 3:
            continue
        prices, orig = [], None
        for k, v in d.items():
            nk = _nk(k)
            if PRICE_KEYS.match(nk) or PRICE_KEYS.match(k):
                n = _to_int(v)
                if n:
                    prices.append(n)
                    if ORIG_KEYS.match(nk) or ORIG_KEYS.match(k):
                        orig = n
        if not prices:
            continue
        _, rate = _get(d, RATE_KEYS)
        m = re.fullmatch(r"\s*(\d{1,2})(\.\d+)?\s*%?\s*", str(rate)) if rate is not None else None
        price, original, pct = finalize_prices(prices, int(m.group(1)) if m else None)
        if orig and orig > (price or 0):
            original = orig
        _, link = _get(d, PURL_KEYS)
        img = _json_img(d)
        _, brand = _get(d, BRAND_KEYS)
        url = urljoin(page_url, link) if isinstance(link, str) and not link.startswith(("javascript", "#")) else ""
        if link_tpl:
            vals = {k: v for k, v in d.items() if isinstance(v, (str, int)) and not isinstance(v, bool)}
            url = url or product_link(link_tpl, vals)
            img = img or product_link(link_tpl, vals, "image")
        out.append(Product(
            name=clean_title(re.sub(r"<[^>]+>", " ", name))[:100],
            url=url,
            image_url=urljoin(page_url, img) if img else "",
            price=price, original_price=original, discount_rate=pct,
            brand=clean_title(brand)[:40] if isinstance(brand, str) else "",
        ))
    return out


def products_from_jsonld(html: str, page_url: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for d in _walk(data):
            if d.get("@type") not in ("Product", ["Product"]):
                continue
            offers = d.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _to_int(offers.get("price") or offers.get("lowPrice"))
            img = d.get("image")
            img = img[0] if isinstance(img, list) and img else img
            brand = d.get("brand")
            out.append(Product(
                name=clean_title(d.get("name", ""))[:100], url=urljoin(page_url, d.get("url") or offers.get("url") or ""),
                image_url=urljoin(page_url, img) if isinstance(img, str) else "", price=price,
                brand=(brand.get("name") if isinstance(brand, dict) else brand or "")[:40] if brand else "",
            ))
    return [p for p in out if p.name]


def merge_products(lists: list[list[Product]], limit: int = 60) -> list[Product]:
    by: dict[str, Product] = {}
    order: list[str] = []
    by_name: dict[str, str] = {}

    def nm(x: Product) -> str:
        return re.sub(r"[\s\W_]+", "", x.name.lower())

    for lst in lists:
        for p in lst:
            k = p.key()
            if k not in by and nm(p) in by_name:      # URL 없는 JSON 상품 ↔ 같은 이름의 DOM 상품
                k = by_name[nm(p)]
            q = by.get(k)
            if q is None:
                by[k] = p
                order.append(k)
                by_name.setdefault(nm(p), k)
                continue
            for f in ("image_url", "price", "original_price", "discount_rate", "brand", "url"):
                if not getattr(q, f):
                    setattr(q, f, getattr(p, f))
    # 가격 있는 상품 우선, 페이지 노출 순서 유지
    items = [by[k] for k in order]
    for p in items:
        if p.original_price and p.price and p.original_price <= p.price:
            p.original_price = None
    items.sort(key=lambda p: p.price is None)
    return items[:limit]
