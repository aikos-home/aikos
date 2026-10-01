// aikos::voice (component aikos_voice): the voice link between the door and the RoomKeys (aikos vertraege.md §4), shared by both devices.
//
// Pure C++17, no ESPHome and no sockets in here: the network comes in through `Transport`, time as `now` arguments.
// That keeps the behaviour unit-testable on a PC (tests/voice_core_test.cpp) and leaves room for other sources
// and sinks later (a TTS stream, a recorder) without touching the rules.
//
// VOICE v1, frozen 2026-10-01 (tested live: door <-> RoomKey Desk, "hat ultra geklappt"):
//   wire       RTP v2, L16 big-endian, PT 96, 16 kHz mono, 20 ms (320 samples), UDP 5004, unicast
//   talk       push-to-talk on both ends, no answer, no hang-up; local "talk on" starts a fresh spurt (marker bit),
//              "talk off" drains what is buffered, then sends one comfort-noise packet (PT 13, 1 byte) = end of speech
//   copy       while talking, every packet also goes to the tap (the transcriber), unless the tap is the peer
//   duplex     half: nothing is played while this end talks
//   incoming   role DOOR: a peer is played ONLY while it holds its button (remote_hold, forwarded by HA); what it sent
//                         up to `prebuffer_ms` before that is played too (the HA hop), everything else is held back
//              role ROOM: the peer is played while a conversation is accepted (set_accept); the first sender in an
//                         accepted conversation becomes the peer if none is set (symmetric RTP)
//              any role:  a trusted source (allow_source, e.g. a TTS stream later) is played until its time runs out
//   end        the conversation ends after `idle_ms` without audio either way (peer forgotten, on_conversation_end)
//   keepalive  a 12-byte RTP header to peer and tap every `keepalive_ms` while idle, so lwIP keeps their MAC
//              (it forgets after 300 s and then loses the first ~0.25 s of speech, measured by the RoomKey thread)
//   latch      a new peer gets `latch_frames` silent 20 ms frames (0, +0.1 s, +0.4 s): ARP may eat the first one
#pragma once

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>

#include "dsp.h"    // Biquad, Limiter (v2: own header)
#include "types.h"  // Addr, Role (v2: own header)

namespace aikos {
namespace voice {

static constexpr int RATE = 16000;
static constexpr int FRAME = 320;  // 20 ms
static constexpr uint8_t PT_L16 = 96;
static constexpr uint8_t PT_CN = 13;

// The network, as seen by the link. The device uses UDP (voice_udp.h); tests use a fake.
class Transport {
 public:
  virtual ~Transport() = default;
  virtual bool send(const Addr &to, const uint8_t *data, size_t len) = 0;
  // one datagram into buf; returns its length, or <= 0 when nothing is waiting
  virtual int recv(uint8_t *buf, size_t cap, Addr &from) = 0;
};

struct Config {
  Role role = Role::DOOR;
  uint32_t idle_ms = 120000;       // conversation ends after this long without audio
  uint32_t prebuffer_ms = 300;     // DOOR: audio from a peer this long before its hold reaches us is played
  uint32_t hold_max_ms = 90000;    // DOOR: a lost "released" can't keep the door open longer
  int latch_frames = 3;            // silent frames to a new peer
  uint32_t keepalive_ms = 60000;   // 0 = off
};

struct Stats {
  uint32_t tx_packets = 0, rx_packets = 0, held_back = 0, tx_errors = 0, overruns = 0;
};

// The edges of a state such as "in conversation", for the start/end triggers of the ESPHome glue (one call per loop).
// Kept here so the unit tests cover it: 0.6.0 only fired the start edge (found by the RoomKey review, 2026-10-01).
struct Edge {
  bool state = false;
  int update(bool now) {  // +1 = it began, -1 = it ended, 0 = unchanged
    if (now == state)
      return 0;
    state = now;
    return now ? 1 : -1;
  }
};

class Link {
 public:
  using Sink = std::function<void(const int16_t *pcm, size_t n)>;

  void configure(const Config &c) { cfg_ = c; }
  const Config &config() const { return cfg_; }
  void set_transport(Transport *t) { net_ = t; }
  void set_sink(Sink s) { sink_ = std::move(s); }
  void set_ssrc(uint32_t ssrc, uint16_t seq, uint32_t ts) {
    ssrc_ = ssrc;
    seq_ = seq;
    ts_ = ts;
  }
  std::function<void()> on_conversation_end;

  // ── peer and tap ─────────────────────────────────────────────────────────────────────────────────────────────
  void set_peer(const Addr &a, uint32_t now) {
    if (!a.valid())
      return;
    const bool fresh = !has_peer_ || a != peer_;
    peer_ = a;
    has_peer_ = true;
    latched_ = false;
    last_audio_ms_ = now;
    if (fresh && cfg_.latch_frames > 0) {
      latch_left_ = cfg_.latch_frames;
      latch_t0_ = now;
      send_latch_();
    } else if (fresh) {
      keepalive_due_ = true;  // resolve the new peer's MAC now, not with the first words
    }
  }
  void clear_peer() {
    if (closing_) {  // still draining the last words: forget the peer after them
      clear_after_drain_ = true;
      return;
    }
    has_peer_ = latched_ = false;
    latch_left_ = 0;
  }
  bool has_peer() const { return has_peer_; }
  Addr peer() const { return peer_; }
  void set_tap(const Addr &a) {  // invalid = off
    if (a.valid() && a != tap_)
      keepalive_due_ = true;  // resolve its MAC now
    tap_ = a;
  }

  // ── local push-to-talk ───────────────────────────────────────────────────────────────────────────────────────
  void talk(bool on, uint32_t now) {
    if (on) {
      tail_.store(head_.load(std::memory_order_acquire));  // stale samples out: a fresh start
      closing_ = false;
      first_ = true;
      tx_ = true;
      last_audio_ms_ = now;
    } else if (tx_) {
      closing_ = true;  // loop() sends what is buffered, then the end packet
    }
  }
  bool talking() const { return tx_ && !closing_; }

  // producer, called from the microphone task: 16-bit samples (filtered and limited by the caller)
  void push(const int16_t *s, size_t n) {
    if (!tx_ || closing_)
      return;
    for (size_t i = 0; i < n; i++)
      put_(s[i]);
  }

  // ── incoming policy ──────────────────────────────────────────────────────────────────────────────────────────
  // DOOR: HA forwards a key's talk_start / talk_stop with its address. The first hold makes it the peer.
  void remote_hold(bool held, const Addr &key, uint32_t now) {
    if (held) {
      if (key.valid() && (!has_peer_ || key.ip != peer_.ip))  // a key is its address; a port set before stays
        set_peer(key, now);
      if (!has_peer_)
        return;
      remote_held_ = true;
      hold_ms_ = now;
      last_audio_ms_ = now;
      for (int k = 0; k < pre_count_; k++) {  // what it sent just before its hold reached us, nothing older
        const int i = (pre_head_ - pre_count_ + k + PRE) % PRE;
        if (pre_[i].from.ip == peer_.ip && now - pre_[i].ms <= cfg_.prebuffer_ms)
          play_(pre_[i].pcm, pre_[i].n);
        else
          stats.held_back++;
      }
    } else {
      remote_held_ = false;
      for (int k = 0; k < pre_count_; k++)
        stats.held_back++;
      last_audio_ms_ = now;
    }
    pre_count_ = 0;
  }
  bool remote_holding() const { return remote_held_; }
  // ROOM: audio in only during a conversation the RoomKey accepted
  void set_accept(bool on) {
    if (accept_ && !on && latched_)
      clear_peer();
    accept_ = on;
  }
  // any role: a trusted source (e.g. a TTS stream) is played until `until_ms`
  void allow_source(const Addr &a, uint32_t until_ms) {
    trusted_ = a;
    trusted_until_ = until_ms;
  }

  bool in_conversation() const { return has_peer_; }

  // ── main loop ────────────────────────────────────────────────────────────────────────────────────────────────
  void loop(uint32_t now) {
    if (net_ == nullptr)
      return;
    // samples the mic task had to drop: skip their sequence numbers (a gap, not spliced audio)
    const uint32_t dropped = dropped_.exchange(0);
    if (dropped >= (uint32_t) FRAME) {
      seq_ += dropped / FRAME;
      ts_ += (dropped / FRAME) * FRAME;
      stats.overruns++;
    }
    // transmit
    while (tx_ && (has_peer_ || tap_.valid()) && avail_() >= (uint32_t) FRAME) {
      int16_t pcm[FRAME];
      for (int i = 0; i < FRAME; i++)
        pcm[i] = get_();
      send_l16_(pcm, FRAME, first_);
      first_ = false;
      last_audio_ms_ = now;
    }
    if (closing_ && (avail_() < (uint32_t) FRAME || !(has_peer_ || tap_.valid()))) {
      const uint32_t rest = avail_();  // the last few samples of the last word
      if (rest > 0 && (has_peer_ || tap_.valid())) {
        int16_t pcm[FRAME];
        for (uint32_t i = 0; i < rest; i++)
          pcm[i] = get_();
        send_l16_(pcm, (int) rest, first_);
      }
      send_cn_();
      tx_ = closing_ = false;
      if (clear_after_drain_) {
        has_peer_ = latched_ = clear_after_drain_ = false;
        latch_left_ = 0;
      }
      last_audio_ms_ = now;
    }
    // latch frames 2 and 3 (+0.1 s, +0.4 s)
    if (latch_left_ > 0 && has_peer_) {
      const int sent = cfg_.latch_frames - latch_left_;
      const uint32_t due = sent == 1 ? 100u : 400u;
      if (now - latch_t0_ >= due)
        send_latch_();
    }
    // keepalive while idle
    if (!tx_ && (has_peer_ || tap_.valid()) &&
        (keepalive_due_ || (cfg_.keepalive_ms > 0 && now - keepalive_ms_ >= cfg_.keepalive_ms)))
      send_keepalive_(now);
    // receive
    for (int guard = 0; guard < 16; guard++) {
      uint8_t buf[1500];
      Addr from;
      const int n = net_->recv(buf, sizeof buf, from);
      if (n <= 0)
        break;
      receive_(buf, n, from, now);
    }
    // safety: a lost "released" can't keep the door open
    if (remote_held_ && now - hold_ms_ > cfg_.hold_max_ms)
      remote_hold(false, Addr{}, now);
    // the conversation ends after idle_ms without audio either way
    if (has_peer_ && !tx_ && !remote_held_ && now - last_audio_ms_ > cfg_.idle_ms) {
      has_peer_ = latched_ = false;
      latch_left_ = 0;
      if (on_conversation_end)
        on_conversation_end();
    }
  }

  Stats stats;

 protected:
  struct Pre {
    int16_t pcm[FRAME];
    int n = 0;
    uint32_t ms = 0;
    Addr from;
  };
  static constexpr int PRE = 25;          // room for 0.5 s
  static constexpr uint32_t RING = 8192;  // 512 ms between the mic task and the main loop

  void receive_(const uint8_t *buf, int n, const Addr &from, uint32_t now) {
    if (n <= 12 || (buf[0] >> 6) != 2)
      return;  // keepalive or not RTP v2
    if ((buf[1] & 0x7F) != PT_L16)
      return;  // comfort noise and anything else: nothing to play
    const int hdr = 12 + 4 * (buf[0] & 0x0F);
    if (n <= hdr)
      return;
    const int count = std::min((n - hdr) / 2, FRAME * 2);
    int16_t pcm[FRAME * 2];
    for (int i = 0; i < count; i++)
      pcm[i] = (int16_t) ((buf[hdr + 2 * i] << 8) | buf[hdr + 2 * i + 1]);

    if (trusted_.valid() && from.ip == trusted_.ip && (int32_t) (trusted_until_ - now) > 0) {
      if (!talking())
        play_(pcm, count);
      stats.rx_packets++;
      return;
    }
    if (tx_)
      return;  // half-duplex: this end talks
    if (cfg_.role == Role::ROOM) {
      if (!accept_) {
        stats.held_back++;  // no conversation: dropped unheard
        return;
      }
      if (!has_peer_) {  // symmetric RTP: answer whoever talks to us
        peer_ = from;
        has_peer_ = latched_ = true;
      }
      if (from.ip != peer_.ip) {
        stats.held_back++;
        return;
      }
      play_(pcm, count);
      stats.rx_packets++;
      last_audio_ms_ = now;
      return;
    }
    // DOOR
    if (has_peer_ && remote_held_ && from.ip == peer_.ip) {
      play_(pcm, std::min(count, FRAME));
      stats.rx_packets++;
      last_audio_ms_ = now;
      return;
    }
    Pre &p = pre_[pre_head_];  // nobody holds for this sender: keep it briefly, unheard
    p.n = std::min(count, FRAME);
    memcpy(p.pcm, pcm, (size_t) p.n * 2);
    p.ms = now;
    p.from = from;
    pre_head_ = (pre_head_ + 1) % PRE;
    if (pre_count_ < PRE)
      pre_count_++;
    else
      stats.held_back++;  // the oldest frame falls out, never played
  }

  void play_(const int16_t *pcm, int n) {
    if (sink_)
      sink_(pcm, (size_t) n);
  }

  void header_(uint8_t *p, uint8_t pt, bool marker) const {
    p[0] = 0x80;
    p[1] = (uint8_t) ((marker ? 0x80 : 0) | pt);
    p[2] = (uint8_t) (seq_ >> 8);
    p[3] = (uint8_t) seq_;
    p[4] = (uint8_t) (ts_ >> 24);
    p[5] = (uint8_t) (ts_ >> 16);
    p[6] = (uint8_t) (ts_ >> 8);
    p[7] = (uint8_t) ts_;
    p[8] = (uint8_t) (ssrc_ >> 24);
    p[9] = (uint8_t) (ssrc_ >> 16);
    p[10] = (uint8_t) (ssrc_ >> 8);
    p[11] = (uint8_t) ssrc_;
  }
  void deliver_(const uint8_t *pkt, size_t len, bool to_peer, bool to_tap) {
    if (to_peer && has_peer_ && !net_->send(peer_, pkt, len))
      stats.tx_errors++;
    if (to_tap && tap_.valid() && !(has_peer_ && to_peer && tap_ == peer_) && !net_->send(tap_, pkt, len))
      stats.tx_errors++;
  }
  void send_l16_(const int16_t *pcm, int n, bool marker) {
    uint8_t pkt[12 + FRAME * 2];
    header_(pkt, PT_L16, marker);
    for (int i = 0; i < n; i++) {
      pkt[12 + 2 * i] = (uint8_t) ((uint16_t) pcm[i] >> 8);
      pkt[13 + 2 * i] = (uint8_t) ((uint16_t) pcm[i] & 0xFF);
    }
    deliver_(pkt, 12 + 2 * (size_t) n, true, true);
    seq_++;
    ts_ += (uint32_t) n;
    stats.tx_packets++;
  }
  void send_cn_() {
    uint8_t pkt[13];
    header_(pkt, PT_CN, false);
    pkt[12] = 127;
    deliver_(pkt, sizeof pkt, true, true);
    seq_++;
  }
  void send_latch_() {
    uint8_t pkt[12 + FRAME * 2] = {0};
    header_(pkt, PT_L16, latch_left_ == cfg_.latch_frames);
    deliver_(pkt, sizeof pkt, true, false);
    seq_++;
    ts_ += FRAME;
    stats.tx_packets++;
    latch_left_--;
  }
  void send_keepalive_(uint32_t now) {
    uint8_t pkt[12];
    header_(pkt, PT_L16, false);
    if (has_peer_)
      net_->send(peer_, pkt, sizeof pkt);
    if (tap_.valid() && !(has_peer_ && tap_ == peer_))
      net_->send(tap_, pkt, sizeof pkt);
    keepalive_ms_ = now;
    keepalive_due_ = false;
  }

  void put_(int16_t v) {
    const uint32_t h = head_.load(std::memory_order_relaxed);
    if (h - tail_.load(std::memory_order_acquire) >= RING) {
      dropped_.fetch_add(1, std::memory_order_relaxed);
      return;
    }
    ring_[h % RING] = v;
    head_.store(h + 1, std::memory_order_release);
  }
  int16_t get_() {
    const uint32_t t = tail_.load(std::memory_order_relaxed);
    const int16_t v = ring_[t % RING];
    tail_.store(t + 1, std::memory_order_release);
    return v;
  }
  uint32_t avail_() const { return head_.load(std::memory_order_acquire) - tail_.load(std::memory_order_relaxed); }

  Config cfg_;
  Transport *net_ = nullptr;
  Sink sink_;
  Addr peer_, tap_, trusted_;
  uint32_t trusted_until_ = 0;
  bool has_peer_ = false, latched_ = false, accept_ = false, first_ = true, clear_after_drain_ = false;
  volatile bool tx_ = false, closing_ = false;
  bool remote_held_ = false, keepalive_due_ = false;
  uint32_t hold_ms_ = 0, last_audio_ms_ = 0, keepalive_ms_ = 0, latch_t0_ = 0;
  int latch_left_ = 0;
  uint16_t seq_ = 0;
  uint32_t ts_ = 0, ssrc_ = 0x61697673;  // "aivs"
  Pre pre_[PRE];
  int pre_head_ = 0, pre_count_ = 0;
  int16_t ring_[RING];
  std::atomic<uint32_t> head_{0}, tail_{0}, dropped_{0};
};

}  // namespace voice
}  // namespace aikos
