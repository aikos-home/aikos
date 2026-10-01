"""Freeze what the rules say for every eval case (no LLM, no audio) → snapshot.json, checked by test_identity_snapshot.py.

    python3 services/transcriber/tests/eval/make_snapshot.py

Run it ON PURPOSE after a rule change and commit the new snapshot.json with the change: its diff shows, case by case,
what the change did (better, worse, different). Never regenerate just to make the test green.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from aikos_transcriber.identity import identify  # noqa: E402

NAMES = ("Jonas", "Anna")                        # the household names the eval assumes (as tools/talk_eval.py)
SETS = ["cases_base.json", "cases_adversarial.json", "cases_holdout.json"]
FIELDS = ("speaker", "kind", "role", "org", "message", "vtype", "urgent")


def snapshot() -> list:
    out = []
    for name in SETS:
        for c in json.loads((HERE / name).read_text(encoding="utf-8")):
            side = c.get("side", "door")
            who = identify(c["text"], NAMES, "", side=side)       # llm_url "" = rules + classify only
            out.append({"id": c["id"], "side": side, "text": c["text"], **{f: getattr(who, f) for f in FIELDS}})
    return out


if __name__ == "__main__":
    snap = snapshot()
    (HERE / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(snap)} cases → snapshot.json")
