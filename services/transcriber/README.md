# aikos transcriber

Turns what is said into text in Home Assistant: what a resident says into a RoomKey (room side) and what a visitor says
at the door (door side). It also tells who is speaking ("Paketdienst · DHL", "Anna", an emergency) and translates
foreign languages into German. Everything runs locally: audio goes to a Whisper server on your own network, never to a
cloud. Python 3.9+ standard library only.

Version **1.3.0** (component tag `transcriber-v1.2.3` until 1.3.0 is tagged).

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
| `text_visitor`, `visitor_language` | room | **R28, with `AIKOS_VISITOR_TRANSLATION=1`:** the resident's answer translated into the visitor's language; sent as an update after the German text, only in a call whose visitor speaks another language |
| event `aikos_talk_transcript` | both | the same data as the sensor attributes |
| event `aikos_mic_check` | both | **W3, with `AIKOS_MIC_CHECK=1`:** after every recording of ≥ 0.5 s, also when nothing was said: `verdict` (`ok`, `silent` = peaks below −90 dBFS, a dead mic; `clipping` = ≥ 1 % of samples at full scale, a floating data line), `zero_ratio`, `clip_ratio`, `peak_db`, `rms_db`, `duration_s`, `device`, `key_id`, `side`. Sent after the text, so it never delays it |

**Test senders** (`AIKOS_TEST_SOURCES`): their text goes to the same names with `_test` appended
(`sensor.talk_transcript_door_test`, event `aikos_talk_transcript_test`, ...), never into the live entities.

**Reads from Home Assistant:** the `sensor.*_ip_address` entities, to name the sending device; on the door side
`sensor.talk_transcript`, to drop door sentences that only repeat the resident (the door mic hears the door speaker); on the
room side with R28 on, `sensor.aikos_call_log` (`visitor_language`, set by the aikos integration 0.6.0), after the German text is out.

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

**R28, translation to the visitor (option, off by default):** with `AIKOS_VISITOR_TRANSLATION=1` the room side publishes the German
text first, exactly as before. Then it reads the call's `visitor_language` from the aikos call log. Only if that is another language
does it translate the answer (the `message`, else the text) with the local LLM and send an update with `text_visitor` and
`visitor_language`. German calls get no extra step (one state read after publishing). The language comes from the transcription
itself: the aikos integration sets it from a door sentence Whisper is sure of. Who is speaking is still found on the German text.
If the LLM gives the German back unchanged, no update is sent. In a foreign call the translation runs before the language
pass (pass 2), so the event `aikos_talk_transcript` comes about one translation (~1–3 s) later than in a German call; the
German text on the screens is not delayed.

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
| `AIKOS_SPLIT` | 0 | door side: cut the audio into utterances at pauses (door mic on for the whole call, voice v2); a resident who starts talking ends the visitor's utterance at once |
| `AIKOS_MIC_CHECK` | 0 | both sides, W3: report every recording's mic health (event `aikos_mic_check`) |
| `AIKOS_VISITOR_TRANSLATION` | 0 | room side, R28: translate the resident's answer into the visitor's language (needs the aikos integration ≥ 0.6.0 and Ollama) |
| `AIKOS_TEST_SOURCES` | `127.0.0.1` | comma-separated sender IPs that are tests; set but empty = none |
| `AIKOS_RECORDINGS` | `~/Library/Application Support/aikos/transcriber/recordings` | recordings are deleted when handled |
| `AIKOS_STATE_DIR` | `~/Library/Application Support/aikos/transcriber` | the activity file |
| `AIKOS_PYTHON` | the running Python | Python for the worker processes; on a Mac also the agents' and `deploy.sh`'s Python: set an absolute path to a pinned interpreter (e.g. uv-managed CPython 3.12) so macOS or Command Line Tools updates can't swap it |

Run one side: `cd services/transcriber && AIKOS_SIDE=door ... python3 -m aikos_transcriber`.

## Errors

| Case | What happens |
|---|---|
| a required setting is missing, the token file is unreadable | exit 2 with the reason, before anything listens |
| the port is taken | the receiver exits; launchd starts it again after 10 s |
| Whisper or Home Assistant does not answer | this utterance is not published; the worker logs the error, the recording is deleted, the receiver keeps running |
| Ollama does not answer | published anyway: "who is speaking" from the rules only, foreign speech untranslated; R28: the German answer only |
| R28: no call log, or it can't be read | the German answer only, as without R28 |
| W3: Home Assistant can't take the mic event | logged; the transcript is not affected |
| silence, a click, music, Whisper's typical hallucinations (subtitle credits like "ARD Text im Auftrag") | nothing is published; such a credit is never taken as the speaker either |
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

**macOS Local Network permission:** a LaunchAgent may reach Home Assistant on the LAN only with that permission. Apple's
`/usr/bin/python3` is exempt. Any other interpreter (uv, Homebrew) must first be allowed in System Settings → Privacy & Security
→ Local Network, else every publish fails with `[Errno 65] No route to host`. The smoke test catches it and `deploy.sh` rolls back
(04.10.).

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

- 1.3.0 (not tagged yet): W3 mic health behind `AIKOS_MIC_CHECK` (default off): every recording's verdict as the event
  `aikos_mic_check` (new module `mic.py`). On the door side, where a recording only starts with speech, the receiver itself reports
  ≥ 10 s of unbroken digital silence (zeros) on the stream (`SilenceWatch`, once per episode). Verdict `noise` for garbage behind the
  devices' ~−2 dBFS limiter (RMS > −10 dBFS). **Limit:** a mic whose driver does not start sends no packets at all, so neither
  check sees it (touch key 07.10., shared I²S bus); that is caught on the device. Written by aikos core, reviewed by the roomkey
  maintainers.
- 1.2.3: deployment only, the service is unchanged. `deploy.sh` uses `AIKOS_PYTHON` from the settings file (absolute
  path, checked) for the tests, both LaunchAgents and the smoke test; without it `/usr/bin/python3` as before. Reason: the agents ran on
  Apple's Command Line Tools Python 3.9, which a pending CLT update could replace underneath a frozen block (Aikos-hub, 04.10.).
- 1.2.2 (in tag 1.2.3): door side with `AIKOS_SPLIT=1`: where an utterance starts and ends is decided by the door's own speech
  detector (aikos_voice VoiceGate, ported: 11 dB over a 1.5 s floor, sustained for a third of 120 ms) instead of a per-packet
  threshold. In a room with music the old threshold took every beat for speech, so the 1.5 s pause after a visitor never came
  and the segment ran to 15 s: the text came 13.5 s after the speech ended (bench 04.10. 20:10). Beats and clicks alone no
  longer start a recording either. Logic by the roomkey maintainers.
- 1.2.1 (in tag 1.2.3): door side with `AIKOS_SPLIT=1`: a resident who starts talking ends the visitor's utterance at once
  (from the room side's activity file). Before, a turn gap shorter than 1.5 s plus the resident's voice from the door speaker
  kept the segment running to 15 s: the visitor's words reached HA 21 s after they began, with the resident's echo in them
  (bench 04.10. 19:54). The echo segment that follows is dropped by the timing rule as before. Logic by the roomkey maintainers.
- 1.2.0 (in tag 1.2.3, off by default): R28 translation to the visitor, behind `AIKOS_VISITOR_TRANSLATION` (default off). Written by aikos core
  for the roomkey maintainers' review (hardware phase, 02.10.); German calls unchanged.
- 1.1.1: noise is never shown as text (R24, live 01.10. 23:06–23:10): a noise at the door came out of Whisper as the
  subtitle credit "ARD Text im Auftrag", was published 3 times (live text too), and the LLM even took it for the speaker.
  Subtitle credits with a broadcaster ("… im Auftrag des ZDF", "ZDF für funk", "ARD Text", "Videotext") or a bare "im
  Auftrag" now count as hallucinations; "ich komme im Auftrag der Stadtwerke" stays a visitor's sentence. A caption or a
  broadcaster is never accepted as the speaker, from the rules or the LLM. Logic by the roomkey maintainers.
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
