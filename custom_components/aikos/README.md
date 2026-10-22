# aikos integration for Home Assistant

The household logic of aikos, installed via HACS. Version **0.14.0**: quiet hours (0.1.0), the ring push (0.2.0), the call log (0.3.0; visitor language 0.6.0), the call archive (0.4.x), the
front door (0.5.0, tag `aikos-v0.5.0`), the mic health warning (0.7.0), the door message register (0.8.0), the door actions (0.9.0), reading aloud in the residents' own voices (0.10.0), the door announcements (0.11.0) and parcels from the carriers' mails (0.12.0). More blocks follow (where the bell
rings, presence, alarm, pairing of devices); each comes as a new version.

## Install

1. HACS → Integrations → ⋮ → Custom repositories → `https://github.com/aikos-home/aikos`, type Integration → install **aikos**.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **aikos**. Nothing to type; aikos can be set up once.

## Interface

One device **aikos** (manufacturer `aikos-home`) with these entities. The ids are fixed English ids, the same in every house
and every Home Assistant language; the names follow the language (German: "Ruhezeit", "Ruhezeit Beginn", ...).

| Entity | What |
|---|---|
| `switch.aikos_quiet_hours` | Quiet hours on/off. Default: on |
| `time.aikos_quiet_hours_start` | Start, default 20:00 |
| `time.aikos_quiet_hours_end` | End, default 07:00 |
| `binary_sensor.aikos_quiet_hours` | Quiet hours active right now; attributes `start`, `end` (HH:MM). Switches exactly at start and end, no polling |

**The window:** from start (inclusive) to end (exclusive); it may run over midnight (20:00–07:00) or lie within one day
(13:00–15:00). Start = end means no quiet hours. During quiet hours the room keys give text only and don't ring;
emergencies pass (the keys do this themselves, so it also works while Home Assistant is down; handing the rule to the keys
comes with a later version).

**Settings** are stored in the integration's config entry, so they survive restarts and are in every Home Assistant backup.

### Ring push (0.2.0)

Settings → Devices & services → aikos → **Configure**:

| Option | What |
|---|---|
| Doorbell | The doorbell's `event` entity (a new timestamp = a press), or a `binary_sensor` that turns on when pressed |
| Residents | HA persons. "Nobody home" = none of them is `home` (unknown counts as away) |
| Phones | Notify services, e.g. the mobile app's service `mobile_app_<phone>` |

On a press, aikos sends **"Es hat geklingelt (22:14) · Ruhezeit"** (English if Home Assistant is not set to German) to every phone
when quiet hours are active, or **"… · niemand zu Hause"** when nobody is home. Otherwise nothing.
- Storm ringing and quick repeats give one push per 30 s.
- A device coming back online (unavailable → its last press) is no press.
- Without a doorbell or phones there is no push (default).

### Call log (0.3.0)

The only source of the chat on the door screen and the room keys. Moved here from the `homeassistant/` package without changing
what the devices read.

| Entity | What |
|---|---|
| `sensor.aikos_call_log` | State = time of the newest message. Attributes `call_id`, `active`, `last_id`, `messages` (≤ 20), `messages_json` |
| `sensor.aikos_call_log_test` | The same for bench tests, fed only by `sensor.talk_transcript_test` / `_door_test`, `input_boolean.aikos_test_in_call` and `input_button.aikos_test_new_call` |

- **Sources (live):** `sensor.talk_transcript` (room), `sensor.talk_transcript_door` (door), `binary_sensor.aikos_intercom_talk_in_call`.
- **Per message:** `id` (side + transcript time), `t`, `side` (`door`/`room`), `who`, `role`, `text` (≤ 300 characters), `urgent`, `lang`
  (language name if not German), `spk` (the speaker the transcript named), `dev` (room key), `sticky`.
- **Contract for the devices:** `messages_json` = the newest 10 messages, oldest first, compact JSON text; every message has `id`,
  `side`, `who`, `text`. Changes only through the change path; new fields may be added.
- **R22:** emptied when a call starts and when it ends; a transcript outside a call is not added. **R25:** a visitor's identity
  holds for the call (`sticky`). **R26:** a resident's name holds per room key, never for another key. **R27:** devices get 10.
- A later update of the same transcript replaces the message. Every new message fires the event `aikos_call_message` and writes
  a logbook entry (live log only).
- Survives a restart (the last state is restored).
- **R28, visitor language (0.6.0):** attributes `visitor_language` (code, `""` = German) and `visitor_language_name`. Set by a door
  sentence Whisper is sure of (probability ≥ 0.8, at least 3 words); holds for the call; a sure German sentence sets it back; reset
  at call start and end. When the transcriber sends a resident's answer translated into that language (`text_visitor`,
  `visitor_language`), the message gets `tr` and `tr_lang`: the door screen shows `tr` to the visitor.

### Call archive (0.4.0, for developers)

aikos → Configure → **Call archive** (default off). Every call as JSON lines in `<config>/aikos_archive/calls.jsonl`, kept until you
delete it:
- `call_start` with all `aikos-home` devices (name, model, firmware), including the integration itself;
- `message` for every transcript (`aikos_talk_transcript`), with time, side, speaker, role, text, original, language, device,
  durations, model and transcriber version; since 0.6.0 also `text_visitor` and `visitor_language` (R28);
- `call_end` with the duration.

Bench traffic (`aikos_talk_transcript_test`, `input_boolean.aikos_test_in_call`) is marked `"test": true`. Python writes the file
itself, in order; no shell is involved, so visitor text is stored as data and can never become a command.

### Front door (0.5.0)

aikos → Configure → **Front door sensor**: the door contact (`binary_sensor` or `input_boolean`). `binary_sensor.aikos_front_door`
follows it with 2 s debounce each way (a blip shorter than that is ignored); unavailable while the contact is, or when none is chosen.
Attribute `source`; attribute `stuck` = open for more than 10 min (then it ends nothing more). The devices react to its off → on edge:
opening the front door ends a call (R17.8).

### Mic health warning (0.7.0, W3)

`binary_sensor.aikos_mic_problem` (device class problem) is on while a device's mic is broken. The source is the transcriber's
event `aikos_mic_check` (option `AIKOS_MIC_CHECK=1` there) after every recording:
- **Two bad verdicts in a row** from the same device (`silent`: a dead mic; `clipping`: a floating data line) → on.
  - A persistent notification "Mikro an … sendet nur Stille – Kabel prüfen" appears.
  - A push goes to the phones configured for the ring push.
  - No repeats while it stays broken.
- **The first `ok`** clears it and dismisses the notification.
- Attributes: `problem_devices`, and per device `verdict`, `bad_in_a_row`, `since`, `peak_db`, `rms_db`, `zero_ratio`, `clip_ratio`.
- `binary_sensor.aikos_mic_problem_test` takes only `aikos_mic_check_test` (bench); it never notifies.
- In memory: after a restart it starts clean and finds a broken mic again within two recordings.

### Door message register (0.8.0, for the aikos app)

Every "Nachricht hinterlassen" at the door, kept until someone deletes it (aikos-app A27). Always on; it only listens, nothing
else changes. Stored in Home Assistant (`.storage/aikos.door_messages`, in every backup); the sound stays where the door's
recorder puts it, `<local media>/aikos_door/` (Media → My media).

| Source (the door's contracts) | Used for |
|---|---|
| Event `esphome.aikos_door_message {recipient, source}` (screen, when a recording starts; `""` = everyone) | whom the message is for (holds 5 min, used once) |
| `binary_sensor.aikos_intercom_talk_message_recording` | the recording's start and end |
| `sensor.talk_transcript_door` (attributes `message`/`text`, `speaker`) | the words, while recording and up to 30 s after its end; later words update the saved message |
| Event `aikos_door_message_saved {file, seconds, recipient}` (recorder) | the message; `recipient` only if the screen named nobody. `file` must be a plain `….mp3` name |
| Event `aikos_door_message_failed` | forgets the screen's recipient |

| Entity / service | What |
|---|---|
| `sensor.aikos_door_messages` | State = number of messages. Attributes `revision` (changes with every change: new message, late words, heard, deleted), `newest` (id), `newest_time` |
| `aikos.door_messages` (response only) | `{"messages": [...]}`, newest first. Per message: `id` (file name without `.mp3`), `file`, `time` (ISO, UTC), `seconds`, `recipient`, `text`, `speaker`, `heard_by` (names), `adopted`, `file_missing` |
| `aikos.door_message_delete {id, by}` | Deletes the MP3, then the entry; response `{"deleted": id}`; logbook entry "… gelöscht (by)" |
| `aikos.door_message_heard {id, by}` | Adds `by` to `heard_by` (once per name) |

- **Who may see, hear or delete** a message is the aikos app's decision (A15, A38): it is the residents' only way in. The services
  need no admin rights (the app's service account is no admin).
- **Older messages:** recorder files (`nachricht-*.mp3`) nobody told the register about are taken in when it starts or lists
  (`adopted: true`, time = file time, no text, no recipient). Other files in the folder (greetings) are no messages.
- **A file deleted outside** (media browser): the entry stays with `file_missing: true`; nothing is deleted automatically.
- No signed Home Assistant link and no sound ever goes into the register or the entity.

### Door actions (0.9.0, for the aikos app)

What a resident does at the door from the app (aikos-app A11–A14, A39–A41). Kept in Home Assistant (`.storage/aikos.door_actions`);
it uses the door's contracts and only writes the door entities named here.

| Entity / service | What |
|---|---|
| `binary_sensor.aikos_bell_muted` | **Door contract:** on while the bell is muted (the screen behaves as in quiet hours; room keys should follow). Attribute `until` (ISO, `""` = until switched off) |
| `switch.aikos_bell_mute` | On = muted until switched off |
| `aikos.bell_mute {minutes \| until_time \| forever}`, `aikos.bell_unmute` | Mute for some minutes (≤ 7 days), until the next such time of day ("bis morgen 7:00"), or until switched off. Ends by itself |
| `aikos.quiet_hours {enabled, start, end}` | The quiet-hours settings of 0.1.0, for a client without admin rights |
| `aikos.door_say {message, sender}` → `{delivered: now \| waiting}` | Someone at the door (radar): shown right away via `esphome.aikos_intercom_screen_show_reply`, event `aikos_door_reply {sender, text}`, logbook. Nobody there: waits for the next visitor (radar off → on), then the same, and gone |
| `sensor.aikos_door_note` | `waiting` / `none`; attributes `message`, `sender`, `since`. `aikos.door_say_cancel` withdraws it |
| `aikos.door_picture {image}` → `{path}`, `aikos.door_picture_clear` | Any photo (base64) → grey PNG ≤ 492×536 with the panel's 16 grey levels under `/local/aikos_door/` (random name, the old one is deleted), `text.aikos_intercom_screen_photo_url` set to it. Stays until removed |
| `sensor.aikos_door_picture` | `shown` / `none`; attribute `path` |
| `aikos.door_greeting {enabled, text, start, end, clear_window, audio, clear_audio}` | Text (≤ 120) and/or a recorded sound (base64: WebM, Ogg, M4A, MP3, WAV; ≤ 3 MB, kept in `<local media>/aikos/`) for everyone who comes. `text.aikos_intercom_screen_greeting` holds the text only within the window (switched exactly at start and end). The sound plays when the radar sees someone: within the window, not during a call or a message, once per 10 min |
| `sensor.aikos_door_greeting` | `active` / `scheduled` / `off`; attributes `enabled`, `text`, `start`, `end`, `audio`, `audio_file` (in `<local media>/aikos/`), `last_played` |

- **Ring push while muted:** muted means nobody hears the bell, so the ring push goes to the phones as in quiet hours (A40):
  "Es hat geklingelt (14:00) · Klingel stumm".
- **The sound at the door:** ffmpeg decodes it, `esphome.aikos_intercom_talk_allow_tts {host, ms}` lets the door play this machine's
  RTP (L16, 16 kHz, PT 96) on UDP 5004 of the talk computer (found from its ESPHome entry `aikos-intercom-talk`). All in the house.
- **Reading aloud (0.10.0, A42-A45):** aikos → Configure → **Voice service (TTS)**: a local TTS entity (the aikos TTS service on
  the house's own machine, through the Wyoming integration). `aikos.door_say` and `aikos.door_greeting` take `voice` = the
  sender's voice there; without a voice (or without a service) the text is only shown. A note now is read right after it is
  shown; a waiting note and the greeting text are made in advance (`<local media>/aikos/speech-*`) and play at once when someone
  comes. A recorded greeting sound goes before the read text. The voice service failing never breaks the door: the text is shown.
- **Said on the spot (0.13.0):** a note now, or an announcement whose sentence isn't made yet, first gets the door's own
  short cue (`esphome.aikos_intercom_talk_tts_cue`, talk computer 0.7.26) and then plays sentence by sentence, each while the
  next is made. If a sentence can't be said faithfully, the rest isn't said either.
- **A waiting note goes first:** at that visit no greeting sound plays on top of it.
- **A visit (0.14.0, the owner's rule):** a new visit begins only after the radar saw nobody for 2 minutes. A shorter gap
  (the radar losing someone right in front of it, or the radar going away for a moment) is the same visit: no second
  greeting, no waiting note, no parcel announcement. The door's welcome page follows the same rule (screen 0.7.26).
- **The screen's greeting text** is left alone until a greeting is set through aikos once; from then on aikos owns it.

### Door announcements (0.11.0, sprachausgabe S10–S14)

After a ring the door says one sentence in a resident's own voice when a situation applies. The residents write the sentences
(in the aikos app); aikos only picks which one, no model decides what is said. Default: level 0 = nothing is said.

| Interface | Meaning |
|---|---|
| `number.aikos_door_disclosure` | 0–4, what the door may tell: 0 nothing; 1 that nobody can come or nobody is home, where to leave a parcel; 2, 3 as 1 for now; 4 also where the residents are (only residents in `named`, only zones in `places`) |
| `aikos.door_announcements {disclosure, parcel, away, quiet, away_places, places, named, voice}` | Sets what is given (sentences ≤ 200; `away_places` needs `{wo}`, replaced by "A ist beim Laden und B ist im Studio"; `places` = zone → how the door says it, ≤ 20; `named` = person ids who agreed; `voice` = whose voice says them). Returns the settings |
| `sensor.aikos_door_announcements` | What a ring would get now: `parcel` / `away` / `quiet` / `none`; attributes the settings, `now_text`, `ready` (sentences made in advance), `last` {situation, text, at}, `zones` and `residents` to choose from |
| Option **Parcel expected (sensor)** | A binary sensor or input boolean, on while a delivery is expected today; empty = aikos' own `binary_sensor.aikos_parcel_expected` (below) |
| Event `aikos_door_announced {situation, text}`, logbook "angesagt: …" | After each announcement |

- **Situations,** the first that applies and has a sentence wins: **parcel** (the parcel sensor is on; this one also speaks when
  someone only comes close, instead of the greeting sound, S14), **away** (every resident is known to be away; unknown is not
  away), **quiet** (bell muted or quiet hours).
- **Made in advance:** every sentence the level allows, as it would be said now, is made when saved and again 5 s after the
  residents move (`<local media>/aikos/speech-announce-*`). A ring before that: the sentence is made on the spot (a little later).
- **When:** 1.5 s after the ring; not during a call or a message; a second ring within 60 s gets no second announcement. Without
  a voice or a voice service nothing is said.

### Parcels from the carriers' mails (0.12.0, sprachausgabe S15)

| Interface | Meaning |
|---|---|
| Options **Parcel mails: mailbox / app password / IMAP server** | One mailbox (IMAP over TLS, port 993; default server `imap.gmail.com`), with an app password, not the normal one. The login is tried before it is stored. Empty mailbox = off; empty password = keep the stored one |
| `binary_sensor.aikos_parcel_expected` | On while a carrier's mail says a parcel comes today and no "delivered" followed; attributes `carriers`, `soon`, `window` ("13:45–15:45"), `checked`, `error` (`login` / `connect` / `search`), `configured`. No subjects, no items |

- **What is read:** every 3 minutes, the inbox, read-only, only mails since yesterday from the carriers' domains (Amazon, DHL,
  DPD, Hermes, GLS, UPS), and of those only sender, subject and date (`BODY.PEEK` of three header fields: nothing is marked as
  read, no text is fetched). The whole day is read each time, so a mail missed once costs nothing.
- **The rules** (`parcel_rules.py`, no model): "In Zustellung", "kommt heute", "Zustellung heute", "zwischen 13:45 und 15:45"
  = today; "wird gleich zugestellt" = soon; "Zugestellt", "Geliefert", "wurde zugestellt", "ist da", "liegt im Briefkasten"
  = delivered; anything else is no notice. Followed per shipment: Amazon by its item, the other carriers by the carrier (two
  parcels of one carrier count as one: at worst a courier is not expected). Over with "delivered", one hour after the time
  window, or at 21:00; a new day starts empty.

## Errors

| Case | What happens |
|---|---|
| A stored time can't be read | The default is used (20:00 or 07:00) |
| A configured phone's notify service doesn't exist (any more) | Warning in the log; the other phones still get the push |
| A notify service fails | Logged; the others still get it, the integration keeps running |
| The archive file can't be written | Logged; calls and everything else go on |
| Second "Add integration" | Refused: aikos is set up once |
| Integration removed | Its entities go away; nothing else in Home Assistant changes |
| A door message's MP3 can't be deleted | The service fails, the entry stays (nothing half-deleted) |
| Unknown message id for delete/heard | The service fails with "Es gibt keine Türnachricht …" |
| The recorder names an unusable file | Warning in the log; nothing is registered |
| The door screen is offline when a note is sent | The note waits (`waiting`) and goes at the next visit |
| A door text entity is unavailable | Not written; the greeting text is set again when the screen comes back |
| The talk computer is not reachable | The greeting sound is skipped (warning in the log); it is tried at the next visit |
| The voice service is away when an announcement is due | Nothing is said (warning in the log); the ring push goes as always |
| `away_places` without `{wo}`, `{wo}` in another sentence, level outside 0–4 | The service fails with "Geht nicht: …"; nothing changes |
| The parcel mailbox refuses the login or can't be reached | In the options: the form says so and stores nothing. Later: the sensor keeps its last answer, `error` says why, one warning in the log |
| Not a picture / not a sound file / end before start | The service fails with "Geht nicht: …"; nothing changes |

## Structure

| File | Job |
|---|---|
| `quiet_hours.py` | The time rules only (in window? next change?), no Home Assistant code |
| `settings.py` | Reads and stores the settings, tells the entities about changes |
| `entity.py` | What all aikos entities share (the device) |
| `switch.py`, `time.py`, `binary_sensor.py` | The entities |
| `ring_push.py` | When a press becomes a push, and its text (no Home Assistant code) |
| `ring_notifier.py` | Watches the doorbell and sends the push |
| `call_log.py` | The call-log rules (R22, R25–R28), no Home Assistant code |
| `sensor.py` | The call log sensors, event and logbook |
| `call_archive.py` | The archive's lines (no Home Assistant code) |
| `archive_writer.py` | Listens to calls and transcripts, appends the lines |
| `front_door.py` | The debounced front door |
| `mic_health.py` | When mic verdicts become a warning (no Home Assistant code) |
| `mic_problem.py` | The mic problem sensors, notification and push |
| `door_messages.py` | The door message register's rules (recipient, words, heard, storage form), no Home Assistant code |
| `message_register.py` | Listens to the door, keeps the register in HA's storage, deletes the MP3 |
| `door_rules.py` | The door actions' rules (mute end, note, greeting window, storage form), no Home Assistant code |
| `door_actions.py` | Mute, note, picture, greeting in Home Assistant: storage, timers, radar |
| `door_entities.py` | The door actions' entities |
| `door_picture.py` | Photo → the panel's grey PNG (Pillow) |
| `door_speaker.py` | A sound file to the door speaker (ffmpeg, RTP) |
| `door_speech.py` | Speech in a resident's voice as a file, played at the door (notes, greeting, announcements) |
| `announce_rules.py` | The announcements' rules (level, situations, places), no Home Assistant code |
| `door_announce.py` | The announcements in Home Assistant: ring, radar, residents, made in advance |
| `announce_entities.py`, `number.py` | The announcements' sensor and the disclosure slider |
| `parcel_rules.py` | Which carrier mail says what, and whether a parcel is still expected (no Home Assistant code) |
| `parcel_mail.py` | Reads the mailbox (imaplib, in an executor), keeps the parcel state |
| `services.py` | The services for the aikos app |
| `config_flow.py`, `__init__.py` | Setting up and removing aikos |

## Tests

`tests/aikos/` in this repository, run in a real Home Assistant test instance
(Python 3.14, `pip install pytest-homeassistant-custom-component==0.13.367` = Home Assistant 2026.9.4, then `pytest tests/aikos`). CI job `integration-unit`.

## History

- 0.14.0: the visit rule: a new visit only after 2 minutes without radar (greeting, waiting note, parcel announcement);
  the greeting's 10-minute pause is replaced by it.
- 0.13.0: speech said on the spot plays sentence by sentence (the first while the next is made), after the door's cue.
- 0.12.0: parcels from the carriers' mails (options "Parcel mails", `binary_sensor.aikos_parcel_expected`); the door
  announcements use it when no other parcel sensor is set.
- 0.11.0: door announcements after a ring in a resident's own voice (parcel, away with places, quiet), the disclosure slider
  `number.aikos_door_disclosure` (default 0 = nothing), option "Parcel expected (sensor)".
- 0.10.1: a note shown before its speech was ready no longer leaves the speech file behind.
- 0.10.0: notes and the greeting read aloud in the sender's own voice through a local TTS (option "Voice service"); speech made
  in advance for waiting notes and the greeting.
- 0.9.1: the screen's greeting text stays as it is until a greeting is set through aikos (0.9.0 emptied it at start).
- 0.9.0: door actions for the aikos app (bell mute with the ring push still going, quiet hours as a service, note to the door
  now or for the next visitor, door picture, greeting with window and sound); provides `binary_sensor.aikos_bell_muted`.
- 0.8.0: door message register for the aikos app (`sensor.aikos_door_messages`, `aikos.door_messages`, `aikos.door_message_delete`,
  `aikos.door_message_heard`); takes over what the door's proof of concept wrote into helpers (words, recipient, last message).
- 0.7.0: W3 mic health warning (`binary_sensor.aikos_mic_problem`, notification, push) from the transcriber's `aikos_mic_check`.
- Docs (after 0.6.0): the Call archive and Front door sections and the Errors heading were lost from this README in 0.3.0–0.5.0
  (an edit replaced the heading the later inserts looked for); restored.
- 0.6.0: R28 visitor language in the call log; translations for the visitor in the log (`tr`, `tr_lang`) and the archive.
- 0.5.0: the front door moves here from the package (option "Front door sensor" instead of `input_text.aikos_front_door_source`).
  The archive option no longer turns off when the options are saved without it.
- 0.4.1: the archive reads the device registry the supported way (no deprecation warning; would have stopped working in HA 2027.9).
- 0.4.0: the call archive moves here from the package (an option instead of File integration + allowlist; same file and lines,
  plus the integration's own version in `call_start`).
- 0.3.0: the call log moves here from the `homeassistant/` package (same entity ids and attributes; the Jinja macro is gone).
- 0.2.0: ring push to the residents' phones during quiet hours or when nobody is home (requirements 1 and 3,
  `features/klingelregeln.md` KR-R3, KR-R12); options flow for doorbell, residents, phones. Quiet hours unchanged.
- 0.1.0: first version; quiet hours (moved here from the `homeassistant/` package, same `binary_sensor.aikos_quiet_hours`).
