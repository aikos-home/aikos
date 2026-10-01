# aikos_voice

The voice link between the aikos door station and the room keys. It is one ESPHome external component that **both**
devices use, so they can't drift apart.

**This branch is voice v2** (rule R17 of the project owner, `features/sprechen.md`): a **call** ("Telefonat") instead of
push-to-talk at the door. **voice v1** is frozen at tag `voice-v1.0.0` (see [`FROZEN.md`](../../../FROZEN.md)); its README
is at that tag. Until v2 is tagged, devices stay on `voice-v1.0.0`.

Screens, buttons and Home Assistant glue stay in the device configs and may change as often as needed. The voice link
itself only changes through this component and its tests.

## Rules (voice v2)

The rules live in one place, `call.h`, as a pure state machine: events in, "who hears what" out. Case 1 (it rang) and
case 2 (nobody rang) differ only in what starts the call.

| | |
|---|---|
| Start | Case 1: after a ring the visitor presses "Sprechen" once, or a key holds. Case 2: a key holds without a ring |
| Join | Holding a key joins and talks; one short press joins to listen only (R19) |
| Door mic | Open for the whole call, closed outside it. Towards the keys it is muted while the door speaker plays and 0.3 s after (echo); the transcriber copy is never muted |
| Key mic | Open only while its button is held |
| Door speaker | Plays the key that has the floor, only while it holds. The first key to hold has the floor; a second one is busy ("besetzt") and gets the floor if it still holds when the first lets go. Every key that answered is in the call |
| Key speaker | Plays the door only while that key does not hold, and only if it is in the call, or its owner wants to hear visitors before answering (per-key setting with times) and no key has answered yet (R19) |
| Busy | A key that holds while another has the floor sends nothing, not even to the transcriber |
| End | 10 s without speech on either side (a held button counts as speech), 5 min at most, from outside (front door, API), or every key that answered has left. Each key also leaves on its own silence or max length, or when the front door opens and its owner switched that on |
| Holds | Keys report their state with every packet (about every second); none for 3 s = released. A button still held when a call ends starts no new call until pressed again. A hold longer than 90 s is a stuck button: it loses the floor and counts no longer until let go |
| Gaps | A key that misses the door's "call on" (Wi-Fi gap) stays in the call for 3 s + the silence time. A key that started a call and hears nothing from the door for 3 s shows "door unreachable" |
| Ids | Call ids continue from a random 24-bit start after every boot |
| Wire | RTP v2, L16 big-endian, PT 96, 16 kHz mono, 20 ms (320 samples), UDP 5004, unicast; the end of speech is one comfort-noise packet (PT 13, 1 byte); as in v1 |
| Network | 3 silent latch frames to a new target (0, +0.1 s, +0.4 s); a keepalive to every target and the transcriber at once and every 60 s while not talking (lwIP forgets a MAC after 300 s) |
| Mic | 120 Hz high-pass, gain, and a peak limiter (about −2 dBFS) instead of clipping |

## Use

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/aikos-home/aikos
      ref: voice-v2.0.0        # once tagged; never a branch on a device
      path: esphome/components
    components: [aikos_voice]

aikos_voice:
  id: voice
  role: door                 # door (the arbiter of the call) | room (one room key)        (required)
  microphone: mic            # a 16-bit mono microphone source at 16 kHz                    (required)
  speaker: spk               # optional; without it nothing is played
  # door: ""                  room: the door's "host[:port]" (also at runtime: aikos_voice.set_door)
  # transcriber: ""           "host:port" that gets a copy of what this end says; empty = off
  # silence_end: 10s          R17.8 (a number entity on the device should set it: aikos_voice.set_silence_end)
  # max_length: 300s          safety
  # mute_tail: 300ms          door: muted towards the keys this long after its speaker played
  # hold_refresh: 3s          a key's state not heard this long = released
  # ring_window: 120s         a key that holds this soon after a ring answers it (case 1)
  # prebuffer: 300ms          door: a key's first words before its hold arrived are still played
  # port: 5004, latch_frames: 3, keepalive: 60s (0 = off), mic_gain: 4.0, highpass: true
  # mic_start_mute: 0ms       zeroes the first samples of every mic start (boards that pop)
  # on_talk_start / on_talk_stop / on_call_start / on_call_end (variable `reason`: "silence", "door unreachable", ...)

binary_sensor:
  - platform: aikos_voice
    in_call: {name: In call}               # door: a call is on; room: this key is in the call
    talking: {name: Mic sending}
    remote_holding: {name: Room key holds} # door: a key has the floor
    answered: {id: door_answered}          # door: some key answered (sent to the keys)
    busy: {name: Busy}                     # room: holding while another key has the floor
sensor:
  - platform: aikos_voice
    call_id: {id: door_call_id}            # door: the id while a call is on, 0 = none (sent to the keys)
    floor_key: {id: floor_key}             # door: last octet of the key that has the floor, 0 = nobody (sent)
    members: {name: Call members}
    key_state: {id: key_state}             # room: 0 idle, 1 in the call, 2 holds (send it to the door)
    tx_packets: {name: RTP packets sent}   # counters, every 5 s
    rx_packets: {name: RTP packets received}
    held_back: {name: RTP packets held back}
    tx_errors: {name: RTP errors}
```

### Actions and conditions

| Action | Parameters | Role | Effect |
|---|---|---|---|
| `aikos_voice.ring` | — | door | The bell rang (starts the ring window) |
| `aikos_voice.visitor_speak` | — | door | The screen's one-time "Sprechen": starts the call (case 1) |
| `aikos_voice.key_hold` | `host`, `held` | door | A key's button; call it with every packet from that key |
| `aikos_voice.key_in_call` | `host`, `in_call` | door | A key joined (short press) or left by its own rules |
| `aikos_voice.set_keys` | `"ip,ip,…"` | door | Every key that gets the door's audio during a call (each key decides whether to play it) |
| `aikos_voice.hold` | `held` | room | This key's button |
| `aikos_voice.join` | — | room | One short press: join to listen (R19) |
| `aikos_voice.door_call` | `on`, `call_id`, `answered` | room | The door's announcement; call it with every packet from the door |
| `aikos_voice.floor_key` | `key` | room | The door's floor (last octet, 0 = nobody); busy if it's another key |
| `aikos_voice.hear_visitor` | bool | room | The owner's "hear visitors before answering", already evaluated with its times and quiet hours |
| `aikos_voice.set_door` | `"host[:port]"` | room | The door's address |
| `aikos_voice.record` | bool | room | A test recording: mic to the transcriber only, never to the door |
| `aikos_voice.end` | — | both | Door: end the call (from outside). Room: leave it (the front-door switch) |
| `aikos_voice.speech_door`, `speech_room` | — | both | Report speech at that end, e.g. new visitor text when noise fools the level detector |
| `aikos_voice.set_transcriber` | `"host:port"` | both | Where the copy goes; empty = off |
| `aikos_voice.set_silence_end`, `set_max_length` | duration | both | The two number entities |
| `aikos_voice.allow_source` | `host`, `duration` | both | Plays a trusted sender for a while (e.g. TTS later) |
| `aikos_voice.set_mic_gain` | `gain` | both | 0.1..64 |

Conditions: `aikos_voice.is_talking`, `aikos_voice.in_call`, `aikos_voice.remote_holding`.

### Messages between the devices

ESPHome `packet_transport`, encrypted with a shared key, sent on change and every second. A **sensor** fires on every
packet, a binary sensor only on change, so the states that must refresh are numbers:

| From | To | `remote_id` | Glue |
|---|---|---|---|
| key | door | `key_state` (sensor: 0 idle, 1 in the call, 2 holding; take the component's `key_state` sensor: a busy key still reports 2) | `key_in_call(host, state ≥ 1)` and `key_hold(host, state = 2)` with every packet |
| door | keys | `door_call_id` (sensor: the id, 0 = no call), `door_answered` (binary), `floor_key` (sensor) | `door_call(id ≠ 0, id, answered)` with every packet; `floor_key(key)` |

Which key has which address the door learns from aikos (`sensor.aikos_people`, attribute `keys_json`) and keeps in flash.
The door sends its messages as broadcast, so a new key needs no reflash of the door.

## Error cases

| Situation | What happens |
|---|---|
| Network not up yet | The UDP socket opens on its own once the network is connected; nothing is sent before that |
| A key, door or transcriber address that isn't usable | Warning in the log; the call is ignored (the transcriber copy is switched off) |
| Audio from a key that hasn't got the floor (door) | Held for 0.3 s (its hold may still be coming), then counted in `held_back`, never played |
| Audio from anyone but the door, or a call this key isn't in (room) | Not played, counted in `held_back` |
| A key's packets stop (Wi-Fi gap, crash) | Its hold ends after 3 s; it stays a member until its own rules end it |
| The door's packets stop (room) | The key stays in the call for 3 s + the silence time, then leaves |
| `sendto` fails (target gone, no route) | Counted in `tx_errors`; talking goes on |
| The main loop can't keep up with the mic | Samples are dropped; the RTP sequence shows a gap rather than spliced audio |
| Keepalives, comfort-noise packets, other payload types | Nothing to play; ignored |
| More than 8 keys | The ninth is ignored |

## Built for what comes next

Sources and sinks, not hard wiring. The link takes samples from the mic (`push`), plays them to a sink (the speaker),
sends copies to a tap (the transcriber) and accepts **trusted sources** for a while (`allow_source`), e.g. a TTS stream
speaking to the visitor. A recorder ("leave a message") is another tap. The network sits behind `Transport`, so the
core runs on a PC for tests. Pairing in the HA GUI (`features/kopplung.md`) will replace the shared key in YAML later.

## Files

| File | |
|---|---|
| `types.h` | `Addr`, `Role` |
| `dsp.h` | High-pass filter and limiter for the mic |
| `level.h` | `VoiceGate`: "is somebody talking?" from levels (speech-based call end), and `level_db` |
| `call.h` | The call model (`DoorCall`, `KeyCall`): who hears what, start and end |
| `voice_core.h` | The link: moves audio (targets, gate, play policy, wire); pure C++17, no ESPHome, no sockets |
| `voice_udp.h` | The UDP transport (lwIP; BSD sockets in a host build) |
| `aikos_voice.h/.cpp`, `*.py` | The ESPHome component: wires call, link, mic, speaker, actions and sensors |

## Never without the tests

CI runs all three on every pull request, also with `-Wall -Wextra`:

1. `esphome/tests/aikos_voice/voice_core_test.cpp`: 51 checks of the link (wire rules from v1, targets, gate, policy).
2. `esphome/tests/aikos_voice/call_test.cpp`: 113 scenario checks of the call model, one per rule (each rule was broken
   on purpose once and caught).
3. `esphome/tests/aikos_voice/level_test.cpp`: the speech detector.

### From v1 to v2: the 25 v1 checks that changed

27 of v1's 52 checks are still in `voice_core_test.cpp` word for word (wire, release, copy, latch, keepalive, overrun). The other 25,
and what covers them now (`L` = `voice_core_test.cpp`, `C` = `call_test.cpp`, `live` = `voice_live_test.py`):

| v1 check | v2 | |
|---|---|---|
| latch: the same peer again: no new latch | L latch: "a target that stays gets no new latch" | same rule, several targets |
| lock: nothing played before the hold | C lock: "no call / nobody holds: nothing is played"; L policy: "HOLD: nothing played yet" | moved into the call model |
| lock: the hold starts the conversation | C case 2: "the hold starts call 1" | |
| lock: only the recent frame played | L policy: "flush plays only the recent frame of that sender" | prebuffer = HOLD + flush |
| lock: the old frame held back | L policy: "the old one held back, the recent one counted" | |
| lock: the holding key is played live | L policy: "PLAY: played live"; C case 2: "the door plays the holding key, nobody else" | |
| lock: rx counts played packets | L policy: "… the recent one counted" (`rx_packets`) | |
| lock: the stranger's frame held back on release | L policy: "DROP: not played, held back"; C lock: "a stranger isn't" | |
| lock: released: not played any more | C case 2: "released: not played any more (lock), call still on" | |
| half-duplex: dropped while talking | retired by **R17.2**: the door mic is open for the whole call and the door plays the floor holder meanwhile (L: "played while this end talks"); half-duplex lives at the key (**R17.4**, C: "never plays the door while holding") | |
| end: still held at 89 s | C stuck button: "90 s: still talking" | v1's hold_max, kept |
| end: hold_max closes it | C stuck button: "after 90 s: A is stuck, not played, not holding" (+ the key side) | |
| end: conversation still on at 119 s idle | retired by **R17.8** (10 s instead of 2 min): C case 2: "9.999 s after the last words: still on" | |
| end: ended after 120 s idle | **R17.8**: C case 2: "10 s without speech ends it"; live step 6 | |
| room: dropped unheard, no latch | C key: "setting off: silent, text only"; L policy: "DROP" | |
| room: latched the door | retired: the key's door is configured (`set_door`); no first-sender latch (RoomKey review: any sender on the LAN could become the peer) | |
| room: door played | C key: "released: plays the door (it answered)" | |
| room: stranger held back | L policy: "DROP: not played, held back" (the key's policy plays the door's address only) | |
| room: a latched peer is forgotten when the conversation closes | C key: "the door ended the call" | |
| keepalive: at once to both | L keepalive: "at once to all three" | several targets |
| trusted source: played without any hold | L trusted: "played although the policy says DROP" | |
| edges: a key holds: one start edge | L edges: "one start"; C case 2: "the hold starts call 1"; live: "on_call_start fired once" | |
| edges: released: still in the conversation | C case 2: "released: … call still on" | |
| edges: 2 min without audio: one end edge | **R17.8**: L edges: "one end"; C: "10 s without speech ends it"; live: "on_call_end fired once" | |
| edges: aikos_voice.end: one end edge too | C: "end from outside: over"; live: "ended from outside" | |

The live test against a real door (`voice_live_test.py`) is rewritten for v2 before the tag. Both must pass before a tag.
Devices pin a tag. Changes go through a pull request reviewed by the intercom and roomkey maintainers (see
[`CLAUDE.md`](../../../CLAUDE.md)).
