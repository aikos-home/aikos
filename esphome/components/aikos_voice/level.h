// aikos::voice: "is somebody talking?" from levels alone, for the call model's speech-based end (R17.8) and
// end-of-speech detection. Pure C++17, time comes in as `now` (ms), so it runs on a PC.
// From the RoomKey (roomkey_dsp.h VoiceGate, used on the device since 2026-10-01 for its mic and the door audio).
#pragma once

#include <cmath>
#include <cstdint>

namespace aikos {
namespace voice {

// One call per audio block (any block size of about 10–30 ms), with the block's level in dBFS.
// Speech = VOICE_DB above the noise floor, the quietest block of the last WINDOW_MS: speech has gaps between words,
// steady noise (street, fan, rain) does not. A single loud block is no speech (the level is smoothed). Muted blocks
// (< −100 dBFS, e.g. a mic that is just starting) don't count, so they can't pull the floor down.
// Thread use: note() from one task (mic or network), the getters from another; the two fields they share are volatile.
class VoiceGate {
 public:
  static constexpr int N = 96;                // ≥ 1.5 s of 16 ms mic blocks or 20 ms RTP packets
  static constexpr float VOICE_DB = 12.0f;    // above the floor
  static constexpr float MIN_DB = -75.0f;     // quieter than this is never speech
  static constexpr uint32_t WINDOW_MS = 1500;

  void note(float db, uint32_t now) {
    if (db < -100.0f)
      return;
    db_[i_] = db;
    ms_[i_] = now;
    i_ = (i_ + 1) % N;
    float floor = db;
    for (int i = 0; i < N; i++)
      if (now - ms_[i] < WINDOW_MS && db_[i] < floor)
        floor = db_[i];
    floor_ = floor;
    smooth_ = smooth_ < -100.0f ? db : smooth_ * 0.7f + db * 0.3f;
    if (smooth_ > floor + VOICE_DB && db > MIN_DB) {
      last_ = now;
      voice_ = true;
    }
  }
  // speech since t0 (wrap-safe for millis())
  bool voiced_since(uint32_t t0) const { return voice_ && (int32_t) (last_ - t0) >= 0; }
  uint32_t quiet_ms(uint32_t now) const { return now - last_; }  // only meaningful once voiced_since() was true
  uint32_t last_voice_ms() const { return last_; }
  float floor_db() const { return floor_; }
  void reset() {
    voice_ = false;
    smooth_ = -120.0f;
  }

 protected:
  float db_[N] = {0};
  uint32_t ms_[N] = {0};
  int i_ = 0;
  float floor_ = 0.0f, smooth_ = -120.0f;
  volatile bool voice_ = false;
  volatile uint32_t last_ = 0;
};

// The level of a block of 16-bit samples in dBFS (−120 for digital silence).
inline float level_db(const int16_t *s, int n) {
  if (n <= 0)
    return -120.0f;
  double acc = 0;
  for (int i = 0; i < n; i++)
    acc += (double) s[i] * s[i];
  const double ms = acc / n / (32768.0 * 32768.0);
  return ms < 1e-12 ? -120.0f : (float) (10.0 * std::log10(ms));
}

}  // namespace voice
}  // namespace aikos
