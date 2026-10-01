// aikos_voice level.h on a PC: the speech detector behind the call's speech-based end (R17.8).
//   g++ -std=c++17 -Wall -Wextra -I esphome/components/aikos_voice esphome/tests/aikos_voice/level_test.cpp -o t && ./t
#include <cmath>
#include <cstdint>
#include <cstdio>
#include "level.h"

using aikos::voice::level_db;
using aikos::voice::VoiceGate;
static int fails = 0, checks = 0;
#define CHECK(c, what)                                 \
  do {                                                 \
    checks++;                                          \
    if (!(c))                                          \
      fails++, printf("  FAIL: %s\n", what);           \
    else                                               \
      printf("  ok    %s\n", what);                    \
  } while (0)

template<typename F> static uint32_t feed(VoiceGate &g, uint32_t t, uint32_t ms, F level) {
  for (uint32_t k = 0; k < ms / 20; k++, t += 20)
    g.note(level(k), t);
  return t;
}
static float words(uint32_t k) { return (k / 8) % 3 == 2 ? -48.0f : -28.0f; }  // syllables with gaps

int main() {
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 3000, [](uint32_t) { return -50.0f; });
    CHECK(!g.voiced_since(0), "steady street noise is not speech");
    feed(g, t, 1000, [](uint32_t k) { return (k / 5) % 2 ? -46.0f : -52.0f; });
    CHECK(!g.voiced_since(0), "noise that wobbles by 6 dB is not speech");
  }
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 1000, [](uint32_t) { return -50.0f; });
    const uint32_t t_speech = t;
    t = feed(g, t, 2000, words);
    CHECK(g.voiced_since(t_speech), "words with gaps over noise are speech");
    CHECK(g.quiet_ms(t) < 300, "the quiet time stays short while talking");
    t = feed(g, t, 4000, [](uint32_t) { return -50.0f; });
    CHECK(g.quiet_ms(t) >= 3500, "after the talk the quiet time grows");
    CHECK(!g.voiced_since(t - 3000), "nothing said in the last 3 s");
  }
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 1500, [](uint32_t) { return -50.0f; });
    g.note(-15.0f, t);
    feed(g, t + 20, 1000, [](uint32_t) { return -50.0f; });
    CHECK(!g.voiced_since(0), "a single knock is not speech");
  }
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 1000, [](uint32_t) { return -120.0f; });
    feed(g, t, 1000, [](uint32_t) { return -50.0f; });
    CHECK(!g.voiced_since(0), "muted blocks don't lower the floor (no speech after a muted mic start)");
  }
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 1000, [](uint32_t) { return -95.0f; });
    feed(g, t, 1000, [](uint32_t k) { return k % 4 == 3 ? -95.0f : -80.0f; });
    CHECK(!g.voiced_since(0), "very quiet levels (< -75 dBFS) are not speech");
  }
  {
    VoiceGate g;
    const uint32_t t0 = 0xFFFFF800u;  // 2 s before millis() wraps
    uint32_t t = feed(g, t0, 1000, [](uint32_t) { return -50.0f; });
    t = feed(g, t, 2000, words);
    CHECK(t < t0 && g.voiced_since(t0), "voiced_since works across the millis() wrap");
  }
  {
    VoiceGate g;
    uint32_t t = feed(g, 1000, 1000, [](uint32_t) { return -50.0f; });
    t = feed(g, t, 1000, words);
    g.reset();
    CHECK(!g.voiced_since(0), "reset forgets the speech");
  }
  {  // door mic, voice v2 live test 01.10.: dropouts (partly empty blocks) pulled the old minimum floor far down
    VoiceGate g;
    feed(g, 1000, 6000, [](uint32_t k) { return k % 40 == 7 ? -85.0f : (k % 3 ? -40.0f : -41.5f); });
    CHECK(!g.voiced_since(0), "dropouts (1 block in 40 at -85 dBFS) don't turn the noise into speech");
  }
  {
    VoiceGate g;
    feed(g, 1000, 6000, [](uint32_t k) { return k % 6 == 0 ? -24.0f : -40.0f; });   // a crack every 120 ms
    CHECK(!g.voiced_since(0), "single loud blocks (cracks, 8 per second) are not speech");
  }
  {
    VoiceGate g;
    feed(g, 1000, 6000, [](uint32_t k) { return k % 40 < 2 ? -20.0f : -40.0f; });   // a double crack every 0.8 s
    CHECK(!g.voiced_since(0), "two loud blocks in a row are not speech either");
  }
  {
    VoiceGate g;   // the same noise with dropouts, then words: still found, and quiet again after them
    uint32_t t = feed(g, 1000, 3000, [](uint32_t k) { return k % 40 == 7 ? -85.0f : -40.0f; });
    const uint32_t t_speech = t;
    t = feed(g, t, 2000, words);
    CHECK(g.voiced_since(t_speech), "words over noise with dropouts are speech");
    t = feed(g, t, 4000, [](uint32_t k) { return k % 40 == 7 ? -85.0f : -40.0f; });
    CHECK(g.quiet_ms(t) >= 3500, "after the words the noise with dropouts stays quiet");
  }
  {
    int16_t zero[320] = {0}, full[320], tone[320];
    for (int i = 0; i < 320; i++) {
      full[i] = i % 2 ? 32767 : -32767;
      tone[i] = (int16_t) (3277 * sinf(2 * 3.14159265f * 440.0f * i / 16000.0f));  // -20 dBFS peak
    }
    CHECK(level_db(zero, 320) <= -119.0f, "level_db: digital silence is -120");
    CHECK(fabsf(level_db(full, 320)) < 0.1f, "level_db: full scale square is 0 dBFS");
    CHECK(fabsf(level_db(tone, 320) - (-23.0f)) < 0.5f, "level_db: a -20 dBFS-peak sine is -23 dBFS rms");
  }
  printf("%d checks, %d failed\n", checks, fails);
  return fails ? 1 : 0;
}
