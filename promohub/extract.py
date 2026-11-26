"""사이트별 셀렉터 없이 기획전 후보를 뽑는 추출기.

1) DOM 링크 탐색: <a href>가 채널의 기획전 URL 패턴에 맞으면 후보. 제목은 링크 텍스트 →
   이미지 alt → aria-label/title 순, 기간은 링크를 감싼 카드 안의 날짜 텍스트에서 찾는다.
2) JSON 수확: 페이지가 내부적으로 받아온 JSON(배너·기획전 API)을 재귀로 훑어
   '링크 + 제목'을 가진 객체를 후보로 만든다. 시작/종료일 필드가 있으면 그대로 쓴다.
3) 상세 메타: 기획전 상세 페이지의 og:title / og:image / 본문 날짜로 빈 칸을 채운다.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import Source
from .models import RawPromotion
from .normalize import canonical_url, clean_title, is_meaningful_title, parse_period

DATE_HINT_RE = re.compile(r"\d{1,4}\s*[.\-/년월]\s*\d{1,2}.{0,25}(?:~|∼|까지)|(?:~|∼)\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}")
PERIOD_SNIPPET_RE = re.compile(r"[^\n]{0,30}(?:\d{1,4}\s*[.\-/년월]\s*\d{1,2})[^\n]{0,40}")


def _img_url(img: Tag, base: str) -> str:
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-srcset", "srcset"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            from .products import _first_src
            return urljoin(base, _first_src(v, attr))
    return ""


def _bg_image(tag: Tag, base: str) -> str:
    for t in [tag, *tag.find_all(style=True)]:
        m = re.search(r"url\(['\"]?([^'\")]+)", t.get("style") or "")
        if m:
            return urljoin(base, m.group(1))
    return ""


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "strong", "b", "em", "dt")


def _card_container(a: Tag, max_up: int = 3) -> Tag:
    """링크를 감싼 카드(li/article/div) — 기간·부제 텍스트를 찾을 범위."""
    node = a
    for _ in range(max_up):
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in ("body", "html"):
            break
        # 링크가 여러 개 들어 있는 큰 섹션까지 올라가지 않는다
        if len(parent.find_all("a", href=True)) > 2:
            break
        node = parent
    return node


def _period_from_text(text: str) -> str:
    for m in PERIOD_SNIPPET_RE.finditer(text):
        s = m.group(0)
        if DATE_HINT_RE.search(s) or parse_period(s)[1]:
            return s.strip()
    return ""


def extract_from_html(html: str, page_url: str, source: Source) -> list[RawPromotion]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    out: dict[str, RawPromotion] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "tel:", "mailto:")):
            continue
        url = urljoin(page_url, href)
        link_text = clean_title(a.get_text(" ", strip=True))
        if not source.accepts(url, link_text if "기획전" in link_text or "이벤트" in link_text else ""):
            continue
        img = a.find("img")
        heading = a.find(HEADING_TAGS)
        title = ""
        for cand in (
            heading.get_text(" ", strip=True) if heading else "",
            link_text,
            img.get("alt", "") if img else "",
            a.get("aria-label", ""),
            a.get("title", ""),
        ):
            cand = clean_title(cand)
            if is_meaningful_title(cand):
                title = cand
                break
        card = _card_container(a)
        card_text = card.get_text("\n", strip=True)
        if not title:
            # 카드 안의 첫 의미 있는 줄
            for line in card_text.split("\n"):
                if is_meaningful_title(clean_title(line)) and not DATE_HINT_RE.search(line):
                    title = clean_title(line)
                    break
        image = (_img_url(img, page_url) if img else "") or _bg_image(a, page_url)
        if not image:
            ci = card.find("img")
            image = _img_url(ci, page_url) if ci else ""
        period = _period_from_text(card_text)
        desc_lines = [l for l in card_text.split("\n")
                      if l and clean_title(l) != title and l not in period and not DATE_HINT_RE.search(l)]
        key = canonical_url(url)
        prev = out.get(key)
        cand = RawPromotion(
            source_id=source.id, url=url, title=title, image_url=image,
            period_text=period, description=" ".join(desc_lines)[:200], origin="dom",
        )
        if prev is None or (len(cand.title) > len(prev.title) and is_meaningful_title(cand.title)):
            if prev:  # 빈 필드 보존
                cand.image_url = cand.image_url or prev.image_url
                cand.period_text = cand.period_text or prev.period_text
            out[key] = cand
        else:
            prev.image_url = prev.image_url or image
            prev.period_text = prev.period_text or period
    return list(out.values())


# ── JSON ───────────────────────────────────────────
URL_KEYS = re.compile(r"^(link|url|href|landing|target|move|banner|click|web|mobile|pc|app)?_?(link|url|uri|href)(_?(pc|mo|mobile|web))?$|^(linkurl|landingurl|clickurl|moveurl|weburl|mobileurl|pcurl|targeturl|link)$", re.I)
TITLE_KEYS = [  # 우선순위 순
    re.compile(r"^((event|plan|promotion|exhibit|campaign|display|banner)_?(title|name|nm|ttl)|main_?title|title|subject|headline)$", re.I),
    re.compile(r"^(name|nm|ttl|text|copy|main_?copy|banner_?text)$", re.I),
    re.compile(r"^alt$", re.I),
]
SUB_KEYS = re.compile(r"^(sub_?title|subtitle|sub_?text|sub_?copy|desc|description|summary|benefit|catchphrase)$", re.I)
IMG_KEYS = re.compile(r"(image|img|thumbnail|thumb|banner)(_?(url|path|src))?$", re.I)
START_KEYS = re.compile(r"^(start|begin|disp_?start|display_?start|evt_?start|event_?start|open|from|sale_?start|strt)_?(date|dt|dttm|time|at|ymd)?$|^(start_?(date|dt|at|time))$", re.I)
END_KEYS = re.compile(r"^(end|finish|close|disp_?end|display_?end|evt_?end|event_?end|to|sale_?end|expire)_?(date|dt|dttm|time|at|ymd)?$|^(end_?(date|dt|at|time))$", re.I)
PERIOD_KEYS = re.compile(r"period|date_?text|duration|기간", re.I)


def _norm_key(k: str) -> str:
    # camelCase → snake
    return re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _walk(obj, depth=0) -> Iterable[dict]:
    if depth > 12:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:500]:
            yield from _walk(v, depth + 1)


def _pick(d: dict, pat, want_str=True):
    if isinstance(pat, list):
        for p in pat:
            v = _pick(d, p, want_str)
            if v is not None and (not want_str or is_meaningful_title(clean_title(v)) or p is pat[-1]):
                return v
        return None
    for k, v in d.items():
        if pat.search(_norm_key(k)) or pat.search(k):
            if want_str and isinstance(v, str) and v.strip():
                return v.strip()
            if not want_str and v not in (None, ""):
                return v
    return None


def extract_from_json(payload, page_url: str, source: Source) -> list[RawPromotion]:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    out = []
    for d in _walk(payload):
        link = _pick(d, URL_KEYS)
        if not link or link.startswith(("javascript:", "#")):
            continue
        url = urljoin(page_url, link)
        title = _pick(d, TITLE_KEYS)
        if not title:
            continue
        title = clean_title(re.sub(r"<[^>]+>", " ", title))
        sub = _pick(d, SUB_KEYS) or ""
        if not source.accepts(url, title if ("기획전" in title or "이벤트" in title) else ""):
            continue
        if not is_meaningful_title(title):
            continue
        img = _pick(d, IMG_KEYS) or ""
        out.append(RawPromotion(
            source_id=source.id, url=url, title=title,
            image_url=urljoin(page_url, img) if img and not img.startswith("data:") else "",
            period_text=_pick(d, PERIOD_KEYS) or "",
            description=clean_title(re.sub(r"<[^>]+>", " ", sub)),
            start_hint=str(_pick(d, START_KEYS, want_str=False) or "") or None,
            end_hint=str(_pick(d, END_KEYS, want_str=False) or "") or None,
            origin="json",
        ))
    return out


# ── 상세 페이지 메타 ─────────────────────────────────
_IMG_SKIP = re.compile(r"logo|icon|ico_|sprite|blank|spacer|loading|btn_|button|arrow|badge|common/|gnb|footer|sns|kakao|naver_|facebook|banner_top|top_banner|\.svg|\.gif|data:", re.I)
_IMG_GOOD = re.compile(r"event|promo|plan|exhibit|banner|visual|main|kv|campaign|special|theme|bnr", re.I)


def _banner_image(soup: BeautifulSoup, page_url: str) -> str:
    """og:image 가 없는 기획전: 본문의 첫 큰 배너 이미지(로고·아이콘·버튼 제외). 2026-11-26."""
    best, best_score = "", 0
    for i, img in enumerate(soup.find_all("img")[:80]):
        src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy") or ""
        if not src or src.startswith("data:") or _IMG_SKIP.search(src) or _IMG_SKIP.search(" ".join(img.get("class") or [])):
            continue
        try:
            w = int(re.sub(r"\D", "", str(img.get("width") or "")) or 0)
        except ValueError:
            w = 0
        if 0 < w < 250:
            continue
        score = (3 if _IMG_GOOD.search(src) or _IMG_GOOD.search(" ".join(img.get("class") or [])) else 0) + (2 if w >= 500 else 0) + max(0, 3 - i // 10)
        if score > best_score:
            best, best_score = urljoin(page_url, src), score
    return best if best_score >= 3 else ""

def extract_detail_meta(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return (t.get("content") or "").strip() if t else ""

    og_img = meta("og:image") or meta("twitter:image")
    page_img = "" if og_img else _banner_image(soup, page_url)
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text("\n", strip=True)
    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    # 사이트명 꼬리 제거: "겨울 기획전 | G마켓"
    title = re.split(r"\s+[|\-–]\s+(?=[^|\-–]{1,15}$)", title)[0]
    return {
        "title": clean_title(title),
        "image_url": urljoin(page_url, og_img) if og_img else page_img,
        "description": clean_title(meta("og:description") or meta("description")),
        "period_text": _period_from_text(text[:20000]),
    }


def merge(raws: list[RawPromotion]) -> list[RawPromotion]:
    """같은 기획전(정규화 URL 기준)을 하나로. 정보가 더 많은 쪽을 우선."""
    by: dict[str, RawPromotion] = {}

    def score(r: RawPromotion) -> int:
        return (len(r.title) > 3) * 2 + bool(r.image_url) + bool(r.period_text or r.end_hint) * 2 + (r.origin == "json")

    for r in raws:
        k = canonical_url(r.url)
        p = by.get(k)
        if p is None:
            by[k] = r
            continue
        best, other = (r, p) if score(r) > score(p) else (p, r)
        for f in ("title", "image_url", "period_text", "description", "start_hint", "end_hint"):
            if not getattr(best, f):
                setattr(best, f, getattr(other, f))
        by[k] = best
    return list(by.values())


def needs_detail(r: RawPromotion) -> bool:
    return not (r.period_text or r.end_hint) or not r.image_url or len(r.title) < 6


def apply_detail(r: RawPromotion, meta: dict) -> RawPromotion:
    if meta.get("title") and (len(r.title) < 6 or not is_meaningful_title(r.title)):
        r.title = meta["title"]
    r.image_url = r.image_url or meta.get("image_url", "")
    r.period_text = r.period_text or meta.get("period_text", "")
    r.description = r.description or meta.get("description", "")
    return r
