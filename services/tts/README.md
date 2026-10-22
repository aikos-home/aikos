# aikos TTS

Speech in the residents' own voices, locally. The door reads a resident's note or the greeting aloud in that person's voice
(aikos-app A42–A45). Each person records their own voice in the aikos app (Haus → Meine Stimme), so every voice is enrolled
by its owner. Voices, text and audio never leave the machine this runs on (R11). Owner: aikos core.

Version **0.5.0**. Python 3.11. Model: [Chatterbox multilingual](https://github.com/resemble-ai/chatterbox) (MIT licence),
zero-shot voice cloning from a 8–60 s recording, German. Every generated clip carries Chatterbox's inaudible watermark,
so it can be recognised as synthetic. A voice is never proof of identity.

**The model never decides what is said.** With `AIKOS_TTS_WHISPER_URL` (a local whisper-server), every sentence is written
back and compared with the text: whatever the model adds after the text's last word is cut off and the rest is checked
again (an inflected form of a word counts: "Schelmen" for "Schelm", at least 4 letters, at most 2 more); an invented
start or missing words mean another take (up to three, each a little less free); if none fits, nothing
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
| `POST /v1/prepare {voice, texts, draft}` | say these once now in the background (202), so they play at once later; the takes are kept per voice (`cache/`, at most 400, a new recording or deleting the voice drops them). One after the other; `draft: true` (a note still being typed in the app) goes first, and a newer draft of the voice replaces the older one that hasn't started |
| `POST /v1/speak {voice, text}` | a short test sentence (≤ 300 characters) as WAV, to listen to in the app |

Voice ids: `^[a-z0-9][a-z0-9_-]{0,39}$`. The app decides who may change which voice (only the person themself).

## Running it (Mac)

`deploy/install.sh SOURCE_DIR` installs into `~/aikos/services/tts` (own venv `.venv-clone`, or `.venv-mlx` with
`AIKOS_TTS_ENGINE=chatterbox-mlx` in `tts.env`; voices `0700`, token `0600`, settings `tts.env`) and runs it as the LaunchAgent `home.aikos.tts` (log `~/Library/Logs/aikos-tts.log`). The model loads
once (~10 s) and stays in memory; one synthesis at a time. A short door sentence takes about 5–8 s on an M2 Max (MPS), so
the aikos integration makes waiting notes, the greeting and the announcements in advance, and the app makes a note while it
is being typed.

**On MLX** (`chatterbox-mlx`, mlx-audio with `mlx-community/chatterbox-multilingual-v3`): measured 22.10. with a
resident's voice, whole sentences including the Whisper check 1.9–2.2 s (before: 6–8 s), 8 of 8 takes faithful at the first
try; the MLX port has no watermark, so the service adds Chatterbox's own (perth) to every take. The first take after a start
is slow (6 s), so the service warms up with one unheard sentence.

Measured on 22.10. (M2 Max, MPS), one take of a short sentence: the model's speech tokens 2–6 s (about 20 tokens/s, slower
than the speech itself), the vocoder 1.2–2 s, the Whisper check 0.85 s, the watermark 0.01 s. Without guidance or with 5
instead of 10 vocoder steps it is barely faster and says more nonsense, so neither is used.

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

## Deploying a version (from `tts-v0.6.0` on)

`deploy/deploy.sh <tag>` rolls one tagged version out on the Mac and rolls back by itself
([AI host](../../docs/ai-host.md) has the rules all services follow):

```sh
git -C ~/aikos/repo fetch --tags
git -C ~/aikos/repo show tts-v0.6.0:services/tts/deploy/deploy.sh > /tmp/tts-deploy.sh
bash /tmp/tts-deploy.sh tts-v0.6.0
```

1. The tag's `services/tts` goes into a release folder of its own, `~/aikos/releases/tts/<tag>` (`git archive`; the
   clone's working tree, which the transcriber runs from, is never touched).
2. `install.sh --build-only <release>` builds the release's environment and prints its Python; the unit tests run with
   it. Red: nothing is changed.
3. The LaunchAgent is backed up to `~/.aikos/backup`; `install.sh <release>` writes it and starts the service.
4. `GET /v1/health` must report the tag's version, and `POST /v1/selftest` must pass (a fixed sentence in the model's
   built-in voice with the Whisper check; a resident's voice is never used for a test).

A failure in 3–4 restores the previous LaunchAgent, and with it the previous release, and exits 1. The newest three
releases stay. Log: `~/Library/Logs/aikos/deploy.log`. `tests/test_deploy.py` runs the whole flow, the way back included,
with git, launchctl and curl replaced.
