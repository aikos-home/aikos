# aikos app

The household's user interface for aikos: an installable web app (PWA) for phones, later also an Android app. Home
Assistant stays the system of record for entities, devices, states, events, sound and pictures; this service is only the
way to them. It signs people in with passkeys, knows who may see and do what, and is the single path from a phone to
Home Assistant. The phone never gets a Home Assistant token, address or link.

Version **0.7.1** (step 1: sign-in, roles, door messages; step 2: message register, delete, forward by hand, push; step 3: door actions, own voices, door announcements, the live call). Python 3.12+ (aiohttp, py_webauthn); PWA in TypeScript
(Preact, Vite).

Runs on one machine (SQLite) or on three nodes with a replicated database and rollouts of signed images
([`deploy/cluster`](../deploy/cluster/README.md)). Container image: [`Dockerfile`](Dockerfile), dependencies pinned with
hashes in [`requirements.lock`](requirements.lock).

## What it holds, and what not

| Kept here (SQLite in the data folder) | Kept in Home Assistant |
|---|---|
| people, their role and their Home Assistant person, passkeys (public keys only), sessions (hashes only), invites (hashes only), pending passkey challenges, audit log | everything else: door messages (sound, text, recipient), drawings, states, history, devices |

Deleting the data folder loses accounts and passkeys, never door data.

## Interface

HTTP API under `/api/v1`, described in [`aikos_app/api/openapi.json`](aikos_app/api/openapi.json) (also served at
`/api/v1/openapi.json`). The PWA is served from `/`. Summary:

| Area | Endpoints |
|---|---|
| First start | `GET /api/v1/setup`, `POST /api/v1/setup/start` (setup code, name), `POST /api/v1/setup/finish` |
| Sign-in | `POST /api/v1/login/start`, `POST /api/v1/login/finish`, `POST /api/v1/logout`, `POST /api/v1/logout/all` |
| Invites | `POST /api/v1/invites/info`, `POST /api/v1/invites/start`, `POST /api/v1/invites/finish` |
| Me | `GET /api/v1/me`, `GET /api/v1/me/passkeys`, `POST /api/v1/me/passkeys/start` and `/finish`, `DELETE /api/v1/me/passkeys/{id}` |
| People (superadmin) | `GET /api/v1/people`, `POST /api/v1/people/invites`, `POST /api/v1/people/{id}/device-invite`, `POST /api/v1/people/{id}/disable` |
| Door | `GET /api/v1/door/status`, `GET /api/v1/door/messages`, `GET /api/v1/door/messages/{id}/audio` (Range supported; `?share=1` = as a file to forward, recorded), `POST /api/v1/door/messages/{id}/heard`, `DELETE /api/v1/door/messages/{id}` |
| Door actions | `GET /api/v1/door/actions`, `POST /api/v1/door/bell`, `POST /api/v1/door/quiet-hours` (`bell.settings`); `POST`/`DELETE /api/v1/door/say`, `PUT`/`GET`/`DELETE /api/v1/door/picture`, `PUT /api/v1/door/greeting`, `PUT`/`GET`/`DELETE /api/v1/door/greeting/audio`, `PUT /api/v1/door/announcements` (`door.act`; agreeing that the door names one's place only for oneself) |
| My voice | `GET`/`PUT`/`DELETE /api/v1/me/voice`, `POST /api/v1/me/voice/sample` (`door.act`, only one's own) |
| Push | `GET /api/v1/push/key`, `POST /api/v1/push/subscription`, `DELETE /api/v1/push/subscription`, `POST /api/v1/push/test` |
| Other | `GET /api/v1/health` (200 with `ok`, `version`, `commit`, `db`, `ha_connected`; 503 without its database), `GET /.well-known/assetlinks.json` |

**Sessions:** an `HttpOnly`, `Secure`, `SameSite=Strict` cookie for the PWA. A native app sends
`X-Aikos-Client: native` at sign-in and gets a bearer token instead. Browser writes must carry the app's own `Origin`.

**Errors:** `{"error": "<code>"}` with a stable code, e.g. `not_signed_in` (401), `forbidden` (403), `not_found` (404,
also for a message that exists but is not yours), `invalid_code`, `invite_invalid`, `passkey_failed`,
`unknown_passkey`, `flow_expired`, `bad_subscription` (400), `already_set_up` (409), `slow_down` (429), `ha_unreachable`, `no_register`, `no_door_actions` (503); `invalid` (400: Home Assistant refused the input).

## Roles

Fixed in [`aikos_app/roles.py`](aikos_app/roles.py): `superadmin` (everything, including people), `adult` (door,
messages for themselves and for everyone, quiet hours, history, own room), `child` (own messages, own room). A message
for a person is visible to that person and the superadmin only; to everyone else it does not exist.

**Deleting a message** (A38) is for good, sound and text in Home Assistant: the recipient and the superadmin; a message for
everyone: every adult and the superadmin. Recorded in the audit log.

**Forwarding** (A37) happens only when a resident taps "Teilen": the phone fetches the MP3 through the app (recorded as
`message.share`) and hands it with the text to the app the person picks. The service itself never sends sound anywhere.

## Sign-in

Passkeys only (WebAuthn, discoverable credentials, user verification required). No passwords, no open sign-up.

1. First start: a one-time **setup code** is written to `<data dir>/setup-code.txt` (never to the log); print a fresh one
   with `python -m aikos_app setup-code`. Whoever enters it and creates a passkey becomes the superadmin.
2. Further people: the superadmin creates an **invite link** (24 h, single use; the token sits in the URL fragment).
3. New or lost phone: an invite that adds a passkey to an existing person (`python -m aikos_app device-invite <name>`
   on the server, or in the app).

Passkeys are bound to the host name of `AIKOS_APP_PUBLIC_URL`. Changing it later invalidates every passkey. Browsers
only allow passkeys over HTTPS or on `localhost`.

## Home Assistant

One connection (WebSocket API) with a **fixed list of commands** that a non-admin user may run: `get_states`,
`subscribe_entities`, `history/history_during_period`, `media_source/browse_media`, `media_source/resolve_media`,
`call_service` (only `aikos.door_messages`, `aikos.door_message_delete`, `aikos.door_message_heard`). Anything else is
refused inside the app. So the app's Home Assistant account should be a normal user, not an admin.

Door messages come from the aikos integration's **message register** (aikos 0.8.0+, `sensor.aikos_door_messages`):
file, time, seconds, recipient, recognised text, speaker, who heard it. The sound files are in the local media folder
`AIKOS_APP_DOOR_MEDIA_DIR` (default `aikos_door`). Without the register (older aikos) the list is the audio files in that
folder; deleting and "heard" then answer `no_register`. Messages the register adopted from the folder (older ones, no text)
and the folder list can get metadata from two optional interim entities: `AIKOS_APP_INTERIM_LAST_MESSAGE_ENTITY` (state =
file name of the last saved message; attributes `seconds`, `time`, `recipient`) and `AIKOS_APP_INTERIM_MESSAGE_TEXT_ENTITY`
(state = recognised text, cleared when a recording starts).

## Door actions

Through the aikos integration (0.9.0+), each exactly one aikos service with the acting person's name; children have none
of them (matrix 2.4a).
- **Bell:** mute for 1 h, 2 h, until tomorrow 7:00 or until switched off (the ring push still comes, A40); quiet hours on/off,
  start and end.
- **A note to the door** (A11/A39): shown at once if the radar sees someone, else for the next visitor; quick replies; a waiting
  note can be withdrawn. Read aloud in the sender's own voice (A42–A45, see below); while it is typed, a pause of 0.9 s has
  its speech made already (`POST /api/v1/door/say/draft`), so it usually plays at once when sent.
- **Picture** (A12/A41): cropped on the phone to the door's field (fixed 492 : 536; drag, pinch or slider to zoom, grey preview),
  sent as a 984 × 1072 JPEG; aikos turns it into the door's grey PNG, which fills the field. It stays until removed. The preview comes through the app.
- **Greeting** (A13/A26): text (≤ 120) and/or a sound recorded with the phone (≤ 20 s), always or from–until.
- **The live call** (A47, A48; aikos 0.15.0+): on every ring a push to everyone who may act at the door (a storm of rings
  within 30 s is one push; one node sends). The door page shows the call live (`GET /api/v1/door/call`: the call log's
  newest lines, door and house side, with translations) and answers it: a quick reply or text (read in one's own voice),
  or live, holding the button as at a room key (`/api/v1/door/talk`, a WebSocket: the phone's microphone as 16 kHz PCM
  while held; the node turns it into RTP for the door and passes the door's microphone back; one participant per node;
  talk computer 0.7.24 `app_join`/`key_state`). Needs `AIKOS_APP_TALK_HOST` (the node's address, rendered by the cluster
  kit when `door_talk_host` is set) and the door's RTP let in on UDP 5012.
- **Announcements** (aikos 0.11.0+, sprachausgabe S10–S14): the sentences the door says after a ring (parcel expected, everybody
  away, everybody away with places, bell muted or quiet hours), with suggestions and "listen in my voice"; the slider 0–4 of what
  the door may tell. Saved sentences are said in the saver's own voice. Whether the door names one's place, each person decides
  only for themselves (their account's Home Assistant person).

## Own voices

"Meine Stimme" (A43–A45, S9): a person records their own voice in the app, reading a short text that includes their consent.
The recording goes to the house's voice service (`services/tts`, `AIKOS_APP_TTS_URL` + `AIKOS_APP_TTS_TOKEN_FILE`) and nowhere
else; the app keeps no copy. The voice id comes from the account's random handle (the same on every node, says nothing about
the person). Notes to the door and the greeting text are read in the sender's own voice; without one they are only shown.
Deleting removes it for good. The voice service being away only means no reading aloud.

## Push

Web Push (VAPID), built in: message encryption per RFC 8291 (`aes128gcm`) and the VAPID token per RFC 8292 with
`cryptography`, no further library. The key pair is created once and kept in the app's database, so every node sends with
the same key and phones stay subscribed across nodes and rollouts.

- **A new door message:** the app sees `newest` of `sensor.aikos_door_messages` change, waits 6 s for the last words, and
  sends time, length, recipient, speaker and recognised text (A24), never sound (G5), to the phones of the people who may
  see that message (A15). Of several nodes only the one that claims the message first in the database sends. Messages
  older than 10 min get no push (e.g. after a restart).
- **Targets:** only the push services of the browser makers (`fcm.googleapis.com`, `*.push.apple.com`,
  `*.push.services.mozilla.com`, Microsoft's WNS; HTTPS on 443). A subscription is an address the server posts to,
  so anything else is refused (no way into the house network). Gone subscriptions (404/410) are forgotten.
- **Phone:** Haus → Benachrichtigungen → "Auf diesem Gerät einschalten", then "Test". iPhone: only in the installed app
  (iOS 16.4+). The service worker shows the notification; a tap opens the messages.
- The nodes need outbound HTTPS to those services.

## Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `AIKOS_APP_PUBLIC_URL` | `http://localhost:<port>` | address the phones open; its host is the passkey RP ID |
| `AIKOS_APP_LISTEN`, `AIKOS_APP_PORT` | `127.0.0.1`, `8780` | where the service listens |
| `AIKOS_APP_TRUST_PROXY` | off | take the client address from `X-Forwarded-For` (behind a reverse proxy) |
| `AIKOS_APP_DATA_DIR` | `data` | setup code, and the SQLite database when no other is set |
| `AIKOS_APP_DB` | SQLite file in the data folder | `rqlites://a:4001,b:4001,c:4001` = rqlite cluster over HTTPS (own node first; see `deploy/cluster`) |
| `AIKOS_APP_DB_USER`, `AIKOS_APP_DB_PASSWORD_FILE`, `AIKOS_APP_DB_CA_FILE` | – | rqlite user, a file with its password, the cluster CA |
| `AIKOS_APP_COMMIT` | – | the commit of the build (set in the image); shown by `/api/v1/health` |
| `AIKOS_APP_HA_URL`, `AIKOS_APP_HA_TOKEN_FILE` | – | Home Assistant and a file with its long-lived token. As a Home Assistant add-on, `SUPERVISOR_TOKEN` is used instead |
| `AIKOS_APP_WEB_DIR` | bundled `aikos_app/web` | the built PWA (`web/dist`) |
| `AIKOS_APP_ASSETLINKS_FILE` | – | Digital Asset Links JSON for a later Android app |
| `AIKOS_APP_DOOR_MEDIA_DIR` | `aikos_door` | local media folder of the door |
| `AIKOS_APP_TTS_URL` | empty | the house's voice service (HTTP side); empty = no own voices |
| `AIKOS_APP_TTS_TOKEN_FILE` | empty | file with its token |
| `AIKOS_APP_ENTITY_SOMEONE_AT_DOOR`, `…_QUIET_HOURS`, `…_BELL_MUTED` | the aikos names | status entities shown at the top |
| `AIKOS_APP_INTERIM_LAST_MESSAGE_ENTITY`, `AIKOS_APP_INTERIM_MESSAGE_TEXT_ENTITY` | off | see above |

## Develop and test

```sh
cd app
python -m venv .venv && .venv/bin/pip install -e .[test]
.venv/bin/python -m pytest            # API, passkeys (software authenticator), roles, door, contract
cd web && npm ci && npm run build      # type check + PWA into web/dist
```

The tests never talk to a real Home Assistant: a fake answers the allowed commands.
