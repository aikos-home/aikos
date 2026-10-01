"""Who is speaking over all eval cases (base 101, adversarial 308, holdout 307), rules + classify, no LLM, no audio.

Every case must give exactly what tests/eval/snapshot.json froze. A rule change that moves any case fails here; if the
move is wanted, regenerate the snapshot on purpose (tests/eval/make_snapshot.py) and commit it with the change, so the
review sees each changed case. The snapshot is an approved list, not a rubber stamp: a PR that changes an answer in it
says in one line per changed case (or group of cases) why the new answer is better. Also prints the rules-only
recognition rate against the cases' expectations.
"""
import json
import unittest
from pathlib import Path

import _path  # noqa: F401
from eval.make_snapshot import FIELDS, snapshot

HERE = Path(__file__).resolve().parent / "eval"


def speaker_ok(expect, got):  # as tools/talk_eval.py
    if not expect:
        return got == ""
    g = got.lower()
    return any((got == "") if alt == ["∅"] else (bool(g) and all(t.lower() in g for t in alt)) for alt in expect)


class Snapshot(unittest.TestCase):
    def test_every_case_as_frozen(self):
        frozen = {s["id"]: s for s in json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))}
        now = snapshot()
        self.assertEqual(len(now), len(frozen), "eval cases added or removed: regenerate the snapshot on purpose")
        diffs = []
        for s in now:
            f = frozen.get(s["id"])
            if f is None or f["text"] != s["text"]:
                diffs.append(f"{s['id']}: case changed or new")
                continue
            for k in FIELDS:
                if s[k] != f[k]:
                    diffs.append(f"{s['id']} {k}: {f[k]!r} → {s[k]!r}   ({s['text'][:60]})")
        self.assertFalse(diffs, f"{len(diffs)} change(s) against the snapshot:\n" + "\n".join(diffs[:40]))

    def test_rules_only_rate(self):
        cases = {}
        for name in ("cases_base.json", "cases_adversarial.json", "cases_holdout.json"):
            for c in json.loads((HERE / name).read_text(encoding="utf-8")):
                cases[c["id"]] = c
        snap = snapshot()
        ok = sum(speaker_ok(cases[s["id"]].get("expect_speaker_any", []), s["speaker"]) for s in snap)
        print(f"\n  rules only (no LLM): {ok}/{len(snap)} = {100 * ok / len(snap):.1f} %")
        self.assertGreater(ok, 0)


if __name__ == "__main__":
    unittest.main()
