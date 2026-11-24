"""기획전 상세 페이지에서 '실제 판매 상품'(이미지·상품명·판매가·정가·할인율·링크)을 뽑는다.

세 경로를 겹쳐 쓴다.
1) DOM 상품 카드: 상품 상세 URL 패턴에 맞는 링크를 감싼 카드에서 이미지·이름·가격 숫자를 읽음
2) JSON: 페이지가 받아온 상품 목록 API 응답에서 이름+가격 필드를 가진 객체
3) JSON-LD(schema.org Product / ItemList)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .normalize import canonical_url, clean_title

GENERIC_PRODUCT_PATTERNS = [
    r"/(vp/)?products?/[\w-]+", r"/goods/[\w-]+", r"/items?/[\w-]+", r"/prd/", r"/productions/\d+",
    r"/catalog/products/", r"/p/product/", r"/sec/[\w/-]+/buy", r"/item\?",
    r"goodscode=|itemno=|goodsno=|goods_no=|prdid=|itemid=|slitmcd=|pdno=|productno=|product_no=|item_id=|prd_no=|prdno=",
]
_PRICE_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{3,9})\s*(?:원|₩)|(?:₩|￦)\s*(\d{1,3}(?:,\d{3})+|\d{3,9})")
_BARE_PRICE_RE = re.compile(r"(?<![\d.%])(\d{1,3}(?:,\d{3})+)(?![\d%])")
_PCT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*%")
_NOT_NAME = re.compile(r"^(\d[\d,]*\s*(원|%)?|무료배송|쿠폰|할인|특가|품절|sold\s*out|new|best|리뷰.*|평점.*|\(?\d+\)?|[★☆\d.]+|장바구니|찜|좋아요|구매.*|.*원\s*~?)$", re.I)
_NAME_NOISE = re.compile(r"(쿠폰\s*적용가|할인\s*전\s*금액|판매가|정상가|할인율|최대\s*혜택가|혜택가|무료배송|평점[\d.]*|후기\s*\(?[\d,]*\)?건?|리뷰\s*[\d,]+)")


_ID_PARAMS = re.compile(r"^(goodscode|itemno|goodsno|goods_no|prdid|itemid|slitmcd|pdno|productno|product_no|item_id|prd_no|"
                        r"prdno|goods_code|goodscode|partnumber|pcode|productid|id|no)$", re.I)


def product_key(url: str) -> str:
    """상품 식별 키: 호스트(m./www. 무시)+경로+상품번호 파라미터만. 추적·옵션 파라미터 차이로 중복되지 않게."""
    from urllib.parse import parse_qsl, urlparse
    u = urlparse(url)
    host = re.sub(r"^(m|www|mw|mobile)\.", "", u.netloc.lower())
    ids = sorted((k.lower(), v) for k, v in parse_qsl(u.query) if _ID_PARAMS.match(k))
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

    def key(self) -> str:
        return product_key(self.url) if self.url else f"name:{self.name}"

    def to_dict(self) -> dict:
        return asdict(self)


def _to_int(v) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = int(v)
    else:
        s = re.sub(r"[^\d.]", "", str(v))
        if not s:
            return None
        n = int(float(s))
    return n if 100 <= n <= 100_000_000 else None


def finalize_prices(prices: list[int], pct: Optional[int]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    prices = sorted(set(p for p in prices if p))
    if not prices:
        return None, None, None
    price = prices[0]
    original = prices[-1] if len(prices) > 1 and prices[-1] > price else None
    if original and original > price * 20:   # 엉뚱한 숫자(누적판매량 등) 방지
        original = None
    if not pct and original:
        pct = round((1 - price / original) * 100)
    if pct is not None and not (0 < pct < 100):
        pct = None
    return price, original, pct


def parse_price_text(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    t = re.sub(r"\s+", " ", text or "")
    nums = [_to_int(a or b) for a, b in _PRICE_RE.findall(t)]
    if not nums:
        nums = [_to_int(x) for x in _BARE_PRICE_RE.findall(t)]
    pcts = [int(x) for x in _PCT_RE.findall(t) if 0 < int(x) < 100]
    return finalize_prices([n for n in nums if n], max(pcts) if pcts else None)


def compile_product_patterns(extra: list[str] | None = None) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in (extra or []) + GENERIC_PRODUCT_PATTERNS]


def is_product_url(url: str, pats: list[re.Pattern]) -> bool:
    return any(p.search(url) for p in pats)


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


def _img(tag: Tag, base: str) -> str:
    for img in tag.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "srcset", "data-srcset"):
            v = img.get(attr)
            if v and not v.startswith("data:") and not re.search(r"icon|badge|logo|blank|sprite|star", v, re.I):
                return urljoin(base, v.split(",")[0].strip().split(" ")[0])
    return ""


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


def _brand(card: Tag) -> str:
    el = card.select_one("[class*=brand]")
    return clean_title(el.get_text(" ", strip=True))[:40] if el else ""


def products_from_html(html: str, page_url: str, pats: list[re.Pattern]) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    out: dict[str, Product] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(page_url, a["href"].strip())
        if not is_product_url(url, pats):
            continue
        key = product_key(url)
        card = _card_for(a, pats, page_url)
        price, orig, pct = parse_price_text(card.get_text(" ", strip=True))
        name = _name(card)
        if not name:
            continue
        p = Product(name=name[:100], url=url, image_url=_img(card, page_url), price=price,
                    original_price=orig, discount_rate=pct, brand=_brand(card))
        prev = out.get(key)
        if prev is None or (p.price and not prev.price) or (len(p.name) > len(prev.name) and p.price):
            if prev:
                p.image_url = p.image_url or prev.image_url
            out[key] = p
        else:
            prev.image_url = prev.image_url or p.image_url
    return list(out.values())


# ── JSON ─────────────────────────────────────────
NAME_KEYS = re.compile(r"^((goods|item|product|prd|prod|deal|sku)_?(name|nm|title|ttl)|name|title|display_?name)$", re.I)
PRICE_KEYS = re.compile(r"^(final_?price|sale_?price|sell_?price|selling_?price|discount(ed)?_?price|dc_?price|benefit_?price|"
                        r"coupon_?price|best_?price|price|cur_?price|current_?price|disp_?price|lowest_?price|prc|sale_?prc|sl_?prc|"
                        r"normal_?price|original_?price|org_?price|consumer_?price|list_?price|retail_?price|market_?price|cust_?price|nor_?prc)$", re.I)
ORIG_KEYS = re.compile(r"^(normal|original|org|consumer|list|retail|market|cust|before|origin|nor)_?(price|prc)$", re.I)
RATE_KEYS = re.compile(r"^(discount|dc|sale|benefit)_?(rate|ratio|percent|pct)$", re.I)
PURL_KEYS = re.compile(r"^((link|landing|item|goods|product|detail|click|move|pc|mobile|mo)_?(url|link|uri))$|^(url|link|href)$", re.I)
PIMG_KEYS = re.compile(r"(image|img|thumbnail|thumb)(_?(url|path|src))?$", re.I)
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


def products_from_json(payload, page_url: str) -> list[Product]:
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
        _, img = _get(d, PIMG_KEYS)
        _, brand = _get(d, BRAND_KEYS)
        out.append(Product(
            name=clean_title(re.sub(r"<[^>]+>", " ", name))[:100],
            url=urljoin(page_url, link) if isinstance(link, str) and not link.startswith(("javascript", "#")) else "",
            image_url=urljoin(page_url, img) if isinstance(img, str) and not img.startswith("data:") else "",
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
    items.sort(key=lambda p: p.price is None)
    return items[:limit]
