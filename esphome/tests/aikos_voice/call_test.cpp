// Scenario tests for the voice v2 call model (call.h): every rule of R17 (aikos features/sprechen.md) has a check here.
// Build and run on a PC (CI does the same):
//   g++ -std=c++17 -Wall -Wextra -I ../../components/aikos_voice call_test.cpp -o call_test && ./call_test
#include <cstdio>
#include "call.h"

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

static Addr K(uint8_t last) {  // a room key at 192.0.2.<last>:5004 (RFC 5737 test range), network byte order, LE host
  Addr a;
  a.ip = (uint32_t) 192 | (uint32_t) 0 << 8 | (uint32_t) 2 << 16 | (uint32_t) last << 24;
  a.port = (uint16_t) ((5004 >> 8) | (5004 << 8));
  return a;
}
static const Addr A = K(144), B = K(145), C = K(146);

// what the door does at one moment: compared between case 1 and case 2 (R17.11)
struct DoorRoutes {
  bool mic, to_keys, plays_a, plays_b;
  bool operator==(const DoorRoutes &o) const {
    return mic == o.mic && to_keys == o.to_keys && plays_a == o.plays_a && plays_b == o.plays_b;
  }
};
static DoorRoutes routes(const DoorCall &c, uint32_t now) { return {c.mic_open(), c.mic_to_keys(now), c.plays(A), c.plays(B)}; }

static void test_case2_key_without_ring() {
  puts("case 2: a key holds without a ring -> call, door mic open, the key is played; silence ends it");
  DoorCall c;
  CHECK(!c.active() && !c.mic_open(), "idle: door mic closed (R17.2)");
  c.hold(A, true, 1000);
  CHECK(c.active() && c.id() == 1, "the hold starts call 1");
  CHECK(c.started_by() == CallStart::KEY_WITHOUT_RING, "started by a key without a ring");
  CHECK(c.mic_open() && c.mic_to_keys(1000), "door mic open, also towards the keys (R17.2)");
  CHECK(c.plays(A) && !c.plays(B), "the door plays the holding key, nobody else");
  CHECK(c.member(A) && c.members() == 1, "the key is in the call");
  c.hold(A, false, 4000);
  CHECK(c.active() && !c.plays(A), "released: not played any more (lock), call still on");
  CHECK(c.mic_open(), "the door mic stays open (the visitor answers without pressing, R17.2)");
  c.loop(4000 + 9999);
  CHECK(c.active(), "9.999 s after the last words: still on");
  c.loop(4000 + 10000);
  CHECK(!c.active() && c.ended_by() == CallEnd::SILENCE, "10 s without speech ends it (R17.8)");
  CHECK(!c.mic_open() && !c.member(A), "door mic closed, nobody in the call");
}

static void test_case1_visitor_first() {
  puts("case 1: ring, then the visitor presses Sprechen -> call before anyone answered; a key answers later");
  DoorCall c;
  c.ring(0);
  CHECK(!c.active() && !c.mic_open(), "a ring alone opens no mic (R17.1)");
  c.visitor_speak(3000);
  CHECK(c.active() && c.started_by() == CallStart::VISITOR, "Sprechen starts the call");
  CHECK(c.mic_open() && c.mic_to_keys(3000), "door mic open, goes to the keys before an answer (R17.13: keys decide)");
  CHECK(c.members() == 0 && c.floor() == nullptr, "nobody answered yet");
  c.speech(Role::DOOR, 9000);
  c.loop(9000 + 9000);
  CHECK(c.active(), "the visitor's speech keeps it on");
  c.hold(B, true, 18500);
  CHECK(c.member(B) && c.plays(B), "a key answers by holding and is played");
  CHECK(c.started_by() == CallStart::VISITOR && c.id() == 1, "still the same call");
}

static void test_case1_key_answers_ring() {
  puts("case 1: ring, then a key holds -> started by a key answering the ring");
  DoorCall c;
  c.ring(0);
  c.hold(A, true, 60000);
  CHECK(c.started_by() == CallStart::KEY_AFTER_RING, "within 2 min of the ring");
  c.end(CallEnd::EXTERNAL, 61000);
  c.hold(A, false, 61500);
  c.ring(100000);
  c.hold(A, true, 100000 + 120000);
  CHECK(c.started_by() == CallStart::KEY_WITHOUT_RING, "2 min after a ring it is case 2 again");
  CHECK(c.id() == 2, "call ids count up");
}

static void test_same_rules_both_cases() {
  puts("R17.11: case 1 and case 2 give the same routes for the same situation");
  DoorCall one, two;
  one.ring(0);
  one.hold(A, true, 1000);  // case 1
  two.hold(A, true, 1000);  // case 2
  CHECK(one.started_by() != two.started_by(), "they differ in the trigger");
  CHECK(routes(one, 1000) == routes(two, 1000), "a key holds: same routes");
  one.hold(B, true, 2000);
  two.hold(B, true, 2000);
  CHECK(routes(one, 2000) == routes(two, 2000), "a second key holds: same routes");
  one.hold(A, false, 3000);
  two.hold(A, false, 3000);
  CHECK(routes(one, 3000) == routes(two, 3000), "the first lets go: same routes");
  one.door_played(3100);
  two.door_played(3100);
  CHECK(routes(one, 3200) == routes(two, 3200), "door speaker playing: same routes");
  one.hold(B, false, 4000);
  two.hold(B, false, 4000);
  one.loop(14000);
  two.loop(14000);
  CHECK(!one.active() && !two.active() && one.ended_by() == two.ended_by(), "same end");
}

static void test_floor_and_busy() {
  puts("R17.14: everyone who answers is in; the first holder has the floor, a second is busy (besetzt)");
  DoorCall c;
  c.hold(A, true, 1000);
  c.hold(B, true, 1500);
  CHECK(c.floor() != nullptr && c.floor()->ip == A.ip, "A has the floor");
  CHECK(c.plays(A) && !c.plays(B), "only A is played");
  CHECK(c.busy(B) && !c.busy(A), "B is busy");
  CHECK(c.members() == 2, "both are in the call");
  c.hold(A, false, 3000);
  CHECK(c.floor() != nullptr && c.floor()->ip == B.ip && c.plays(B), "A lets go: B, still holding, gets the floor");
  CHECK(!c.busy(B), "B no longer busy");
  c.hold(B, false, 4000);
  CHECK(c.floor() == nullptr && !c.plays(A) && !c.plays(B), "nobody holds: nobody is played");
  CHECK(c.members() == 2 && c.active(), "both stay in the call");
}

static void test_lock() {
  puts("lock: a key is only ever played while it holds and has the floor; a stranger never");
  DoorCall c;
  c.ring(0);
  CHECK(!c.plays(A), "no call: nothing is played");
  c.visitor_speak(100);
  CHECK(!c.plays(A) && !c.plays(C), "call on, nobody holds: nothing is played");
  c.key_in_call(A, true, 200);
  CHECK(c.member(A) && !c.plays(A), "in the call but not holding: not played");
  c.hold(A, true, 300);
  CHECK(c.plays(A) && !c.plays(C), "holding: played; a stranger isn't");
}

static void test_hold_refresh() {
  puts("holds: resent every second; nothing for 3 s = released");
  DoorCall c;
  c.hold(A, true, 0);
  for (uint32_t t = 1000; t <= 5000; t += 1000) {
    c.hold(A, true, t);
    c.loop(t);
  }
  CHECK(c.plays(A), "refreshed: still holding at 5 s");
  c.loop(5000 + 3000);
  CHECK(c.plays(A), "3.0 s without a refresh: still holding");
  c.loop(5000 + 3001);
  CHECK(!c.plays(A) && !c.holds(A), "more than 3 s: released");
}

static void test_holding_keeps_call_on() {
  puts("R17.8: a held button counts as speech; silence counts from the release");
  DoorCall c;
  c.hold(A, true, 0);
  for (uint32_t t = 1000; t <= 20000; t += 1000) {
    c.hold(A, true, t);
    c.loop(t);
  }
  CHECK(c.active(), "held 20 s without speech: still on");
  c.hold(A, false, 20000);
  c.loop(29999);
  CHECK(c.active(), "9.999 s after the release: on");
  c.loop(30000);
  CHECK(!c.active() && c.ended_by() == CallEnd::SILENCE, "10 s after the release: over");

  DoorCall s;  // a short silence setting, shorter than the gap between two "holds": the held button alone keeps it on
  CallConfig cfg;
  cfg.silence_end_ms = 2000;
  s.configure(cfg);
  s.hold(A, true, 0);
  s.loop(2400);
  s.hold(A, true, 2500);
  s.loop(4900);
  CHECK(s.active(), "held, silence setting 2 s, holds 2.5 s apart: still on");
}

static void test_max_length() {
  puts("max length: speech that never stops can't keep a call open forever");
  DoorCall c;
  c.visitor_speak(0);
  for (uint32_t t = 5000; t < 300000; t += 5000) {
    c.speech(Role::DOOR, t);
    c.loop(t);
  }
  CHECK(c.active(), "on at 295 s");
  c.loop(300000);
  CHECK(!c.active() && c.ended_by() == CallEnd::MAX_LENGTH, "over at 300 s");
}

static void test_mute_tail() {
  puts("R17.16: the door mic is muted towards the keys while the door speaker plays, and 0.3 s after");
  DoorCall c;
  c.hold(A, true, 0);
  c.door_played(1000);
  CHECK(c.mic_open(), "the mic itself stays open (the transcriber copy is never muted)");
  CHECK(!c.mic_to_keys(1000) && !c.mic_to_keys(1299), "muted towards the keys up to 0.3 s after playing");
  CHECK(c.mic_to_keys(1300), "open again after 0.3 s");
}

static void test_end_from_outside_and_stale_hold() {
  puts("end from outside: over at once; a button still held starts no new call until pressed again");
  DoorCall c;
  c.hold(A, true, 0);
  c.end(CallEnd::FRONT_DOOR, 2000);
  CHECK(!c.active() && c.ended_by() == CallEnd::FRONT_DOOR && !c.mic_open(), "over");
  c.hold(A, true, 2500);  // the refresh of the still-held button
  c.loop(2500);
  CHECK(!c.active() && !c.plays(A), "the refresh starts nothing");
  c.hold(A, false, 3000);
  c.hold(A, true, 3500);
  CHECK(c.active() && c.id() == 2 && c.plays(A), "a new press starts call 2");

  DoorCall d;  // still held after the end, and someone else starts the next call
  d.hold(A, true, 0);
  d.end(CallEnd::FRONT_DOOR, 1000);
  d.visitor_speak(1500);
  d.hold(A, true, 1600);  // refresh of the old hold
  CHECK(d.active() && !d.plays(A) && !d.holds(A), "the old hold is neither played nor counted in the new call");
  d.loop(1500 + 10000);
  CHECK(!d.active() && d.ended_by() == CallEnd::SILENCE, "nor does it keep the new call open");
}

static void test_everyone_left() {
  puts("end: every key that answered left (e.g. the front door opened for each of them)");
  DoorCall c;
  c.hold(A, true, 0);
  c.hold(A, false, 1000);
  c.hold(B, true, 2000);
  c.hold(B, false, 3000);
  c.key_in_call(A, false, 4000);
  CHECK(c.active() && c.members() == 1, "one left, one still in");
  c.key_in_call(B, false, 5000);
  CHECK(!c.active() && c.ended_by() == CallEnd::EVERYONE_LEFT, "the last one left: over");

  DoorCall v;  // a call nobody answered yet doesn't end because "everybody left"
  v.visitor_speak(0);
  v.key_in_call(A, false, 100);
  CHECK(v.active(), "the visitor's call goes on");
}

static void test_key_case2_and_hearing() {
  puts("key: holding opens its mic; it never plays the door while it holds (R17.3, R17.4)");
  KeyCall k;
  CHECK(!k.mic_open() && !k.in_call(), "idle");
  k.hold(true, 1000);
  CHECK(k.mic_open() && k.in_call(), "held: mic open, in the call (case 2: it starts the call)");
  k.door_call(true, 7, 1300);
  CHECK(k.in_call() && k.door_id() == 7, "joins the call the door announces");
  CHECK(!k.plays_door(true), "never plays the door while holding (R17.4)");
  k.hold(false, 2000);
  CHECK(!k.mic_open(), "released: mic closed at once (R17.3)");
  CHECK(k.plays_door(false), "released: plays the door (it answered)");
  k.door_call(true, 7, 2300);
  CHECK(k.in_call(), "the door's refresh changes nothing");
  k.door_call(false, 7, 5000);
  CHECK(!k.in_call() && !k.plays_door(true) && k.left_by() == CallEnd::DOOR_ENDED, "the door ended the call");
}

static void test_key_short_press_before_announcement() {
  puts("key: a short press released before the door's announcement still joins that call");
  KeyCall k;
  k.hold(true, 0);
  k.hold(false, 400);
  CHECK(k.in_call(), "pending: in the call it started");
  k.door_call(true, 1, 800);
  CHECK(k.in_call() && k.plays_door(false), "joined call 1 and hears the visitor's answer");
  k.door_call(true, 2, 1500);  // the door's "call 1 is over" got lost, and call 2 began
  CHECK(!k.in_call() && !k.plays_door(false), "only in the call it joined: not in call 2");
}

static void test_key_hear_before_answer() {
  puts("R17.13: before answering, a key plays the visitor only if its owner wants that");
  KeyCall k;
  k.door_call(true, 3, 0);
  CHECK(!k.in_call(), "a visitor's call: this key hasn't answered");
  CHECK(!k.plays_door(false), "setting off (or bedroom after 22:00): silent, text only");
  CHECK(k.plays_door(true), "setting on (Männerzimmer): plays the visitor at once");
  k.hold(true, 1000);
  CHECK(k.in_call() && !k.plays_door(true), "answering: in the call, silent while holding");
  k.hold(false, 2000);
  CHECK(k.plays_door(false), "after answering it plays whatever the setting");
}

static void test_key_front_door_and_new_call() {
  puts("R17.8: the front door ends the call for a key that has it switched on; a new door call starts fresh");
  KeyCall k;
  k.door_call(true, 4, 0);
  k.hold(true, 500);
  k.hold(false, 1500);
  k.front_door(2000);
  CHECK(!k.in_call() && k.left_by() == CallEnd::FRONT_DOOR, "left the call");
  k.door_call(true, 4, 2500);
  CHECK(!k.in_call() && !k.plays_door(true), "the door's refresh of the same call doesn't bring it back");
  k.door_call(false, 4, 9000);
  k.door_call(true, 5, 20000);
  CHECK(k.plays_door(true) && !k.in_call(), "call 5: hears the visitor again (setting on), not answered yet");
}

static void test_key_own_end_rules() {
  puts("key: leaves on its own silence; the door's announcement stopping counts as the end");
  KeyCall k;
  k.door_call(true, 1, 0);
  k.hold(true, 0);
  k.hold(false, 1000);
  for (uint32_t t = 1000; t <= 10000; t += 1000)
    k.door_call(true, 1, t);
  k.loop(10999);
  CHECK(k.in_call(), "9.999 s after its last words: in");
  k.loop(11000);
  CHECK(!k.in_call() && k.left_by() == CallEnd::SILENCE, "10 s silence: left");

  KeyCall g;
  g.door_call(true, 2, 0);
  g.hold(true, 100);
  g.hold(false, 200);
  g.loop(3000);
  CHECK(g.in_call(), "3.0 s after the door's last announcement: in");
  g.loop(3001);
  CHECK(!g.in_call() && !g.door_on() && g.left_by() == CallEnd::DOOR_ENDED, "door silent > 3 s: over");
}

static void test_key_busy_and_stale() {
  puts("key: busy while another key has the floor; a held button doesn't talk into an ended call");
  KeyCall k;
  k.door_call(true, 1, 0);
  k.hold(true, 100);
  k.floor_taken(true);
  CHECK(k.busy(), "another key has the floor: besetzt");
  k.floor_taken(false);
  CHECK(!k.busy(), "free again");
  k.door_call(false, 1, 1000);
  CHECK(!k.mic_open(), "the call ended while held: mic closed");
  k.hold(false, 1500);
  k.hold(true, 2000);
  CHECK(k.mic_open() && k.in_call(), "a new press: talks again");
}

int main() {
  test_case2_key_without_ring();
  test_case1_visitor_first();
  test_case1_key_answers_ring();
  test_same_rules_both_cases();
  test_floor_and_busy();
  test_lock();
  test_hold_refresh();
  test_holding_keeps_call_on();
  test_max_length();
  test_mute_tail();
  test_end_from_outside_and_stale_hold();
  test_everyone_left();
  test_key_case2_and_hearing();
  test_key_short_press_before_announcement();
  test_key_hear_before_answer();
  test_key_front_door_and_new_call();
  test_key_own_end_rules();
  test_key_busy_and_stale();
  printf("\n%d checks, %d failed\n", checks, failures);
  return failures == 0 ? 0 : 1;
}
