import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sel", Path(__file__).resolve().parents[1] / "scripts" / "apply_selection.py")
sel = importlib.util.module_from_spec(spec); spec.loader.exec_module(sel)


def test_select_fills_per_type_in_traffic_order():
    sources = [{"id": "a", "channel_type": "fashion", "rank": 1},
               {"id": "b", "channel_type": "fashion", "rank": 2, "enabled": False}]
    cands = [{"id": f"c{i}", "channel_type": "fashion", "type_order": i} for i in range(1, 6)]
    found = {"c1": 0, "c2": 10, "c3": 2, "c4": 5, "c5": 9}
    picked, rep = sel.select(sources, cands, found, per_type=3)
    assert [c["id"] for c in picked] == ["c2", "c4"]          # 기존 a 1자리 + 통과한 후보 순서대로 2자리
    assert rep["fashion"]["kept"] == ["a"] and rep["fashion"]["total"] == 3
    assert ("c5", 9) in rep["fashion"]["dropped"]               # 자리 없음


def test_real_files_load():
    import yaml
    root = Path(__file__).resolve().parents[1] / "config"
    cands = yaml.safe_load((root / "candidates.yaml").read_text(encoding="utf-8"))["sources"]
    src = yaml.safe_load((root / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    assert not ({c["id"] for c in cands} & {s["id"] for s in src})
    picked, rep = sel.select(src, cands, {c["id"]: 5 for c in cands})
    assert all(r["total"] <= 20 for r in rep.values())
    text = sel.append_sources(picked[:2], {c["id"]: 5 for c in cands}, "2026-11-25")
    assert yaml.safe_load(text)[0]["id"] == picked[0]["id"]
