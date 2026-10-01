# aikos_voice

The voice link between the aikos door station and the room keys. It is one ESPHome external component that **both**
devices use, so they can't drift apart.

Behaviour = **voice v1**. The project owner marked it done on 2026-10-01 after the first live test door ⇄ room key, and
it is frozen at tag `voice-v1.0.0` (see [`FROZEN.md`](../../../FROZEN.md)). Screens, buttons and Home Assistant glue stay
in the device configs and may change as often as needed. The voice link itself only changes through this component and
its tests. The next version (voice v2: one call model for "it rang" and "nobody rang", door mic on for the whole call)
will be built next to it on a branch and gets its own tag.

## Rules (voice v1)

| | |
|---|---|
| Wire | RTP v2, L16 big-endian, PT 96, 16 kHz mono, 20 ms (320 samples), UDP 5004, unicast |
| Talk | Push-to-talk on both ends, no answer, no hang-up. Release = send the last buffered samples, then one comfort-noise packet (PT 13, 1 byte) = end of speech |
| Copy | While talking, every packet also goes to the transcriber address (not twice if it is the peer) |
| Duplex | Half: nothing is played while this end talks |
| Door role | Plays a key **only while that key holds its button** (`remote_hold`, forwarded by Home Assistant). Up to 0.3 s of audio it sent before the hold arrived is played too. Everything else is counted as held back and never played |
| Room role | Plays the peer while a conversation is accepted (`set_accept`). If no peer is set, the first sender becomes the peer |
| End | 2 min without audio in either direction ends the conversation (the peer is forgotten) |
| Network | 3 silent latch frames to a new peer (at 0, +0.1 s and +0.4 s). A keepalive goes to a new peer or transcriber at once, then every 60 s while idle, because lwIP forgets a MAC after 300 s |
| Mic | 120 Hz high-pass, gain, and a peak limiter (about −2 dBFS) instead of clipping |

## Use

Pin the tag, never a branch:

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/aikos-home/aikos
      ref: voice-v1.0.0
      path: esphome/components
    components: [aikos_voice]

aikos_voice:
  id: voice
  role: door                 # door | room                                   (required)
  microphone: mic            # a 16-bit mono microphone source at 16 kHz      (required)
  speaker: spk               # optional; without it nothing is played
  # port: 5004                UDP port for RTP, in and out
  # transcriber: ""           "host:port" that gets a copy while talking; empty = off
  # idle_timeout: 120s        conversation ends after this long without audio
  # prebuffer: 300ms          door: audio a key sent this long before its hold arrived is still played
  # hold_max: 90s             door: a lost "released" can't keep the door playing longer
  # latch_frames: 3           silent frames to a new peer (0..10)
  # keepalive: 60s            12-byte RTP header to peer and transcriber while idle
  # mic_gain: 4.0             0.1..64
  # highpass: true            120 Hz
  # on_talk_start / on_talk_stop / on_conversation_start / on_conversation_end: automations

binary_sensor:
  - platform: aikos_voice
    talking: {name: Talking}
    in_conversation: {name: In call}
    remote_holding: {name: Room key holds}
sensor:
  - platform: aikos_voice     # counters, published every 5 s
    tx_packets: {name: RTP packets sent}
    rx_packets: {name: RTP packets received}         # played
    held_back: {name: RTP packets held back}         # received, never played
    tx_errors: {name: RTP errors}
```

The microphone's sample rate is checked when the config is validated: it must be 16000.

### Actions and conditions

| Action | Parameters | Effect |
|---|---|---|
| `aikos_voice.talk_start` / `talk_stop` | — | This end starts or stops talking (push-to-talk) |
| `aikos_voice.remote_hold` | `held` (bool), `peer_host` ("ip" or "ip:port", optional) | Door: the key at `peer_host` holds or released its button. Holding makes it the peer and plays it. An empty `peer_host` means the current peer |
| `aikos_voice.set_peer` | `host`, `port` (default 5004) | Sets the peer and sends the latch frames |
| `aikos_voice.end` | — | Stop talking, forget the peer, stop the speaker |
| `aikos_voice.set_transcriber` | `address` ("host:port", empty = off) | Where the copy goes |
| `aikos_voice.set_accept` | `accept` (bool) | Room: accept (play) the peer or not |
| `aikos_voice.allow_source` | `host`, `duration` | Plays a trusted sender for a while (e.g. a text-to-speech stream later) |
| `aikos_voice.set_mic_gain` | `gain` | 0.1..64 |

Conditions: `aikos_voice.is_talking`, `aikos_voice.in_conversation`, `aikos_voice.remote_holding`.

## Error cases

| Situation | What happens |
|---|---|
| Network not up yet | The UDP socket opens on its own once the network is connected; nothing is sent before that |
| `peer_host` / `host` / `transcriber` not a usable address | Warning in the log; the call is ignored (the transcriber copy is switched off) |
| A sender that doesn't hold (door) or isn't the peer / no accepted conversation (room) | Not played, counted in `held_back` |
| More than 0.3 s queued from a sender before its hold arrives (door) | The oldest frames fall out, counted in `held_back` |
| "Released" never arrives (door) | The door stops playing that key after `hold_max` |
| Audio arrives while this end talks | Not played (half-duplex) |
| `sendto` fails (peer gone, no route) | Counted in `tx_errors`; talking goes on |
| The main loop can't keep up with the mic | Samples are dropped; the RTP sequence shows a gap rather than spliced audio |
| Keepalives, comfort-noise packets, other payload types | Nothing to play; ignored |

## Built for what comes next

Sources and sinks, not hard wiring. The link takes samples from the mic (`push`), plays them to a sink (the speaker),
sends copies to a tap (the transcriber) and accepts **trusted sources** for a while (`allow_source`), e.g. a TTS stream
speaking to the visitor. A recorder ("leave a message") is another tap. The network sits behind `Transport`, so the
core runs on a PC for tests.

## Files

| File | |
|---|---|
| `voice_core.h` | The rules: pure C++17, no ESPHome, no sockets |
| `voice_udp.h` | The UDP transport (lwIP; BSD sockets in a host build) |
| `aikos_voice.h/.cpp`, `*.py` | The ESPHome component: mic, speaker, actions, sensors |

## Never without the tests

1. `esphome/tests/aikos_voice/voice_core_test.cpp`: 52 unit checks on a PC. CI runs them on every push and pull request:
   `g++ -std=c++17 -Wall -I esphome/components/aikos_voice esphome/tests/aikos_voice/voice_core_test.cpp -o t && ./t`
2. `esphome/tests/aikos_voice/voice_live_test.py`: 16 live checks against a door talk computer via Home Assistant. The PC
   plays a room key; configure it through the environment (see the file). The door config must count the two triggers in
   template sensors named "Conversations started" and "Conversations ended" (incremented in `on_conversation_start` /
   `on_conversation_end`), so the test can see them fire.

Both must pass before a tag. Devices pin a tag. Changes go through a pull request reviewed by the intercom and roomkey
maintainers (see [`CLAUDE.md`](../../../CLAUDE.md)).
