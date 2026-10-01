// aikos::voice: the call ("Telefonat") of voice v2 (aikos features/sprechen.md, R17) as a pure state machine:
// events in, "who hears what" out. No audio, no network, no ESPHome: the device glue feeds what it knows (buttons,
// the door screen's "Sprechen", speech found by a level detector, the front door) and asks the routes before it moves
// audio. Case 1 (it rang) and case 2 (nobody rang) differ ONLY in what starts the call (R17.11).
//
//   DoorCall  the call as the door owns it: the door is the arbiter (start, floor, end)
//   KeyCall   what one room key does in the door's call (its button, its settings, its own end rules)
//
// Rules:
//   start     case 1: after a ring, the visitor presses "Sprechen" once, or a key holds its button
//             case 2: a key holds its button without a ring
//   door mic  open for the whole call, closed outside it (R17.2). Towards the keys it is muted while the door speaker
//             plays and `mute_tail_ms` after (R17.16, echo); the copy to the transcriber is never muted
//   key mic   open only while its button is held (R17.3)
//   door spk  plays the key that has the floor, only while it holds (the lock of v1). The first key to hold has the
//             floor; another key that holds meanwhile is busy ("besetzt") and not played; it gets the floor if it still
//             holds when the first lets go. Every key that answered is in the call (R17.14)
//   key spk   plays the door only while that key does NOT hold (R17.4), and only if it is in the call (it answered) or
//             its owner wants to hear visitors before answering (per-key setting with times, R17.13; the key's quiet
//             hours decide that setting, R17.15)
//   end       no speech on either side for `silence_end_ms` (R17.8; a held button counts as speech), `max_length_ms`
//             (safety against noise that looks like speech), from outside (front door, API), or every key that
//             answered has left. A key leaves on its own silence or max length, or when the front door opens and
//             its owner switched that on (R17.8)
//   holds     keys resend "holds" every second; none for `hold_refresh_ms` = released (lost packets, crashed key).
//             A button still held when a call ends starts no new call until it is pressed again.
#pragma once

#include <cstdint>

#include "types.h"

namespace aikos {
namespace voice {

struct CallConfig {
  uint32_t silence_end_ms = 10000;   // R17.8, a number entity on every device (`call_silence_end`)
  uint32_t max_length_ms = 300000;   // safety (`call_max_length`)
  uint32_t hold_refresh_ms = 3000;   // "holds" and the door's "call on" are resent every second
  uint32_t mute_tail_ms = 300;       // R17.16: the room's last words still ring in the door's front plate
  uint32_t ring_window_ms = 120000;  // a key that holds this soon after a ring answers that ring (case 1)
};

enum class CallStart : uint8_t { NONE, VISITOR, KEY_AFTER_RING, KEY_WITHOUT_RING };
enum class CallEnd : uint8_t { NONE, SILENCE, MAX_LENGTH, FRONT_DOOR, EXTERNAL, EVERYONE_LEFT, DOOR_ENDED };

inline const char *to_string(CallStart s) {
  switch (s) {
    case CallStart::VISITOR:
      return "visitor pressed Sprechen";
    case CallStart::KEY_AFTER_RING:
      return "a key answered the ring";
    case CallStart::KEY_WITHOUT_RING:
      return "a key without a ring";
    default:
      return "-";
  }
}
inline const char *to_string(CallEnd e) {
  switch (e) {
    case CallEnd::SILENCE:
      return "silence";
    case CallEnd::MAX_LENGTH:
      return "max length";
    case CallEnd::FRONT_DOOR:
      return "front door opened";
    case CallEnd::EXTERNAL:
      return "ended from outside";
    case CallEnd::EVERYONE_LEFT:
      return "every key left";
    case CallEnd::DOOR_ENDED:
      return "the door ended the call";
    default:
      return "-";
  }
}

// ───────────────────────────────────────────────────────────────────────────────────────────────── the door
class DoorCall {
 public:
  static constexpr int MAX_KEYS = 8;

  void configure(const CallConfig &c) { cfg_ = c; }
  const CallConfig &config() const { return cfg_; }

  // ── events ──
  void ring(uint32_t now) {
    rang_ = true;
    ring_ms_ = now;
  }
  // the door screen's one-time "Sprechen" (case 1); the screen only offers it after a ring
  void visitor_speak(uint32_t now) {
    if (!active_)
      start_(CallStart::VISITOR, now);
    last_speech_ms_ = now;
  }
  // a key's button, sent by the key itself every second while held, and once on release
  void hold(const Addr &key, bool held, uint32_t now) {
    Slot *s = slot_(key, held);
    if (s == nullptr)
      return;
    if (!held) {
      release_(*s, now);
      return;
    }
    s->hold_ms = now;
    if (s->held) {  // a refresh
      if (!s->stale && active_)
        last_speech_ms_ = now;
      return;
    }
    s->held = true;  // a fresh press
    s->stale = false;
    s->since = ++order_;
    if (!active_)
      start_(ringing(now) ? CallStart::KEY_AFTER_RING : CallStart::KEY_WITHOUT_RING, now);
    s->in_call = true;  // holding = answering: the key is in the call (R17.14)
    had_member_ = true;
    if (floor_ < 0)
      floor_ = index_(s);
    last_speech_ms_ = now;
  }
  // a key's own "I'm in the call" (it went off: the key left by its own rules)
  void key_in_call(const Addr &key, bool in, uint32_t now) {
    Slot *s = slot_(key, in);
    if (s == nullptr)
      return;
    if (in) {
      if (active_ && !s->stale) {
        s->in_call = true;
        had_member_ = true;
      }
      return;
    }
    if (!s->in_call)
      return;
    s->in_call = false;
    if (s->held)
      release_(*s, now);
    if (active_ && had_member_ && members() == 0)
      end_(CallEnd::EVERYONE_LEFT);
  }
  // speech found at that end (door mic level detector; for the room end the glue may also report a key's audio)
  void speech(Role side, uint32_t now) {
    (void) side;  // both ends count the same (R17.8)
    if (active_)
      last_speech_ms_ = now;
  }
  // the door speaker just played room audio: the door mic stays muted towards the keys a little longer
  void door_played(uint32_t now) {
    played_ = true;
    played_ms_ = now;
  }
  void end(CallEnd why, uint32_t now) {
    (void) now;
    if (active_)
      end_(why);
  }
  void loop(uint32_t now) {
    for (Slot &s : slots_)
      if (s.used && s.held && now - s.hold_ms > cfg_.hold_refresh_ms)
        release_(s, now);  // its "holds" stopped coming
    if (!active_)
      return;
    if (now - start_ms_ >= cfg_.max_length_ms)
      end_(CallEnd::MAX_LENGTH);
    else if (!anyone_holds_() && now - last_speech_ms_ >= cfg_.silence_end_ms)
      end_(CallEnd::SILENCE);
  }

  // ── state ──
  bool active() const { return active_; }
  uint32_t id() const { return id_; }  // 1, 2, ... one per call; 0 before the first
  CallStart started_by() const { return started_by_; }
  CallEnd ended_by() const { return ended_by_; }
  bool ringing(uint32_t now) const { return rang_ && now - ring_ms_ < cfg_.ring_window_ms; }
  int members() const {
    int n = 0;
    for (const Slot &s : slots_)
      n += s.used && s.in_call;
    return n;
  }
  bool member(const Addr &key) const {
    const Slot *s = find_(key);
    return s != nullptr && s->in_call;
  }
  bool holds(const Addr &key) const {
    const Slot *s = find_(key);
    return s != nullptr && s->held && !s->stale;
  }
  // the key that has the floor, or nullptr
  const Addr *floor() const { return floor_ >= 0 ? &slots_[floor_].addr : nullptr; }
  // the key holds, but another one has the floor ("besetzt")
  bool busy(const Addr &key) const {
    const Slot *s = find_(key);
    return s != nullptr && s->held && !s->stale && floor_ >= 0 && &slots_[floor_] != s;
  }

  // ── who hears what (the door end) ──
  bool mic_open() const { return active_; }  // R17.2: the whole call, also before anyone answered (R17.13)
  bool mic_to_keys(uint32_t now) const {     // R17.16: not while the door speaker plays, plus the tail
    return active_ && !(played_ && now - played_ms_ < cfg_.mute_tail_ms);
  }
  bool plays(const Addr &from) const {  // the door speaker plays this sender now
    return active_ && floor_ >= 0 && slots_[floor_].addr.ip == from.ip;
  }

 protected:
  struct Slot {
    Addr addr;
    bool used = false, held = false, stale = false, in_call = false;
    uint32_t hold_ms = 0;  // last "holds"
    uint32_t since = 0;    // order of the press, for the floor
  };

  void start_(CallStart how, uint32_t now) {
    active_ = true;
    id_++;
    started_by_ = how;
    ended_by_ = CallEnd::NONE;
    start_ms_ = last_speech_ms_ = now;
    had_member_ = false;
    rang_ = false;  // the ring is answered
    played_ = false;
    floor_ = -1;
  }
  void end_(CallEnd why) {
    active_ = false;
    ended_by_ = why;
    floor_ = -1;
    had_member_ = false;
    played_ = false;
    for (Slot &s : slots_) {
      s.in_call = false;
      if (s.held)
        s.stale = true;  // still held: no new call until it is pressed again
    }
  }
  void release_(Slot &s, uint32_t now) {
    const bool counted = s.held && !s.stale;
    s.held = s.stale = false;
    if (floor_ >= 0 && &slots_[floor_] == &s)
      floor_ = next_floor_();
    if (counted && active_)
      last_speech_ms_ = now;  // silence counts from the end of the last words
  }
  int next_floor_() const {  // the key that has held the longest and is still holding
    int best = -1;
    for (int i = 0; i < MAX_KEYS; i++) {
      const Slot &s = slots_[i];
      if (s.used && s.held && !s.stale && s.in_call && (best < 0 || s.since < slots_[best].since))
        best = i;
    }
    return best;
  }
  bool anyone_holds_() const {
    for (const Slot &s : slots_)
      if (s.used && s.held && !s.stale)
        return true;
    return false;
  }
  const Slot *find_(const Addr &key) const {
    for (const Slot &s : slots_)
      if (s.used && s.addr.ip == key.ip)
        return &s;
    return nullptr;
  }
  Slot *slot_(const Addr &key, bool add) {
    for (Slot &s : slots_)
      if (s.used && s.addr.ip == key.ip)
        return &s;
    if (!add || key.ip == 0)
      return nullptr;
    for (Slot &s : slots_)
      if (!s.used || (!s.held && !s.in_call)) {  // a free slot, or one of a key that isn't doing anything
        s = Slot{};
        s.used = true;
        s.addr = key;
        return &s;
      }
    return nullptr;  // more than MAX_KEYS keys at once: ignored
  }
  int index_(const Slot *s) const { return (int) (s - slots_); }

  CallConfig cfg_;
  Slot slots_[MAX_KEYS];
  bool active_ = false, rang_ = false, had_member_ = false, played_ = false;
  uint32_t id_ = 0, order_ = 0, ring_ms_ = 0, start_ms_ = 0, last_speech_ms_ = 0, played_ms_ = 0;
  int floor_ = -1;
  CallStart started_by_ = CallStart::NONE;
  CallEnd ended_by_ = CallEnd::NONE;
};

// ───────────────────────────────────────────────────────────────────────────────────────────────── a room key
// The door announces its call with its id (every second while on, once when it ends). A key is in the call it
// answered; a press while the door has no call starts one (case 2) and the key joins the id the door announces next.
// Leaving (front door, own silence) holds for that call id: the next refresh of the same call doesn't bring it back.
class KeyCall {
 public:
  void configure(const CallConfig &c) { cfg_ = c; }

  // ── events ──
  void hold(bool held, uint32_t now) {  // this key's own button
    if (!held) {
      if (held_ && !stale_)
        last_speech_ms_ = now;
      held_ = stale_ = false;
      return;
    }
    if (held_)
      return;
    held_ = true;
    stale_ = false;
    if (!in_call()) {  // answering (case 1) or starting a call (case 2)
      if (door_on_)
        member_id_ = door_id_;
      else
        pending_ = true;
      joined_ms_ = now;
      left_by_ = CallEnd::NONE;
    }
    left_id_ = 0;  // pressing again overrides having left
    last_speech_ms_ = now;
  }
  void door_call(bool on, uint32_t id, uint32_t now) {
    if (!on) {
      leave_(CallEnd::DOOR_ENDED);
      door_on_ = false;
      return;
    }
    door_ms_ = now;
    if (door_on_ && id == door_id_)
      return;  // a refresh
    door_on_ = true;  // a new call at the door
    door_id_ = id;
    if (pending_) {  // this key started it
      member_id_ = id;
      pending_ = false;
    }
    last_speech_ms_ = now;
  }
  // the door says another key has the floor
  void floor_taken(bool by_other) { floor_taken_ = by_other; }
  void speech(Role side, uint32_t now) {
    (void) side;
    last_speech_ms_ = now;
  }
  // the front door opened; the glue calls this only if this key's "front door ends the call" switch is on (R17.8)
  void front_door(uint32_t now) {
    (void) now;
    leave_(CallEnd::FRONT_DOOR);
  }
  void loop(uint32_t now) {
    if (door_on_ && now - door_ms_ > cfg_.hold_refresh_ms) {  // the door's "call on" stopped coming
      leave_(CallEnd::DOOR_ENDED);
      door_on_ = false;
    }
    if (!in_call())
      return;
    if (now - joined_ms_ >= cfg_.max_length_ms)
      leave_(CallEnd::MAX_LENGTH);
    else if (!mic_open() && now - last_speech_ms_ >= cfg_.silence_end_ms)
      leave_(CallEnd::SILENCE);
  }

  // ── state ──
  bool in_call() const { return pending_ || (member_id_ != 0 && door_on_ && member_id_ == door_id_); }  // → the door
  bool door_on() const { return door_on_; }
  uint32_t door_id() const { return door_id_; }
  CallEnd left_by() const { return left_by_; }

  // ── who hears what (one room key) ──
  bool mic_open() const { return held_ && !stale_; }  // R17.3: only while held, at once off on release
  bool busy() const { return mic_open() && floor_taken_; }
  // R17.4: never while this key holds; R17.13: before answering only if its owner wants that (setting + times)
  bool plays_door(bool hear_visitor_before_answer) const {
    return door_on_ && !held_ && (in_call() || (hear_visitor_before_answer && left_id_ != door_id_));
  }

 protected:
  void leave_(CallEnd why) {
    if (in_call())
      left_by_ = why;
    if (door_on_)
      left_id_ = door_id_;
    member_id_ = 0;
    pending_ = false;
    if (held_)
      stale_ = true;  // a held button doesn't keep talking into an ended call
  }

  CallConfig cfg_;
  bool held_ = false, stale_ = false, pending_ = false, door_on_ = false, floor_taken_ = false;
  uint32_t door_id_ = 0, member_id_ = 0, left_id_ = 0;
  uint32_t joined_ms_ = 0, last_speech_ms_ = 0, door_ms_ = 0;
  CallEnd left_by_ = CallEnd::NONE;
};

}  // namespace voice
}  // namespace aikos
