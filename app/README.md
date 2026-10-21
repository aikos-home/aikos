# aikos app

The household's user interface for aikos: an installable web app (PWA) for phones, later also an Android app. Home
Assistant stays the system of record for entities, devices, states, events, sound and pictures; this service is only the
way to them. It signs people in with passkeys, knows who may see and do what, and is the single path from a phone to
Home Assistant. The phone never gets a Home Assistant token, address or link.

Version **0.1.0** (step 1: sign-in, roles, door messages). Python 3.12+ (aiohttp, py_webauthn); PWA in TypeScript
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
| Door | `GET /api/v1/door/status`, `GET /api/v1/door/messages`, `GET /api/v1/door/messages/{id}/audio` (Range supported) |
| Other | `GET /api/v1/health` (200 with `ok`, `version`, `commit`, `db`, `ha_connected`; 503 without its database), `GET /.well-known/assetlinks.json` |

**Sessions:** an `HttpOnly`, `Secure`, `SameSite=Strict` cookie for the PWA. A native app sends
`X-Aikos-Client: native` at sign-in and gets a bearer token instead. Browser writes must carry the app's own `Origin`.

**Errors:** `{"error": "<code>"}` with a stable code, e.g. `not_signed_in` (401), `forbidden` (403), `not_found` (404,
also for a message that exists but is not yours), `invalid_code`, `invite_invalid`, `passkey_failed`,
`unknown_passkey`, `flow_expired` (400), `already_set_up` (409), `slow_down` (429), `ha_unreachable` (503).

## Roles

Fixed in [`aikos_app/roles.py`](aikos_app/roles.py): `superadmin` (everything, including people), `adult` (door,
messages for themselves and for everyone, quiet hours, history, own room), `child` (own messages, own room). A message
for a person is visible to that person and the superadmin only; to everyone else it does not exist.

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
`call_service` (only for allowed domains; none in step 1). Anything else is refused inside the app. So the app's Home
Assistant account should be a normal user, not an admin.

Door messages are the audio files in the local media folder `AIKOS_APP_DOOR_MEDIA_DIR` (default `aikos_door`). Until the
aikos integration keeps a message register, two optional entities add metadata: `AIKOS_APP_INTERIM_LAST_MESSAGE_ENTITY`
(state = file name of the last saved message; attributes `seconds`, `time`, `recipient`) and
`AIKOS_APP_INTERIM_MESSAGE_TEXT_ENTITY` (state = recognised text, cleared when a recording starts).

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
