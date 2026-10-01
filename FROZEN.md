# Frozen building blocks

A block listed here is frozen at the given version. How to change it: see [`CLAUDE.md`](CLAUDE.md), section "Frozen building blocks".

| Block | Version (tag) | Path | Regression tests | Frozen since |
|---|---|---|---|---|
| `aikos_voice`: push-to-talk between door station and room keys (RTP L16, transcriber copy, door lock) | `voice-v1.0.0` (commit `1576421`) | [`esphome/components/aikos_voice`](esphome/components/aikos_voice/README.md) | 52 host checks (`esphome/tests/aikos_voice`, required CI check `voice-unit`) + 16 live checks on the door station | 2026-10-01 |
| `transcriber`: speech to text for Home Assistant, locally (RTP in; transcripts, live text, who is speaking, translation out) | `transcriber-v1.1.0` (commit `7c25666`); `transcriber-v1.0.0` (`aa9afdb`) stays usable | [`services/transcriber`](services/transcriber/README.md) | 44 unit tests incl. the identity snapshot over 716 eval cases and the echo rules (`services/transcriber/tests`, required CI check `transcriber-unit`, Python 3.9 + 3.12) | 2026-10-01 (1.1.0 since 19:09) |

Next version under way: voice v2 (call model with one set of "who hears what" rules for both cases, several room keys, speech-based end).
It goes through the same gate and gets its own tag; `voice-v1.0.0` stays usable.

Transcriber: the logic (`identity/`, the worker, receiver, live text, echo filter) belongs to the roomkey maintainers, packaging, deployment and CI to aikos core (see its README). Deployed on the Mac with `services/transcriber/deploy/deploy.sh <tag>`.
