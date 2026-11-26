"""Supabase 적재: 채널 1개 수집 결과를 public.ingest(token, payload) RPC로 보낸다.

환경변수
  SUPABASE_URL           https://<ref>.supabase.co
  SUPABASE_ANON_KEY      publishable(anon) 키 — 공개돼도 되는 키
  PROMOHUB_INGEST_TOKEN  수집기 전용 토큰(비공개, GitHub Secrets에 보관)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx

from .models import Promotion


def remote_configured() -> bool:
    return all(os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "PROMOHUB_INGEST_TOKEN"))


def promotion_payload(p: Promotion) -> dict:
    return {
        "id": p.id, "url": p.url, "title": p.title, "kind": p.kind, "category": p.category,
        "benefits": p.benefits, "max_discount": p.max_discount,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "image_url": p.image_url, "description": p.description, "period_text": p.period_text,
        "items": [dict(it.to_dict(), item_key=it.key()) for it in (p.products or [])],
    }


def build_payload(source, promos: list[Promotion], started_at: datetime, ok: bool = True, error: str = "",
                  diag: dict | None = None) -> dict:
    return {
        "source": {"id": source.id, "name": source.name, "channel_type": source.channel_type, "rank": source.rank},
        "promotions": [promotion_payload(p) for p in promos],
        "seen_at": datetime.now(timezone.utc).isoformat(),
        "run": {"found": len(promos), "ok": ok, "error": error[:500], "started_at": started_at.isoformat(),
                "diag": diag or {}},
    }


class RemoteSink:
    def __init__(self, url: str | None = None, key: str | None = None, token: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/") + "/rest/v1/rpc/ingest"
        self.key = key or os.environ["SUPABASE_ANON_KEY"]
        self.token = token or os.environ["PROMOHUB_INGEST_TOKEN"]

    # 사이트와 같은 anon 권한으로 적재하므로 한 번의 호출이 3초(statement_timeout)를 넘으면 취소된다.
    # 기획전·상품이 많은 채널(예: 패션플러스 123건)은 나눠 보낸다. ingest 는 기획전 단위 upsert 라
    # 나눠 보내도 결과가 같고, 수집 기록(run)은 마지막 묶음에만 붙여 crawl_runs 에 한 줄만 남긴다.
    MAX_PROMOS = 20
    MAX_ITEMS = 600

    def send(self, payload: dict, retries: int = 3) -> int:
        promos = payload.get("promotions") or []
        chunks, cur, n_items = [], [], 0
        for pr in promos:
            k = len(pr.get("items") or [])
            if cur and (len(cur) >= self.MAX_PROMOS or n_items + k > self.MAX_ITEMS):
                chunks.append(cur)
                cur, n_items = [], 0
            cur.append(pr)
            n_items += k
        if cur or not chunks:
            chunks.append(cur)
        if len(chunks) == 1:
            return self._post(payload, retries)
        base = {k: v for k, v in payload.items() if k not in ("promotions", "run")}
        new = 0
        for i, ch in enumerate(chunks):
            part = dict(base, promotions=ch)
            if i == len(chunks) - 1 and "run" in payload:
                part["run"] = payload["run"]
            new += self._post(part, retries)
        return new

    def _post(self, payload: dict, retries: int = 3) -> int:
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if not self.key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.key}"   # 레거시 anon JWT
        body = json.dumps({"p_token": self.token, "p_payload": payload}, ensure_ascii=False, default=str)
        last = None
        for i in range(retries):
            try:
                r = httpx.post(self.url, content=body.encode(), headers=headers, timeout=60)
                if r.status_code == 200:
                    return int(r.json() or 0)
                last = f"{r.status_code} {r.text[:300]}"
                if r.status_code in (400, 401, 403):
                    break
            except httpx.HTTPError as e:
                last = repr(e)
            time.sleep(2 * (i + 1))
        raise RuntimeError(f"Supabase 적재 실패: {last}")
