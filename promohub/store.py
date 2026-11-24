"""SQLite 저장소. 스키마는 PostgreSQL로 그대로 옮길 수 있게 표준 SQL만 쓴다."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import CHANNEL_TYPES, Promotion
from .normalize import KST, status_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    rank INTEGER DEFAULT 999
);
CREATE TABLE IF NOT EXISTS promotions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    benefits TEXT DEFAULT '',
    max_discount INTEGER,
    start_date TEXT,
    end_date TEXT,
    image_url TEXT DEFAULT '',
    description TEXT DEFAULT '',
    period_text TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    seen_count INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_promo_source ON promotions(source_id);
CREATE INDEX IF NOT EXISTS ix_promo_end ON promotions(end_date);
CREATE INDEX IF NOT EXISTS ix_promo_last_seen ON promotions(last_seen);
CREATE TABLE IF NOT EXISTS promotion_items (
    promotion_id TEXT NOT NULL REFERENCES promotions(id),
    item_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    brand TEXT DEFAULT '',
    url TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    price INTEGER,
    original_price INTEGER,
    discount_rate INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (promotion_id, item_key)
);
CREATE INDEX IF NOT EXISTS ix_items_price ON promotion_items(price);
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    found INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    ok INTEGER DEFAULT 0,
    error TEXT
);
"""


def now_iso() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str | Path = "data/promohub.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ── 쓰기 ──
    def upsert_source(self, sid: str, name: str, channel_type: str, rank: int = 999):
        self.conn.execute(
            "INSERT INTO sources(id,name,channel_type,rank) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, channel_type=excluded.channel_type, rank=excluded.rank",
            (sid, name, channel_type, rank),
        )
        self.conn.commit()

    def upsert_promotions(self, promos: list[Promotion], seen_at: Optional[str] = None) -> int:
        """반환값: 새로 발견된 건수. 기존 건은 last_seen·내용을 갱신(빈 값으로 덮어쓰지 않음)."""
        seen_at = seen_at or now_iso()
        new = 0
        for p in promos:
            r = p.to_row()
            exists = self.conn.execute("SELECT 1 FROM promotions WHERE id=?", (p.id,)).fetchone()
            if exists:
                self.conn.execute(
                    """UPDATE promotions SET title=?, kind=?, category=?,
                       benefits=CASE WHEN ?<>'' THEN ? ELSE benefits END,
                       max_discount=COALESCE(?, max_discount),
                       start_date=COALESCE(?, start_date), end_date=COALESCE(?, end_date),
                       image_url=CASE WHEN ?<>'' THEN ? ELSE image_url END,
                       description=CASE WHEN ?<>'' THEN ? ELSE description END,
                       period_text=CASE WHEN ?<>'' THEN ? ELSE period_text END,
                       url=?, last_seen=?, seen_count=seen_count+1 WHERE id=?""",
                    (r["title"], r["kind"], r["category"], r["benefits"], r["benefits"], r["max_discount"],
                     r["start_date"], r["end_date"], r["image_url"], r["image_url"],
                     r["description"], r["description"], r["period_text"], r["period_text"],
                     r["url"], seen_at, p.id),
                )
            else:
                new += 1
                self.conn.execute(
                    """INSERT INTO promotions(id,source_id,url,title,kind,category,benefits,max_discount,
                       start_date,end_date,image_url,description,period_text,first_seen,last_seen)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p.id, p.source_id, p.url, p.title, p.kind, p.category, r["benefits"], p.max_discount,
                     r["start_date"], r["end_date"], p.image_url, p.description, p.period_text, seen_at, seen_at),
                )
            if p.products:
                self.replace_items(p.id, p.products, seen_at)
        self.conn.commit()
        return new

    def replace_items(self, promotion_id: str, products: list, seen_at: str):
        """이번 수집에서 본 상품 목록으로 교체(가격은 최신값). first_seen은 유지."""
        old = {r["item_key"]: r["first_seen"] for r in self.conn.execute(
            "SELECT item_key, first_seen FROM promotion_items WHERE promotion_id=?", (promotion_id,))}
        self.conn.execute("DELETE FROM promotion_items WHERE promotion_id=?", (promotion_id,))
        seen_keys = set()
        for pos, it in enumerate(products):
            k = it.key()
            if k in seen_keys:
                continue
            seen_keys.add(k)
            self.conn.execute(
                """INSERT INTO promotion_items(promotion_id,item_key,position,name,brand,url,image_url,price,
                   original_price,discount_rate,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (promotion_id, k, pos, it.name, it.brand, it.url, it.image_url, it.price, it.original_price,
                 it.discount_rate, old.get(k, seen_at), seen_at))

    def items(self, promotion_id: str, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM promotion_items WHERE promotion_id=? ORDER BY position LIMIT ?", (promotion_id, limit))]

    def _attach_items(self, items: list[dict], per: int):
        if not items:
            return
        ids = [i["id"] for i in items]
        by: dict[str, list] = {i: [] for i in ids}
        stats: dict[str, tuple] = {}
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            q = ",".join("?" * len(part))
            for r in self.conn.execute(f"SELECT * FROM promotion_items WHERE promotion_id IN ({q}) ORDER BY position", part):
                lst = by[r["promotion_id"]]
                if len(lst) < per:
                    lst.append({k: r[k] for k in ("name", "brand", "url", "image_url", "price", "original_price", "discount_rate")})
            for r in self.conn.execute(
                    f"SELECT promotion_id, COUNT(*) n, MIN(price) mn, MAX(discount_rate) md FROM promotion_items "
                    f"WHERE promotion_id IN ({q}) GROUP BY promotion_id", part):
                stats[r["promotion_id"]] = (r["n"], r["mn"], r["md"])
        for i in items:
            i["items"] = by[i["id"]]
            n, mn, md = stats.get(i["id"], (0, None, None))
            i["item_count"], i["min_price"] = n, mn

    def search_items(self, q: str = "", min_price: int | None = None, max_price: int | None = None,
                     sort: str = "discount", limit: int = 300) -> list[dict]:
        sql = ("SELECT it.*, p.title AS promotion_title, p.url AS promotion_url, p.end_date, s.name AS source_name, "
               "s.id AS source_id FROM promotion_items it JOIN promotions p ON p.id=it.promotion_id "
               "JOIN sources s ON s.id=p.source_id WHERE (p.end_date IS NULL OR p.end_date >= date('now','localtime'))")
        args: list = []
        if q:
            sql += " AND (it.name LIKE ? OR it.brand LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        if min_price is not None:
            sql += " AND it.price >= ?"; args.append(min_price)
        if max_price is not None:
            sql += " AND it.price <= ?"; args.append(max_price)
        sql += {"discount": " ORDER BY it.discount_rate IS NULL, it.discount_rate DESC",
                "price": " ORDER BY it.price IS NULL, it.price ASC",
                "price_desc": " ORDER BY it.price DESC"}.get(sort, "") + " LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def start_run(self, source_id: str) -> int:
        cur = self.conn.execute("INSERT INTO crawl_runs(source_id, started_at) VALUES(?,?)", (source_id, now_iso()))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, found: int, new: int, ok: bool, error: str = ""):
        self.conn.execute(
            "UPDATE crawl_runs SET finished_at=?, found=?, new_count=?, ok=?, error=? WHERE id=?",
            (now_iso(), found, new, int(ok), error[:500], run_id),
        )
        self.conn.commit()

    # ── 읽기 ──
    def _decorate(self, row: sqlite3.Row, today: date, stale_before: str) -> dict:
        d = dict(row)
        sd = date.fromisoformat(d["start_date"]) if d["start_date"] else None
        ed = date.fromisoformat(d["end_date"]) if d["end_date"] else None
        st = status_of(sd, ed, today)
        # 기간을 모르는데 최근 수집에서 사라졌다면 종료로 간주
        if st == "unknown" and d["last_seen"] < stale_before:
            st = "ended"
        d["status"] = st
        d["d_day"] = (ed - today).days if ed else None
        d["benefits"] = [b for b in (d["benefits"] or "").split(",") if b]
        d["is_new"] = d["first_seen"] >= (datetime.now(KST) - timedelta(hours=24)).isoformat()
        d["channel_type_label"] = CHANNEL_TYPES.get(d.get("channel_type", ""), "")
        return d

    def query(self, *, source: list[str] | None = None, channel_type: list[str] | None = None,
              category: list[str] | None = None, kind: str | None = None, status: list[str] | None = None,
              q: str | None = None, sort: str = "ending", limit: int = 500, include_ended: bool = False,
              items_per: int = 8) -> list[dict]:
        sql = ("SELECT p.*, s.name AS source_name, s.channel_type FROM promotions p "
               "JOIN sources s ON s.id=p.source_id WHERE 1=1")
        args: list = []

        def _in(col, vals):
            nonlocal sql
            if vals:
                sql += f" AND {col} IN ({','.join('?' * len(vals))})"
                args.extend(vals)

        _in("p.source_id", source)
        _in("s.channel_type", channel_type)
        _in("p.category", category)
        if kind:
            sql += " AND p.kind=?"
            args.append(kind)
        if q:
            sql += (" AND (p.title LIKE ? OR p.description LIKE ? OR EXISTS (SELECT 1 FROM promotion_items it "
                    "WHERE it.promotion_id=p.id AND (it.name LIKE ? OR it.brand LIKE ?)))")
            args += [f"%{q}%"] * 4
        rows = self.conn.execute(sql, args).fetchall()
        today = datetime.now(KST).date()
        stale_before = (datetime.now(KST) - timedelta(days=2)).isoformat()
        items = [self._decorate(r, today, stale_before) for r in rows]
        if status:
            items = [i for i in items if i["status"] in status]
        elif not include_ended:
            items = [i for i in items if i["status"] != "ended"]
        keyf = {
            "ending": lambda i: (i["end_date"] is None, i["end_date"] or "9999"),
            "new": lambda i: i["first_seen"],
            "discount": lambda i: -(i["max_discount"] or 0),
        }.get(sort, lambda i: i["end_date"] or "9999")
        items.sort(key=keyf, reverse=(sort == "new"))
        items = items[:limit]
        self._attach_items(items, items_per)
        return items

    def sources(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT s.*, (SELECT MAX(finished_at) FROM crawl_runs r WHERE r.source_id=s.id AND r.ok=1) AS last_crawled,
                      (SELECT error FROM crawl_runs r WHERE r.source_id=s.id ORDER BY id DESC LIMIT 1) AS last_error
               FROM sources s ORDER BY s.rank, s.name"""
        ).fetchall()
        return [dict(r) | {"channel_type_label": CHANNEL_TYPES.get(r["channel_type"], "")} for r in rows]
