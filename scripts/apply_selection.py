"""시험 수집 결과로 채널 유형별 트래픽 상위 N곳(기본 20)을 골라 config/sources.yaml 에 반영.

사용: python scripts/apply_selection.py found.json [--per-type 20] [--min-found 3] [--dry-run]
  found.json = {"채널id": 시험 수집에서 잡힌 기획전 수, ...}  (crawl_runs 에서 뽑음)

규칙
- 유형별 순서: sources.yaml 기존 채널(rank 순) → candidates.yaml 후보(type_order 순). 기존 50곳이 트래픽 상위라 먼저 본다.
- 기존 채널: 현재 enabled 면 그대로 유지(한 자리 차지). disabled 는 운영자 결정이므로 건드리지 않는다.
- 후보: 시험 수집 기획전 min_found 건 이상이면 선정. robots 금지·차단·0건은 탈락.
- 유형별 per_type 곳까지 채우고, 선정된 후보를 sources.yaml 끝에 enabled 로 추가한다(기존 줄·주석은 그대로).
"""
import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC, CAND = ROOT / "config" / "sources.yaml", ROOT / "config" / "candidates.yaml"


def select(sources: list[dict], cands: list[dict], found: dict, per_type: int = 20, min_found: int = 3):
    have = {s["id"] for s in sources}
    picked, report = [], {}
    types = list(dict.fromkeys([s["channel_type"] for s in sources] + [c["channel_type"] for c in cands]))
    for t in types:
        kept = [s["id"] for s in sorted(sources, key=lambda x: x.get("rank", 999))
                if s["channel_type"] == t and s.get("enabled", True)]
        new, dropped = [], []
        for c in sorted((c for c in cands if c["channel_type"] == t), key=lambda x: x.get("type_order", 999)):
            if c["id"] in have:
                continue
            n = int(found.get(c["id"], 0) or 0)
            if len(kept) + len(new) < per_type and n >= min_found:
                new.append(c)
            else:
                dropped.append((c["id"], n))
        picked += new
        report[t] = {"kept": kept, "added": [(c["id"], int(found.get(c["id"], 0))) for c in new], "dropped": dropped,
                     "total": len(kept) + len(new)}
    return picked, report


def append_sources(picked: list[dict], found: dict, today: str) -> str:
    blocks = []
    for c in picked:
        d = {k: v for k, v in c.items() if k != "type_order"}
        y = yaml.safe_dump([d], allow_unicode=True, sort_keys=False).rstrip("\n")
        y = y.replace("- id: " + c["id"], f"- id: {c['id']}   # {today} 유형별 상위 선정(시험 수집 기획전 {found.get(c['id'])}건)", 1)
        blocks.append(y)
    return ("\n" + "\n".join(blocks) + "\n") if blocks else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("found")
    ap.add_argument("--per-type", type=int, default=20)
    ap.add_argument("--min-found", type=int, default=3)
    ap.add_argument("--date", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    found = json.loads(Path(a.found).read_text(encoding="utf-8"))
    src = yaml.safe_load(SRC.read_text(encoding="utf-8"))["sources"]
    cands = yaml.safe_load(CAND.read_text(encoding="utf-8"))["sources"]
    picked, report = select(src, cands, found, a.per_type, a.min_found)
    if not a.dry_run and picked:
        text = SRC.read_text(encoding="utf-8").rstrip("\n") + "\n"
        SRC.write_text(text + append_sources(picked, found, a.date or "선정"), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
