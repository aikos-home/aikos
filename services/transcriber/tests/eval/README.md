# Eval cases for "who is speaking"

| File | Cases | What |
|---|---|---|
| `cases_base.json` | 101 | typical door and room sentences |
| `cases_adversarial.json` | 308 | corrections, vocatives, idioms, accents, mixed languages, roles only mentioned as a topic |
| `cases_holdout.json` | 307 | written blind (not looked at while tuning until the first run): 90.6 % before tuning, 97.7 % after |
| `real_manifest.json` | 150 | real recordings of native speakers from [Tatoeba](https://tatoeba.org) (metadata only) |
| `snapshot.json` | 716 | what the rules give for every case, frozen (see `make_snapshot.py`, checked by `test_identity_snapshot.py`) |

Case format: `{"id", "category", "side": "door"|"room", "say", "text", "expect_speaker_any": [["Anna"], …],
"expect_message_contains", …}`. An empty `expect_speaker_any` = nobody introduced themselves; the alternative `["∅"]`
= empty is fine too (cases a careful human would call ambiguous).

Full eval with the local LLM (and optionally audio): `python3 services/transcriber/tools/talk_eval.py --cases
services/transcriber/tests/eval/cases_*.json --text-only` → 98.9 % (708/716) on 2026-10-01. The 8 misses are known
differences between the cases and the visitor-type spec (`features/sprechen.md` §2c).

**Real recordings:** the audio is not in this repository (CC BY 4.0 / CC BY-NC 4.0 by their speakers, sentences
CC BY 2.0 FR). `real_manifest.json` lists each clip with its Tatoeba sentence and audio id, speaker (attribution),
licence and the expected speaker. Fetch the audio from Tatoeba by its audio id for your own run (`--real`). End to end
(Whisper + identity) all 150 passed on 2026-09-30.

Origin: RoomKey `tools/eval/` (roomkey@d0d52b9).
