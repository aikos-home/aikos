// aikos::voice: signal processing for the microphone path (from the RoomKey: clipping costs words).
// Pure C++17. Moved out of voice_core.h unchanged for voice v2 (architecture review of v1, 2026-10-01).
#pragma once

#include <cmath>

namespace aikos {
namespace voice {

// Second-order filter; `highpass` takes knocks, handling noise and DC out of the speech band.
struct Biquad {
  float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
  static Biquad highpass(float fc, float fs, float q = 0.7071f) {
    const float w = 2.0f * 3.14159265f * fc / fs, cw = cosf(w), alpha = sinf(w) / (2.0f * q), a0 = 1.0f + alpha;
    Biquad f;
    f.b0 = (1.0f + cw) / 2.0f / a0;
    f.b1 = -(1.0f + cw) / a0;
    f.b2 = (1.0f + cw) / 2.0f / a0;
    f.a1 = -2.0f * cw / a0;
    f.a2 = (1.0f - alpha) / a0;
    return f;
  }
  float process(float x) {
    const float y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};

// Peak limiter: turns words down instead of clipping them.
struct Limiter {
  float env = 0.0f;
  float ceiling = 0.8f * 32767.0f;  // about -2 dBFS
  float process(float v) {
    const float a = v < 0 ? -v : v;
    env = a > env ? a : env * 0.9995f + a * 0.0005f;
    return env > ceiling ? v * (ceiling / env) : v;
  }
};

}  // namespace voice
}  // namespace aikos
