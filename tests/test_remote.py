"""RemoteSink: Supabase RPC 호출 형식 검증(로컬 가짜 서버)."""
import json
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from promohub.config import load_config
from promohub.models import RawPromotion
from promohub.normalize import normalize
from promohub.products import Product
from promohub.remote import RemoteSink, build_payload

GOT = {}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        GOT["path"] = self.path
        GOT["headers"] = dict(self.headers)
        GOT["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b"1")

    def log_message(self, *a):
        pass


def test_sink_payload():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    src = load_config().get("oliveyoung")
    raw = RawPromotion(source_id="oliveyoung", url="https://www.oliveyoung.co.kr/store/planshop/x?dispCatNo=1",
                       title="연말 뷰티 기획전", period_text="11.20 ~ 12.10")
    raw.products = [Product(name="수분 에센스", url="https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A1&t=1",
                            price=21900, original_price=29000, discount_rate=24)]
    p = normalize(raw, date(2026, 11, 24))
    sink = RemoteSink(f"http://127.0.0.1:{srv.server_port}", "sb_publishable_x", "tok")
    assert sink.send(build_payload(src, [p], datetime.now(timezone.utc))) == 1
    srv.shutdown()
    assert GOT["path"] == "/rest/v1/rpc/ingest" and GOT["headers"]["apikey"] == "sb_publishable_x"
    body = GOT["body"]
    assert body["p_token"] == "tok"
    pl = body["p_payload"]
    assert pl["source"] == {"id": "oliveyoung", "name": "올리브영", "channel_type": "vertical", "rank": 9}
    pr = pl["promotions"][0]
    assert pr["end_date"] == "2026-12-10" and pr["max_discount"] == 24
    assert pr["items"][0]["item_key"] == "oliveyoung.co.kr/store/goods/getgoodsdetail.do?goodsno=A1"
    assert pl["run"]["found"] == 1 and pl["run"]["ok"] is True


def test_sink_splits_large_payload():
    """패션플러스(기획전 123건)가 3초 제한에 걸려 적재 실패 → 묶음으로 나눠 보내고 run 은 마지막에만."""
    calls = []

    class Fake(RemoteSink):
        def _post(self, payload, retries=3):
            calls.append(payload)
            return len(payload["promotions"])

    sink = Fake("http://x", "sb_publishable_x", "tok")
    promos = [{"id": f"p{i}", "items": [{"item_key": f"k{i}-{j}"} for j in range(10)]} for i in range(123)]
    payload = {"source": {"id": "fashionplus"}, "promotions": promos, "seen_at": "t", "run": {"found": 123}}
    assert sink.send(payload) == 123
    assert len(calls) > 1
    assert [p["id"] for c in calls for p in c["promotions"]] == [p["id"] for p in promos]
    assert all(len(c["promotions"]) <= 20 and sum(len(p["items"]) for p in c["promotions"]) <= 600 for c in calls)
    assert all("run" not in c for c in calls[:-1]) and calls[-1]["run"] == {"found": 123}
    assert all(c["source"] == {"id": "fashionplus"} and c["seen_at"] == "t" for c in calls)
    # 빈 실패 기록은 그대로 한 번
    calls.clear()
    assert sink.send({"source": {"id": "x"}, "promotions": [], "run": {"ok": False}}) == 0
    assert len(calls) == 1 and calls[0]["run"] == {"ok": False}
