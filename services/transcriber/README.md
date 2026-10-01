# aikos transcriber

Turns what is said into text in Home Assistant: what a resident says into a RoomKey (room side) and what a visitor says
at the door (door side). It also tells who is speaking ("Paketdienst · DHL", "Anna", an emergency) and translates
foreign languages into German. Everything runs locally: audio goes to a Whisper server on your own network, never to a
cloud. Python 3.9+ standard library only.

Version **1.1.0** (component tag `transcriber-v1.1.0`).

## Interface

**In: RTP over UDP.** Payload type 96 = L16, 16 kHz, mono, big-endian, 20 ms per packet. Payload type 13 (comfort
noise) = the utterance is over (talk button released). Packets of 12 bytes or less are keepalives. Room side: UDP 5006,
door side: UDP 5008. One recording per utterance and sender; each utterance is handled by its own worker process, so a
crash there never stops the receiver.

**Out: Home Assistant** (REST API, long-lived token):

| What | Side | Content |
|---|---|---|
| `sensor.talk_transcript` | room | state = ISO time of the utterance; attributes `text`, `message`, `speaker`, `speaker_kind`, `speaker_role`, `speaker_org`, `speaker_method`, `urgent`, `side`, `device`, `key_id`, `duration_s`, `language`, `language_name`, `language_name_en`, `language_probability`, `text_original`, `model`, `created`, `source`, `transcribe_s` |
| `sensor.talk_transcript_door` | door | the same |
| `sensor.talk_live_door` | door | partial text while the visitor is still talking (`sensor.talk_live` on the room side with `AIKOS_LIVE=1`) |
| event `aikos_talk_transcript` | both | the same data as the sensor attributes |

**Test senders** (`AIKOS_TEST_SOURCES`): their text goes to the same names with `_test` appended
(`sensor.talk_transcript_door_test`, event `aikos_talk_transcript_test`, ...), never into the live entities.

**Reads from Home Assistant:** the `sensor.*_ip_address` entities, to name the sending device; on the door side
`sensor.talk_transcript`, to drop door sentences that only repeat the resident (the door mic hears the door speaker).

**Between the two sides:** the activity file `<AIKOS_STATE_DIR>/room_active` (`room_active_test` for test senders).
Content = when the resident started talking (Unix time), modification time = the last audio. The door side reads it:
no live text while a resident talks, and its echo filter only looks at door audio that overlaps.

**Echo by timing:** a door recording whose speech lies entirely within a resident's talk (from 0.2 s before to 0.5 s
after it, for the door speaker's delay) is an echo and is not transcribed, whatever Whisper would make of it. A garbled
echo ("Ich kann gerade nicht" heard as "Das war nicht.") doesn't match the resident's words, so the word filter alone
missed it (live test 01.10.). The same rule holds back live partials. Trade-off: a visitor who speaks only while the
resident talks (double talk) is dropped too; whatever the visitor says after that is kept.

**Resident's words at the door are never a visitor:** if a door utterance names one of the household (`AIKOS_KNOWN_NAMES`) as
the speaker while a resident talked for at least 0.5 s during it, it is not published (final and live text). This covers
the door mic hearing the resident when no room transcript can filter it, e.g. a key whose mic sends silence (system test
01.10., W1). **Known trade-off:** a household member at the door who introduces themselves while someone inside is
talking is dropped too; without that overlap ("Hier ist Jonas, ich habe meinen Schlüssel vergessen") it is shown.

Needs: a whisper.cpp server with the OpenAI-compatible `/v1/audio/transcriptions` (large-v3 recommended) and, optional,
Ollama with `qwen3:8b` (fallback for "who is speaking", and translation).

## Configuration

Environment variables (on a Mac: the settings file of the LaunchAgents, see below).

| Variable | Default | |
|---|---|---|
| `AIKOS_SIDE` | required | `room` or `door` |
| `AIKOS_HA_URL` | required | e.g. `http://homeassistant.local:8123` |
| `AIKOS_HA_TOKEN_FILE` | required | file with a long-lived token of a user made for the transcriber, mode 600 |
| `AIKOS_PORT` | 5006 room, 5008 door | |
| `AIKOS_KNOWN_NAMES` | empty | household first names, comma-separated: Whisper spells them right |
| `AIKOS_WHISPER_URL` | `http://127.0.0.1:6667/v1/audio/transcriptions` | |
| `AIKOS_LLM_URL` | `http://127.0.0.1:11434` | Ollama |
| `AIKOS_LIVE` | 1 door, 0 room | publish partial text while talking |
| `AIKOS_SPLIT` | 0 | door side: cut the audio into utterances at pauses (door mic on for the whole call, voice v2) |
| `AIKOS_TEST_SOURCES` | `127.0.0.1` | comma-separated sender IPs that are tests; set but empty = none |
| `AIKOS_RECORDINGS` | `~/Library/Application Support/aikos/transcriber/recordings` | recordings are deleted when handled |
| `AIKOS_STATE_DIR` | `~/Library/Application Support/aikos/transcriber` | the activity file |
| `AIKOS_PYTHON` | the running Python | Python for the worker processes |

Run one side: `cd services/transcriber && AIKOS_SIDE=door ... python3 -m aikos_transcriber`.

## Errors

| Case | What happens |
|---|---|
| a required setting is missing, the token file is unreadable | exit 2 with the reason, before anything listens |
| the port is taken | the receiver exits; launchd starts it again after 10 s |
| Whisper or Home Assistant does not answer | this utterance is not published; the worker logs the error, the recording is deleted, the receiver keeps running |
| Ollama does not answer | published anyway: "who is speaking" from the rules only, foreign speech untranslated |
| silence, a click, music, Whisper's typical hallucinations | nothing is published |
| a second utterance in the same second | its recording gets `_2`, `_3`, ...; nothing is overwritten |

## Deploying on a Mac

```
bash ~/aikos/repo/services/transcriber/deploy/deploy.sh transcriber-v1.0.0
```

Checks out the tag in `~/aikos/repo`, runs the unit tests with the Mac's Python, writes the two LaunchAgents
`home.aikos.transcriber.room` and `.door` (`deploy/launchd.py`), restarts them, waits until both receivers listen and
sends one spoken test sentence per side (`deploy/smoke.py`, macOS `say`, test sender 127.0.0.1, `_test` entities only).
If anything after the tests fails, the previous LaunchAgents and checkout come back by themselves. Log:
`~/Library/Logs/aikos/deploy.log`.

The house settings live in `~/.aikos/transcriber.env`, never in the repository; start from
[`deploy/transcriber.env.example`](deploy/transcriber.env.example). Without it, `deploy.sh` takes them over once from
the existing transcriber LaunchAgents.

## Tests

```
python3 -m unittest discover -s services/transcriber/tests
```

CI job `transcriber-unit`, on Python 3.9 (the Mac's) and 3.12. They cover who-is-speaking (the RoomKey self-test
cases), configuration, speech detection, the receiver over real UDP (one recording per utterance, the activity-file
contract), the worker end to end against fake Whisper, Ollama and Home Assistant (test senders never reach live
entities), and the LaunchAgent writer. Nothing in the tests talks to a real Home Assistant.

**Who is speaking, all eval cases:** `tests/test_identity_snapshot.py` runs the rules (+ visitor type, no LLM, no audio) over
the 716 cases in `tests/eval/` and compares every case with `tests/eval/snapshot.json`. A rule change that moves any case
fails; if the move is wanted, regenerate the snapshot on purpose (`python3 services/transcriber/tests/eval/make_snapshot.py`)
and commit it with the change, so the review sees each changed case; the PR says in one line why each changed answer is
better (an approved list, not a rubber stamp). The full eval with the local LLM and with audio
(spoken by macOS voices, degraded, through Whisper) is `tools/talk_eval.py`, a dev tool outside CI: 98.9 % text only
(708/716, qwen3:8b) on 2026-10-01; rules alone 92.9 %. See `tests/eval/README.md`.

`tests/equivalence/` proved that the move from the RoomKey repository changed nothing (identity: 36,084 checks over
937 texts; worker: 7 of 7 scenarios). It needs the old code and is not part of CI.

## Who owns what

- Packaging, configuration, deployment, tests and CI: aikos core.
- The logic (what counts as speech, who is speaking in `identity/`, the echo filter, the live text): the RoomKey
  maintainers. A change there needs their review.

Changes go through a pull request. Once tagged, this block is listed in [`FROZEN.md`](../../FROZEN.md).

## History

- 1.1.0: a resident's own words heard by the door mic are never published as a visitor (W1 from the system test of
  01.10.: with the key's mic sending silence, the door showed the resident's own name as the visitor); see "Resident's words at
  the door" for the rule and its known trade-off. Plus: an echo of the resident at the door is dropped by its timing (all
  its speech lies in the resident's talk), since Whisper garbles such echoes past any word match (live test 01.10. 18:57).
  Logic by the roomkey maintainers (PRs #17, #19).
- 1.0.1: deployment only, the service is unchanged. `deploy.sh` no longer stops silently when `lsof` warns (it
  stopped after the restart, before the receiver check and the spoken test); the settings takeover accepts
  `AIKOS_SPLIT` on the door agent only.
- 1.0.0: moved from the RoomKey repository (`tools/`, at d0d52b9) without changing behaviour; new: start via
  `python3 -m aikos_transcriber`, the Mac deployment with automatic rollback, the unit tests; fixed: a second
  utterance in the same second overwrote the first recording.
