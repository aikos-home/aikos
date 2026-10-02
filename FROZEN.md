# Frozen building blocks

A block listed here is frozen at the given version. How to change it: see [`CLAUDE.md`](CLAUDE.md), section "Frozen building blocks".

| Block | Version (tag) | Path | Regression tests | Frozen since |
|---|---|---|---|---|
| `aikos_voice`: push-to-talk between door station and room keys (RTP L16, transcriber copy, door lock) | `voice-v1.0.0` (commit `1576421`) | [`esphome/components/aikos_voice`](esphome/components/aikos_voice/README.md) | 52 host checks (`esphome/tests/aikos_voice`, required CI check `voice-unit`) + 16 live checks on the door station | 2026-10-01 |
| `aikos_voice` v2: the call between door station and room keys (call model `call.h`, speech detector `level.h`, link moves audio only; R17, R19, R21) | `voice-v2.0.1` (commit `8fc4060`: 2.0.0 + speaker auto-load, PR #23, build only); `voice-v2.0.0` (`dbb07df`) stays usable | [`esphome/components/aikos_voice`](esphome/components/aikos_voice/README.md) | 183 host checks (link 51, call 113, level 19; required CI check `voice-unit`), door live test 23/23 (0.7.3), aikos acceptance run 01.10. (`features/sprechen.md` §6b) | 2026-10-01 |
| `transcriber`: speech to text for Home Assistant, locally (RTP in; transcripts, live text, who is speaking, translation out) | `transcriber-v1.1.0` (commit `7c25666`); `transcriber-v1.0.0` (`aa9afdb`) stays usable | [`services/transcriber`](services/transcriber/README.md) | 44 unit tests incl. the identity snapshot over 716 eval cases and the echo rules (`services/transcriber/tests`, required CI check `transcriber-unit`, Python 3.9 + 3.12) | 2026-10-01 (1.1.0 since 19:09) |

`voice-v1.0.0` (push-to-talk) stays usable as the fallback; devices move to `voice-v2.0.0` by pinning the tag.

Transcriber: the logic (`identity/`, the worker, receiver, live text, echo filter) belongs to the roomkey maintainers, packaging, deployment and CI to aikos core (see its README). Deployed on the Mac with `services/transcriber/deploy/deploy.sh <tag>`.
