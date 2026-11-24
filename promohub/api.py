"""FastAPI: /api/promotions, /api/sources, /api/stats + 웹 화면(web/index.html) 서빙."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

from .config import ROOT
from .store import Store

DB_PATH = os.environ.get("PROMOHUB_DB", str(ROOT / "data" / "promohub.db"))
app = FastAPI(title="Promo Hub", version="0.1")
store = Store(DB_PATH)


def _split(v: Optional[str]) -> Optional[list[str]]:
    return [x for x in v.split(",") if x] if v else None


@app.get("/api/promotions")
def promotions(
    source: Optional[str] = Query(None, description="쉼표 구분 채널 id"),
    channel_type: Optional[str] = Query(None, description="openmarket,homeshopping,mall"),
    category: Optional[str] = None,
    kind: Optional[str] = Query(None, description="기획전 | 이벤트"),
    status: Optional[str] = Query(None, description="active,ending_soon,upcoming,unknown,ended"),
    q: Optional[str] = None,
    sort: str = Query("ending", pattern="^(ending|new|discount)$"),
    limit: int = Query(500, le=3000),
    items_per: int = Query(8, le=60, description="기획전당 함께 내려줄 상품 수"),
):
    items = store.query(source=_split(source), channel_type=_split(channel_type), category=_split(category),
                        kind=kind, status=_split(status), q=q, sort=sort, limit=limit, items_per=items_per)
    return {"count": len(items), "items": items}


@app.get("/api/promotions/{pid}/items")
def promotion_items(pid: str):
    return {"items": store.items(pid)}


@app.get("/api/items")
def items(q: Optional[str] = None, min_price: Optional[int] = None, max_price: Optional[int] = None,
          sort: str = Query("discount", pattern="^(discount|price|price_desc)$"), limit: int = Query(300, le=2000)):
    """진행 중 기획전에 담긴 상품 검색(가격대·할인율)."""
    return {"items": store.search_items(q or "", min_price, max_price, sort, limit)}


@app.get("/api/sources")
def sources():
    return store.sources()


@app.get("/api/stats")
def stats():
    items = store.query(limit=5000)
    return {
        "total": len(items),
        "by_status": Counter(i["status"] for i in items),
        "by_source": Counter(i["source_name"] for i in items),
        "by_category": Counter(i["category"] for i in items),
        "new_24h": sum(i["is_new"] for i in items),
    }


@app.get("/")
def index():
    return FileResponse(Path(ROOT) / "web" / "index.html")
