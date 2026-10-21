# aikos TTS

Speech in the residents' own voices, locally. The door reads a resident's note or the greeting aloud in that person's voice
(aikos-app A42–A45). Each person records their own voice in the aikos app (Haus → Meine Stimme), so every voice is enrolled
by its owner. Voices, text and audio never leave the machine this runs on (R11). Owner: aikos core.

Version **0.3.0**. Python 3.11. Model: [Chatterbox multilingual](https://github.com/resemble-ai/chatterbox) (MIT licence),
zero-shot voice cloning from a 8–60 s recording, German. Every generated clip carries Chatterbox's inaudible watermark,
so it can be recognised as synthetic. A voice is never proof of identity.

**The model never decides what is said.** With `AIKOS_TTS_WHISPER_URL` (a local whisper-server), every sentence is written
back and compared with the text: whatever the model adds after the text's last word is cut off and the rest is checked
again; an invented start or missing words mean another take (up to three, each a little less free); if none fits, nothing
is spoken and Home Assistant shows the text only. Measured on 21.10. with a resident's voice: 5 of 5 door sentences word for
word (before the check: 3 of 5, with babbling after the sentence); 7–25 s per sentence including the retries.

## Interface

**Home Assistant: Wyoming** (`tcp://0.0.0.0:10200`, HA's standard TTS link; add it in HA with the Wyoming integration).
- `describe` lists one voice per enrolled person (`name` = voice id, `description` = display name, language `de`).
- `synthesize {text, voice: {name}}` answers 16-bit mono PCM at the model's rate (24 kHz). Without a known voice it answers
  an error, so nothing is ever spoken in anyone's voice by accident.
- Only the machines in `AIKOS_TTS_WYOMING_CLIENTS` may ask (the Home Assistant hosts). A cloned voice must not be something
  anyone in the network can fetch.

**aikos app: HTTP** (`0.0.0.0:10201`, `Authorization: Bearer <token>`, only from `AIKOS_TTS_HTTP_CLIENTS`).

| Route | What |
|---|---|
| `GET /v1/health` | `{ok, version, engine, voices}`; no token needed, no secrets in it |
| `GET /v1/voices` | `[{id, name, created, seconds}]` |
| `PUT /v1/voices/{id}` | body = the recording (any format ffmpeg reads), header `X-Voice-Name` (URL-encoded). 8–60 s after cutting leading silence; replaces the voice only once the new recording is checked |
| `DELETE /v1/voices/{id}` | the voice and its recording, for good |
| `POST /v1/prepare {voice, texts}` | say these once now in the background (202), so they play at once later; the takes are kept per voice (`cache/`, at most 400, a new recording or deleting the voice drops them) |
| `POST /v1/speak {voice, text}` | a short test sentence (≤ 300 characters) as WAV, to listen to in the app |

Voice ids: `^[a-z0-9][a-z0-9_-]{0,39}$`. The app decides who may change which voice (only the person themself).

## Running it (Mac)

`deploy/install.sh SOURCE_DIR` installs into `~/aikos/services/tts` (own venv `.venv-clone`, voices `0700`, token `0600`,
settings `tts.env`) and runs it as the LaunchAgent `home.aikos.tts` (log `~/Library/Logs/aikos-tts.log`). The model loads
once (~10 s) and stays in memory; one synthesis at a time. A short door sentence takes about 5–8 s on an M2 Max (MPS), so
the aikos integration makes waiting notes and the greeting in advance.

## Errors

| Case | What happens |
|---|---|
| Unknown or missing voice | Wyoming error / HTTP 404; nothing is spoken |
| Recording too short, too long, not audio | HTTP 400 with the reason; the old voice stays |
| Client not in the list | Wyoming error / HTTP 403 |
| Wrong token | HTTP 401 |
| The model fails | The request fails; Home Assistant shows the text only (aikos keeps the door working) |

## Tests

`pip install -e ".[test]"`, `pytest` (without the model: `FakeEngine`). CI job `tts-unit`.
