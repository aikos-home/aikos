// Unit tests for aikos::voice::Link (voice v2: the link moves audio, call.h decides who hears what). The wire rules
// tested live with v1 on 2026-10-01 keep their checks; a change that breaks one makes this program fail (exit code 1).
// Build and run on a PC (CI does the same):
//   g++ -std=c++17 -Wall -I ../../components/aikos_voice voice_core_test.cpp -o voice_core_test && ./voice_core_test
//   (Windows without a compiler: python -m ziglang c++ ... from the PyPI package "ziglang")
#include <cstdio>
#include <cstring>
#include <deque>
#include <string>
#include <vector>
#include "voice_core.h"

using namespace aikos::voice;

static int failures = 0, checks = 0;
#define CHECK(cond, what)                                              \
  do {                                                                 \
    checks++;                                                          \
    if (!(cond)) {                                                     \
      failures++;                                                      \
      printf("  FAIL line %d: %s  (%s)\n", __LINE__, what, #cond);     \
    }                                                                  \
  } while (0)

struct Sent {
  Addr to;
  std::vector<uint8_t> data;
  uint8_t pt() const { return data.size() > 1 ? (data[1] & 0x7F) : 0; }
  bool marker() const { return data.size() > 1 && (data[1] & 0x80); }
  uint16_t seq() const { return (uint16_t) ((data[2] << 8) | data[3]); }
  uint32_t ts() const { return (uint32_t) data[4] << 24 | (uint32_t) data[5] << 16 | (uint32_t) data[6] << 8 | data[7]; }
  int samples() const { return data.size() > 12 ? (int) (data.size() - 12) / 2 : 0; }
  int16_t sample(int i) const { return (int16_t) ((data[12 + 2 * i] << 8) | data[13 + 2 * i]); }
};

struct FakeNet : Transport {
  std::vector<Sent> sent;
  std::deque<std::pair<Addr, std::vector<uint8_t>>> inbox;
  bool send(const Addr &to, const uint8_t *d, size_t n) override {
    sent.push_back({to, std::vector<uint8_t>(d, d + n)});
    return true;
  }
  int recv(uint8_t *buf, size_t cap, Addr &from) override {
    if (inbox.empty())
      return -1;
    auto p = inbox.front();
    inbox.pop_front();
    from = p.first;
    memcpy(buf, p.second.data(), std::min(cap, p.second.size()));
    return (int) p.second.size();
  }
  // audio and end packets to `a` (12-byte keepalives are counted by their own test)
  std::vector<Sent> to(const Addr &a) const {
    std::vector<Sent> r;
    for (auto &s : sent)
      if (s.to == a && s.data.size() > 12)
        r.push_back(s);
    return r;
  }
};

static Addr A(uint8_t last, uint16_t port) {  // 192.0.2.<last>:port (RFC 5737 test range), network byte order, LE host
  Addr a;
  a.ip = (uint32_t) 192 | (uint32_t) 0 << 8 | (uint32_t) 2 << 16 | (uint32_t) last << 24;
  a.port = (uint16_t) ((port >> 8) | (port << 8));
  return a;
}

static std::vector<uint8_t> rtp(uint8_t pt, int samples, int16_t value, uint16_t seq = 1) {
  std::vector<uint8_t> p(12 + 2 * samples, 0);
  p[0] = 0x80;
  p[1] = pt;
  p[2] = seq >> 8;
  p[3] = seq & 0xFF;
  for (int i = 0; i < samples; i++) {
    p[12 + 2 * i] = (uint8_t) ((uint16_t) value >> 8);
    p[13 + 2 * i] = (uint8_t) ((uint16_t) value & 0xFF);
  }
  return p;
}

struct Rig {
  FakeNet net;
  Link link;
  std::vector<int16_t> played;
  Verdict verdict = Verdict::DROP;  // what the policy says for every sender (tests change it)
  explicit Rig(int latch = 3, uint32_t keepalive = 0) {
    LinkConfig c;
    c.latch_frames = latch;
    c.keepalive_ms = keepalive;
    link.configure(c);
    link.set_transport(&net);
    link.set_sink([this](const int16_t *p, size_t n) { played.insert(played.end(), p, p + n); });
    link.set_policy([this](const Addr &, uint32_t) { return verdict; });
  }
};

static const Addr DOOR_TAP = A(110, 5008), KEY = A(144, 5004), KEY2 = A(145, 5004), OTHER = A(99, 5004);

static void test_talk_packets_and_copy() {
  puts("talk: 20 ms L16 frames to the target and transcriber, marker on the first, seq/ts advance");
  Rig r(0);
  r.link.set_target(KEY, 0);
  r.link.set_tap(DOOR_TAP);
  r.link.talk(true, 0);
  std::vector<int16_t> s(640);
  for (int i = 0; i < 640; i++)
    s[i] = (int16_t) (i * 7 - 2000);
  r.link.push(s.data(), s.size());
  r.link.loop(20);
  auto peer = r.net.to(KEY), tap = r.net.to(DOOR_TAP);
  CHECK(peer.size() == 2 && tap.size() == 2, "two frames to each");
  CHECK(peer[0].pt() == PT_L16 && peer[0].samples() == FRAME, "PT 96, 320 samples");
  CHECK(peer[0].marker() && !peer[1].marker(), "marker only on the first packet of the spurt");
  CHECK((uint16_t) (peer[1].seq() - peer[0].seq()) == 1, "seq +1");
  CHECK(peer[1].ts() - peer[0].ts() == FRAME, "timestamp +320");
  CHECK(peer[0].sample(0) == s[0] && peer[1].sample(319) == s[639], "big-endian samples intact");
}

static void test_release_drains_then_end_packet() {
  puts("release: the last samples go out, then one comfort-noise packet (PT 13) to target and transcriber");
  Rig r(0);
  r.link.set_target(KEY, 0);
  r.link.set_tap(DOOR_TAP);
  r.link.talk(true, 0);
  std::vector<int16_t> s(100, 1234);
  r.link.push(s.data(), s.size());
  r.link.talk(false, 10);
  CHECK(!r.link.talking(), "not talking once released");
  r.link.loop(20);
  auto peer = r.net.to(KEY), tap = r.net.to(DOOR_TAP);
  CHECK(peer.size() == 2 && peer[0].samples() == 100 && peer[0].sample(99) == 1234, "the short last frame");
  CHECK(peer[1].pt() == PT_CN && peer[1].data.size() == 13 && peer[1].data[12] == 127, "CN with 1-byte level");
  CHECK(tap.size() == 2 && tap[1].pt() == PT_CN, "the transcriber gets the end packet too");
  r.link.push(s.data(), s.size());
  r.link.loop(40);
  CHECK(r.net.to(KEY).size() == 2, "nothing after the release");
}

static void test_tap_equal_target_once() {
  puts("copy: when the transcriber IS a target, each packet goes out once");
  Rig r(0);
  r.link.set_target(KEY, 0);
  r.link.set_tap(KEY);
  r.link.talk(true, 0);
  std::vector<int16_t> s(320, 5);
  r.link.push(s.data(), s.size());
  r.link.loop(20);
  CHECK(r.net.to(KEY).size() == 1, "one copy");
}

static void test_several_targets() {
  puts("targets: every target gets every frame (v2: the door talks to every key); duplicates count once");
  Rig r(0);
  const Addr list[] = {KEY, KEY2, KEY, Addr{}};
  r.link.set_targets(list, 4, 0);
  CHECK(r.link.targets() == 2, "two targets (duplicate and invalid dropped)");
  r.link.set_tap(DOOR_TAP);
  r.link.talk(true, 0);
  std::vector<int16_t> s(320, 9);
  r.link.push(s.data(), s.size());
  r.link.loop(20);
  CHECK(r.net.to(KEY).size() == 1 && r.net.to(KEY2).size() == 1 && r.net.to(DOOR_TAP).size() == 1, "one frame each");
}

static void test_gate() {
  puts("gate: send_to_targets(false) keeps frames from the targets, never from the transcriber (R17.16 mute)");
  Rig r(0);
  r.link.set_target(KEY, 0);
  r.link.set_tap(DOOR_TAP);
  r.link.talk(true, 0);
  std::vector<int16_t> s(320, 3);
  r.link.send_to_targets(false);
  r.link.push(s.data(), s.size());
  r.link.loop(20);
  CHECK(r.net.to(KEY).empty() && r.net.to(DOOR_TAP).size() == 1, "muted: transcriber only");
  r.link.send_to_targets(true);
  r.link.push(s.data(), s.size());
  r.link.loop(40);
  CHECK(r.net.to(KEY).size() == 1 && r.net.to(DOOR_TAP).size() == 2, "open again: both");
  CHECK((uint16_t) (r.net.to(DOOR_TAP)[1].seq() - r.net.to(DOOR_TAP)[0].seq()) == 1, "seq runs on (a gap at the key)");
  r.link.send_to_targets(false);
  r.link.talk(false, 50);
  r.link.loop(60);
  CHECK(r.net.to(KEY).back().pt() == PT_CN, "the end packet reaches the targets even while muted");
}

static void test_latch_frames() {
  puts("latch: a new target gets 3 silent frames at 0, +0.1 s, +0.4 s, the first with marker; not to the transcriber");
  Rig r(3);
  r.link.set_tap(DOOR_TAP);
  r.link.set_target(KEY, 1000);
  CHECK(r.net.to(KEY).size() == 1, "first at once");
  r.link.loop(1050);
  CHECK(r.net.to(KEY).size() == 1, "not yet at +50 ms");
  r.link.loop(1100);
  CHECK(r.net.to(KEY).size() == 2, "second at +100 ms");
  r.link.loop(1399);
  CHECK(r.net.to(KEY).size() == 2, "not yet at +399 ms");
  r.link.loop(1400);
  r.link.loop(2000);
  auto k = r.net.to(KEY);
  CHECK(k.size() == 3, "exactly three");
  CHECK(k[0].marker() && k[0].samples() == FRAME && k[0].sample(0) == 0 && k[2].sample(319) == 0, "silent frames");
  CHECK(r.net.to(DOOR_TAP).empty(), "the transcriber gets no latch frames");
  const Addr both[] = {KEY, KEY2};
  r.link.set_targets(both, 2, 3000);
  r.link.loop(3100);
  r.link.loop(3400);
  CHECK(r.net.to(KEY).size() == 3, "a target that stays gets no new latch");
  CHECK(r.net.to(KEY2).size() == 3, "the new one gets its three");
}

static void test_policy_play_hold_drop() {
  puts("incoming: the policy decides; HOLD keeps 0.3 s for flush(), older and DROP count as held back");
  Rig r(0);
  r.verdict = Verdict::HOLD;
  r.net.inbox.push_back({KEY, rtp(PT_L16, 320, 111)});  // t=0: 1.0 s before flush: too old
  r.link.loop(0);
  r.net.inbox.push_back({KEY, rtp(PT_L16, 320, 222)});  // t=800: 0.2 s before flush
  r.net.inbox.push_back({OTHER, rtp(PT_L16, 320, 444)});
  r.link.loop(800);
  CHECK(r.played.empty(), "HOLD: nothing played yet");
  r.link.flush(KEY, 1000);
  CHECK(r.played.size() == 320 && r.played[0] == 222, "flush plays only the recent frame of that sender");
  CHECK(r.link.stats.held_back == 1 && r.link.stats.rx_packets == 1, "the old one held back, the recent one counted");
  r.link.flush(OTHER, 1000);
  CHECK(r.played.size() == 640 && r.played[320] == 444, "the other sender's frame was kept, in order");
  r.verdict = Verdict::PLAY;
  r.net.inbox.push_back({KEY, rtp(PT_L16, 320, 333)});
  r.link.loop(1020);
  CHECK(r.played.size() == 960 && r.played[640] == 333, "PLAY: played live");
  r.verdict = Verdict::DROP;
  r.net.inbox.push_back({KEY, rtp(PT_L16, 320, 555)});
  r.link.loop(1040);
  CHECK(r.played.size() == 960 && r.link.stats.held_back == 2, "DROP: not played, held back");
}

static void test_prebuffer_overflow() {
  puts("HOLD: more than 0.5 s waiting: the oldest frames fall out and are counted");
  Rig r(0);
  r.verdict = Verdict::HOLD;
  for (int i = 0; i < 40; i++)
    r.net.inbox.push_back({KEY, rtp(PT_L16, 320, (int16_t) i)});
  r.link.loop(0);
  r.link.loop(1);
  r.link.loop(2);
  CHECK(r.link.stats.held_back == 15, "40 frames, room for 25: 15 held back");
  r.link.flush(KEY, 100);
  CHECK(r.played.size() == 25 * 320 && r.played[0] == 15, "the newest 25 are played, oldest first");
}

static void test_noise_never_played() {
  puts("CN and keepalives are never played, whatever the policy");
  Rig r(0);
  r.verdict = Verdict::PLAY;
  r.net.inbox.push_back({KEY, rtp(PT_CN, 0, 0)});
  r.net.inbox.back().second.push_back(127);
  r.net.inbox.push_back({KEY, std::vector<uint8_t>{0x80, PT_L16, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1}});
  r.link.loop(60);
  CHECK(r.played.empty(), "CN and 12-byte keepalive not played");
}

static void test_door_talks_and_plays() {
  puts("v2: no half-duplex inside the link; the policy decides (the door mic is open while the door plays)");
  Rig r(0);
  r.verdict = Verdict::PLAY;
  r.link.set_target(KEY, 0);
  r.link.talk(true, 0);
  r.net.inbox.push_back({KEY, rtp(PT_L16, 320, 7)});
  r.link.loop(20);
  CHECK(r.played.size() == 320, "played while this end talks");
}

static void test_keepalive() {
  puts("keepalive: a 12-byte header every 60 s while not talking, to every target and the transcriber");
  Rig r(0, 60000);
  const Addr list[] = {A(172, 5004), KEY2};
  r.link.set_targets(list, 2, 0);
  r.link.set_tap(A(110, 5006));
  r.link.loop(0);
  size_t n0 = r.net.sent.size();
  CHECK(n0 == 3 && r.net.sent[0].data.size() == 12, "at once to all three");
  r.link.loop(59999);
  CHECK(r.net.sent.size() == n0, "not before 60 s");
  r.link.loop(60000);
  CHECK(r.net.sent.size() == n0 + 3, "again at 60 s");
  r.link.talk(true, 60000);
  r.link.loop(130000);
  size_t ka = 0;
  for (auto &s : r.net.sent)
    ka += s.data.size() == 12;
  CHECK(ka == 6, "none while talking");
}

static void test_trusted_source() {
  puts("trusted source (e.g. a TTS stream later): played until its time runs out, whatever the policy");
  Rig r(0);
  const Addr tts = A(110, 7000);
  r.link.allow_source(tts, 5000);
  r.net.inbox.push_back({tts, rtp(PT_L16, 320, 42)});
  r.link.loop(100);
  CHECK(r.played.size() == 320 && r.played[0] == 42, "played although the policy says DROP");
  r.net.inbox.push_back({tts, rtp(PT_L16, 320, 43)});
  r.link.loop(5001);
  CHECK(r.played.size() == 320, "not after its time");
}

static void test_overrun_gap() {
  puts("overrun: samples the main loop could not take make a sequence gap, not spliced audio");
  Rig r(0);
  r.link.set_target(KEY, 0);
  r.link.talk(true, 0);
  std::vector<int16_t> s(8192 + 640, 1);
  r.link.push(s.data(), s.size());  // 640 samples too many for the 8192 ring
  r.link.loop(10);
  CHECK(r.link.stats.overruns == 1, "counted");
  auto k = r.net.to(KEY);
  CHECK(k.size() >= 2, "packets still flow");
}

static void test_edges() {
  puts("triggers: Edge gives one start and one end per state change (v1 fix kept)");
  Edge e;
  CHECK(e.update(false) == 0, "nothing at rest");
  CHECK(e.update(true) == 1 && e.update(true) == 0, "one start");
  CHECK(e.update(false) == -1 && e.update(false) == 0, "one end");
}

int main() {
  test_talk_packets_and_copy();
  test_release_drains_then_end_packet();
  test_tap_equal_target_once();
  test_several_targets();
  test_gate();
  test_latch_frames();
  test_policy_play_hold_drop();
  test_prebuffer_overflow();
  test_noise_never_played();
  test_door_talks_and_plays();
  test_keepalive();
  test_trusted_source();
  test_overrun_gap();
  test_edges();
  printf("\n%d checks, %d failed\n", checks, failures);
  return failures == 0 ? 0 : 1;
}
