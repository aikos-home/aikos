// aikos::voice (component aikos_voice): the audio link between the door and the room keys, shared by both devices.
//
// Pure C++17, no ESPHome and no sockets in here: the network comes in through `Transport`, time as `now` arguments.
// That keeps the behaviour unit-testable on a PC (tests/voice_core_test.cpp).
//
// VOICE v2: the link only MOVES audio. Who hears what is decided by the call model (call.h); the device glue tells the
// link where to send (targets, gate) and the link asks a policy before it plays a sender.
//   wire       RTP v2, L16 big-endian, PT 96, 16 kHz mono, 20 ms (320 samples), UDP 5004, unicast (as in v1)
//   talk       "talk on" starts a fresh spurt (marker bit); "talk off" drains what is buffered, then sends one
//              comfort-noise packet (PT 13, 1 byte) = end of speech
//   targets    up to MAX_TARGETS (door: every key during a call; key: the door). A new target gets `latch_frames`
//              silent frames (0, +0.1 s, +0.4 s): ARP may eat the first one
//   gate       `send_to_targets(false)` keeps frames from the targets but not from the tap (door: muted towards the keys
//              while its speaker plays; key: a test recording that must never reach the door)
//   tap        the transcriber copy of everything this end says, not twice if the tap is also a target
//   incoming   a policy decides per sender: PLAY, HOLD (kept up to `prebuffer_ms`, played by flush(from) when the
//              sender may be heard, e.g. its "holds" arrived a little after its first words) or DROP (counted as held
//              back); a trusted source (allow_source, e.g. a TTS stream later) is played while its time lasts
//   keepalive  a 12-byte RTP header to every target and the tap every `keepalive_ms` while not talking, so lwIP keeps
//              their MAC (it forgets after 300 s and then loses the first ~0.25 s of speech, measured by the RoomKey)
#pragma once

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>

#include "dsp.h"    // Biquad, Limiter
#include "types.h"  // Addr, Role

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

struct LinkConfig {
  uint32_t prebuffer_ms = 300;    // HOLD: audio from a sender this long before it may be heard is still played
  int latch_frames = 3;           // silent frames to a new target
  uint32_t keepalive_ms = 60000;  // 0 = off
};

struct Stats {
  uint32_t tx_packets = 0, rx_packets = 0, held_back = 0, tx_errors = 0, overruns = 0;
};

enum class Verdict : uint8_t { PLAY, HOLD, DROP };

// The edges of a state such as "in a call", for the start/end triggers of the ESPHome glue (one call per loop).
// Kept here so the unit tests cover it: v1 0.6.0 only fired the start edge (found by the RoomKey review, 2026-10-01).
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
  static constexpr int MAX_TARGETS = 8;
  using Sink = std::function<void(const int16_t *pcm, size_t n)>;
  using Policy = std::function<Verdict(const Addr &from, uint32_t now)>;

  void configure(const LinkConfig &c) { cfg_ = c; }
  const LinkConfig &config() const { return cfg_; }
  void set_transport(Transport *t) { net_ = t; }
  void set_sink(Sink s) { sink_ = std::move(s); }
  void set_policy(Policy p) { policy_ = std::move(p); }
  void set_ssrc(uint32_t ssrc, uint16_t seq, uint32_t ts) {
    ssrc_ = ssrc;
    seq_ = seq;
    ts_ = ts;
  }

  // ── where this end's audio goes ──────────────────────────────────────────────────────────────────────────────
  // The full list each time; targets that are new get latch frames, the others keep their state.
  void set_targets(const Addr *list, int n, uint32_t now) {
    Target next[MAX_TARGETS];
    int count = 0;
    for (int i = 0; i < n && count < MAX_TARGETS; i++) {
      if (!list[i].valid())
        continue;
      bool dup = false;
      for (int j = 0; j < count; j++)
        dup |= next[j].addr == list[i];
      if (dup)
        continue;
      Target t;
      t.addr = list[i];
      const Target *old = find_(list[i]);
      if (old != nullptr) {
        t = *old;
      } else if (cfg_.latch_frames > 0) {
        t.latch_left = cfg_.latch_frames;
        t.latch_t0 = now;
      } else {
        keepalive_due_ = true;  // resolve the new target's MAC now, not with the first words
      }
      next[count++] = t;
    }
    for (int i = 0; i < count; i++)
      targets_[i] = next[i];
    n_targets_ = count;
    for (int i = 0; i < n_targets_; i++)
      if (targets_[i].latch_left == cfg_.latch_frames && cfg_.latch_frames > 0)
        send_latch_(targets_[i]);  // the first latch frame at once
  }
  void set_target(const Addr &a, uint32_t now) { set_targets(&a, a.valid() ? 1 : 0, now); }
  void clear_targets() { n_targets_ = 0; }
  int targets() const { return n_targets_; }
  bool has_target(const Addr &a) const { return find_(a) != nullptr; }
  void set_tap(const Addr &a) {  // invalid = off
    if (a.valid() && a != tap_)
      keepalive_due_ = true;  // resolve its MAC now
    tap_ = a;
  }
  void send_to_targets(bool on) { gate_ = on; }
  bool sending_to_targets() const { return gate_; }

  // ── this end talks ───────────────────────────────────────────────────────────────────────────────────────────
  void talk(bool on, uint32_t now) {
    (void) now;
    if (on) {
      tail_.store(head_.load(std::memory_order_acquire));  // stale samples out: a fresh start
      closing_.store(false);
      first_ = true;
      tx_.store(true);
    } else if (tx_.load()) {
      closing_.store(true);  // loop() sends what is buffered, then the end packet
    }
  }
  bool talking() const { return tx_.load() && !closing_.load(); }

  // producer, called from the microphone task: 16-bit samples (filtered and limited by the caller)
  void push(const int16_t *s, size_t n) {
    if (!tx_.load() || closing_.load())
      return;
    for (size_t i = 0; i < n; i++)
      put_(s[i]);
  }

  // ── incoming ─────────────────────────────────────────────────────────────────────────────────────────────────
  // play what `from` sent up to `prebuffer_ms` ago and the policy held back; everything older is dropped
  void flush(const Addr &from, uint32_t now) {
    int kept = 0;
    for (int k = 0; k < pre_count_; k++) {
      Pre &p = pre_[(pre_head_ - pre_count_ + k + PRE) % PRE];
      if (p.from.ip == from.ip) {
        if (now - p.ms <= cfg_.prebuffer_ms) {
          play_(p.pcm, p.n);
          stats.rx_packets++;
        } else {
          stats.held_back++;
        }
        continue;
      }
      pre_[(pre_head_ - pre_count_ + kept + PRE) % PRE] = p;  // keep the other senders' frames, in order
      kept++;
    }
    pre_head_ = (pre_head_ - pre_count_ + kept + PRE) % PRE;
    pre_count_ = kept;
  }
  // any role: a trusted source (e.g. a TTS stream) is played until `until_ms`
  void allow_source(const Addr &a, uint32_t until_ms) {
    trusted_ = a;
    trusted_until_ = until_ms;
  }

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
    const bool anywhere = n_targets_ > 0 || tap_.valid();
    // transmit
    while (tx_.load() && anywhere && avail_() >= (uint32_t) FRAME) {
      int16_t pcm[FRAME];
      for (int i = 0; i < FRAME; i++)
        pcm[i] = get_();
      send_l16_(pcm, FRAME, first_);
      first_ = false;
    }
    if (closing_.load() && (avail_() < (uint32_t) FRAME || !anywhere)) {
      const uint32_t rest = avail_();  // the last few samples of the last word
      if (rest > 0 && anywhere) {
        int16_t pcm[FRAME];
        for (uint32_t i = 0; i < rest; i++)
          pcm[i] = get_();
        send_l16_(pcm, (int) rest, first_);
      }
      send_cn_();
      tx_.store(false);
      closing_.store(false);
    }
    // latch frames 2 and 3 (+0.1 s, +0.4 s)
    for (int i = 0; i < n_targets_; i++) {
      Target &t = targets_[i];
      if (t.latch_left > 0) {
        const int sent = cfg_.latch_frames - t.latch_left;
        const uint32_t due = sent == 1 ? 100u : 400u;
        if (now - t.latch_t0 >= due)
          send_latch_(t);
      }
    }
    // keepalive while not talking
    if (!tx_.load() && anywhere &&
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
  }

  Stats stats;

 protected:
  struct Target {
    Addr addr;
    int latch_left = 0;
    uint32_t latch_t0 = 0;
  };
  struct Pre {
    int16_t pcm[FRAME];
    int n = 0;
    uint32_t ms = 0;
    Addr from;
  };
  static constexpr int PRE = 25;          // room for 0.5 s
  static constexpr uint32_t RING = 8192;  // 512 ms between the mic task and the main loop

  const Target *find_(const Addr &a) const {
    for (int i = 0; i < n_targets_; i++)
      if (targets_[i].addr == a)
        return &targets_[i];
    return nullptr;
  }

  void receive_(const uint8_t *buf, int n, const Addr &from, uint32_t now) {
    if (n <= 12 || (buf[0] >> 6) != 2)
      return;  // keepalive or not RTP v2
    if ((buf[1] & 0x7F) != PT_L16)
      return;  // comfort noise and anything else: nothing to play
    const int hdr = 12 + 4 * (buf[0] & 0x0F);
    if (n <= hdr)
      return;
    const int count = std::min((n - hdr) / 2, FRAME);
    int16_t pcm[FRAME];
    for (int i = 0; i < count; i++)
      pcm[i] = (int16_t) ((buf[hdr + 2 * i] << 8) | buf[hdr + 2 * i + 1]);

    if (trusted_.valid() && from.ip == trusted_.ip && (int32_t) (trusted_until_ - now) > 0) {
      play_(pcm, count);
      stats.rx_packets++;
      return;
    }
    const Verdict v = policy_ ? policy_(from, now) : Verdict::DROP;
    if (v == Verdict::PLAY) {
      play_(pcm, count);
      stats.rx_packets++;
      return;
    }
    if (v == Verdict::DROP) {
      stats.held_back++;
      return;
    }
    Pre &p = pre_[pre_head_];  // HOLD: keep it briefly, unheard
    p.n = count;
    memcpy(p.pcm, pcm, (size_t) count * 2);
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
  // to the targets (if the gate is open) and the tap (once, even if it is also a target)
  void deliver_(const uint8_t *pkt, size_t len, bool gated) {
    bool tap_done = false;
    if (!gated || gate_) {
      for (int i = 0; i < n_targets_; i++) {
        if (!net_->send(targets_[i].addr, pkt, len))
          stats.tx_errors++;
        tap_done |= targets_[i].addr == tap_;
      }
    }
    if (tap_.valid() && !tap_done && !net_->send(tap_, pkt, len))
      stats.tx_errors++;
  }
  void send_l16_(const int16_t *pcm, int n, bool marker) {
    uint8_t pkt[12 + FRAME * 2];
    header_(pkt, PT_L16, marker);
    for (int i = 0; i < n; i++) {
      pkt[12 + 2 * i] = (uint8_t) ((uint16_t) pcm[i] >> 8);
      pkt[13 + 2 * i] = (uint8_t) ((uint16_t) pcm[i] & 0xFF);
    }
    deliver_(pkt, 12 + 2 * (size_t) n, true);
    seq_++;
    ts_ += (uint32_t) n;
    stats.tx_packets++;
  }
  void send_cn_() {
    uint8_t pkt[13];
    header_(pkt, PT_CN, false);
    pkt[12] = 127;
    deliver_(pkt, sizeof pkt, false);  // the end of speech always reaches everyone who may have heard the start
    seq_++;
  }
  void send_latch_(Target &t) {
    uint8_t pkt[12 + FRAME * 2] = {0};
    header_(pkt, PT_L16, t.latch_left == cfg_.latch_frames);
    if (!net_->send(t.addr, pkt, sizeof pkt))
      stats.tx_errors++;
    seq_++;
    ts_ += FRAME;
    stats.tx_packets++;
    t.latch_left--;
  }
  void send_keepalive_(uint32_t now) {
    uint8_t pkt[12];
    header_(pkt, PT_L16, false);
    bool tap_done = false;
    for (int i = 0; i < n_targets_; i++) {
      net_->send(targets_[i].addr, pkt, sizeof pkt);
      tap_done |= targets_[i].addr == tap_;
    }
    if (tap_.valid() && !tap_done)
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

  LinkConfig cfg_;
  Transport *net_ = nullptr;
  Sink sink_;
  Policy policy_;
  Target targets_[MAX_TARGETS];
  int n_targets_ = 0;
  Addr tap_, trusted_;
  uint32_t trusted_until_ = 0;
  bool first_ = true, gate_ = true, keepalive_due_ = false;
  std::atomic<bool> tx_{false}, closing_{false};  // shared with the mic task (RoomKey review: not volatile)
  uint32_t keepalive_ms_ = 0;
  uint16_t seq_ = 0;
  uint32_t ts_ = 0, ssrc_ = 0x61697673;  // "aivs"
  Pre pre_[PRE];
  int pre_head_ = 0, pre_count_ = 0;
  int16_t ring_[RING];
  std::atomic<uint32_t> head_{0}, tail_{0}, dropped_{0};
};

}  // namespace voice
}  // namespace aikos
