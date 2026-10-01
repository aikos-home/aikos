// aikos_voice: ESPHome component around the shared voice link, used by the door talk computer and the room keys.
// Behaviour = voice v2 (call.h decides who hears what, voice_core.h moves the audio, level.h finds speech). Everything
// that is not the voice link itself (screens, buttons, HA glue, which key has which address) stays in the device
// configs, so it can change as often as it likes without touching this.
#pragma once

#include <string>
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/components/microphone/microphone_source.h"
#include "esphome/components/speaker/speaker.h"
#include "call.h"
#include "level.h"
#include "voice_core.h"
#include "voice_udp.h"

#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_BINARY_SENSOR
#include "esphome/components/binary_sensor/binary_sensor.h"
#endif

namespace esphome::aikos_voice {

using VoiceRole = ::aikos::voice::Role;

class AikosVoice : public Component {
 public:
  // ── configuration ──
  void set_microphone_source(microphone::MicrophoneSource *m) { this->mic_ = m; }
  void set_speaker(speaker::Speaker *s) { this->speaker_ = s; }
  void set_role(VoiceRole r) { this->role_ = r; }
  void set_port(uint16_t p) { this->port_ = p; }
  void set_prebuffer(uint32_t ms) { this->link_cfg_.prebuffer_ms = ms; }
  void set_latch_frames(int n) { this->link_cfg_.latch_frames = n; }
  void set_keepalive(uint32_t ms) { this->link_cfg_.keepalive_ms = ms; }
  void set_highpass(bool on) { this->highpass_ = on; }
  void set_mic_start_mute(uint32_t ms) { this->mic_start_mute_samples_ = ms * 16; }  // 16 samples per ms
  void set_initial_transcriber(const std::string &a) { this->transcriber_ = a; }
  void set_initial_door(const std::string &a) { this->door_host_ = a; }
  void set_silence_end(uint32_t ms) { this->call_cfg_.silence_end_ms = ms; }
  void set_max_length(uint32_t ms) { this->call_cfg_.max_length_ms = ms; }
  void set_mute_tail(uint32_t ms) { this->call_cfg_.mute_tail_ms = ms; }
  void set_hold_refresh(uint32_t ms) { this->call_cfg_.hold_refresh_ms = ms; }
  void set_ring_window(uint32_t ms) { this->call_cfg_.ring_window_ms = ms; }

  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }
  void setup() override;
  void loop() override;
  void dump_config() override;

  // ── both ends ──
  void set_transcriber(const std::string &host_port);       // "" = off
  void allow_source(const std::string &host, uint32_t ms);  // a trusted stream (e.g. TTS later) for ms
  void set_mic_gain(float g) { this->gain_ = g; }
  float get_mic_gain() const { return this->gain_; }
  void set_call_silence_end(uint32_t ms);  // the number entities on the device (R17.8)
  void set_call_max_length(uint32_t ms);
  void end_call();  // from outside (door: API, front door later; key: its front-door switch)

  // ── door ──
  void ring();
  void visitor_speak();                                   // the door screen's one-time "Sprechen"
  void key_hold(const std::string &host, bool held);      // a key's talk_held
  void key_in_call(const std::string &host, bool in);     // a key's in_call
  void set_keys(const std::string &hosts);                // every key's address, "a,b,c" (from aikos_people)

  // ── room key ──
  void hold(bool held);                                         // this key's button
  void join();                                                  // one short press: listen (R19)
  void door_call(bool on, uint32_t id, bool answered);          // the door's announcement
  void floor_key(int last_octet);                               // the door's floor (0 = nobody)
  void set_hear_visitor(bool on) { this->hear_visitor_ = on; }  // the key's setting with its times, evaluated by it
  void set_door(const std::string &host_port);
  void record(bool on);  // a test recording: mic to the transcriber only, never to the door (RoomKey must-have)

  // ── state ──
  bool in_call() const;  // door: a call is on; key: this key is in the call
  bool is_talking() const { return this->link_.talking(); }
  bool answered() const { return this->door_.answered(); }
  bool remote_holding() const { return this->door_.floor() != nullptr; }
  bool busy() const { return this->key_.busy(); }
  uint32_t call_id() const { return this->role_ == VoiceRole::DOOR ? this->door_.id() : this->key_.door_id(); }
  int floor_last_octet() const;
  const ::aikos::voice::Stats &stats() const { return this->link_.stats; }

  Trigger<> *get_talk_start_trigger() { return &this->talk_start_trigger_; }
  Trigger<> *get_talk_stop_trigger() { return &this->talk_stop_trigger_; }
  Trigger<> *get_call_start_trigger() { return &this->call_start_trigger_; }
  Trigger<> *get_call_end_trigger() { return &this->call_end_trigger_; }

#ifdef USE_SENSOR
  void set_tx_packets_sensor(sensor::Sensor *s) { this->tx_sensor_ = s; }
  void set_rx_packets_sensor(sensor::Sensor *s) { this->rx_sensor_ = s; }
  void set_held_back_sensor(sensor::Sensor *s) { this->held_sensor_ = s; }
  void set_tx_errors_sensor(sensor::Sensor *s) { this->err_sensor_ = s; }
  void set_call_id_sensor(sensor::Sensor *s) { this->id_sensor_ = s; }
  void set_floor_key_sensor(sensor::Sensor *s) { this->floor_sensor_ = s; }
  void set_members_sensor(sensor::Sensor *s) { this->members_sensor_ = s; }
#endif
#ifdef USE_BINARY_SENSOR
  void set_talking_binary_sensor(binary_sensor::BinarySensor *b) { this->talking_bs_ = b; }
  void set_in_call_binary_sensor(binary_sensor::BinarySensor *b) { this->call_bs_ = b; }
  void set_remote_holding_binary_sensor(binary_sensor::BinarySensor *b) { this->remote_bs_ = b; }
  void set_answered_binary_sensor(binary_sensor::BinarySensor *b) { this->answered_bs_ = b; }
  void set_busy_binary_sensor(binary_sensor::BinarySensor *b) { this->busy_bs_ = b; }
#endif

 protected:
  bool door_role_() const { return this->role_ == VoiceRole::DOOR; }
  void on_mic_(const std::vector<uint8_t> &data);
  void on_play_(const int16_t *pcm, size_t n);
  ::aikos::voice::Verdict policy_(const ::aikos::voice::Addr &from, uint32_t now);
  void loop_door_(uint32_t now);
  void loop_key_(uint32_t now);
  void set_mic_(bool on);
  void talk_(bool on, uint32_t now);
  void publish_(uint32_t now);
  bool resolve_(const std::string &host, ::aikos::voice::Addr &out) const;

  VoiceRole role_{VoiceRole::DOOR};
  ::aikos::voice::LinkConfig link_cfg_;
  ::aikos::voice::CallConfig call_cfg_;
  ::aikos::voice::Link link_;
  ::aikos::voice::UdpTransport udp_;
  ::aikos::voice::DoorCall door_;
  ::aikos::voice::KeyCall key_;
  ::aikos::voice::VoiceGate mic_gate_, rx_gate_;  // speech in our own mic, speech arriving from the other end
  microphone::MicrophoneSource *mic_{nullptr};
  speaker::Speaker *speaker_{nullptr};
  uint16_t port_{5004};
  std::string transcriber_, door_host_;
  ::aikos::voice::Addr door_addr_;
  bool highpass_{true}, hear_visitor_{false}, record_{false}, mic_on_{false};
  int own_octet_{-1};  // the last octet of this device's IPv4 address, for floor_key
  float gain_{4.0f};
  uint32_t mic_start_mute_samples_{0}, mute_left_{0};
  ::aikos::voice::Biquad hp_;
  ::aikos::voice::Limiter limiter_;
  ::aikos::voice::Edge call_edge_, talk_edge_;
  uint32_t floor_ip_{0}, mic_voice_seen_{0}, rx_voice_seen_{0}, last_publish_{0};
  int floor_key_{0};

  Trigger<> talk_start_trigger_, talk_stop_trigger_, call_start_trigger_, call_end_trigger_;
#ifdef USE_SENSOR
  sensor::Sensor *tx_sensor_{nullptr}, *rx_sensor_{nullptr}, *held_sensor_{nullptr}, *err_sensor_{nullptr};
  sensor::Sensor *id_sensor_{nullptr}, *floor_sensor_{nullptr}, *members_sensor_{nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *talking_bs_{nullptr}, *call_bs_{nullptr}, *remote_bs_{nullptr};
  binary_sensor::BinarySensor *answered_bs_{nullptr}, *busy_bs_{nullptr};
#endif
};

// ── actions and conditions ───────────────────────────────────────────────────────────────────────────────────────
#define AIKOS_VOICE_SIMPLE_ACTION(NAME, CALL) \
  template<typename... Ts> class NAME : public Action<Ts...>, public Parented<AikosVoice> { \
   public: \
    void play(const Ts &...x) override { this->parent_->CALL; } \
  };
AIKOS_VOICE_SIMPLE_ACTION(RingAction, ring())
AIKOS_VOICE_SIMPLE_ACTION(VisitorSpeakAction, visitor_speak())
AIKOS_VOICE_SIMPLE_ACTION(JoinAction, join())
AIKOS_VOICE_SIMPLE_ACTION(EndAction, end_call())
#undef AIKOS_VOICE_SIMPLE_ACTION

template<typename... Ts> class KeyHoldAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, host)
  TEMPLATABLE_VALUE(bool, held)
  void play(const Ts &...x) override { this->parent_->key_hold(this->host_.value(x...), this->held_.value(x...)); }
};
template<typename... Ts> class KeyInCallAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, host)
  TEMPLATABLE_VALUE(bool, in_call)
  void play(const Ts &...x) override { this->parent_->key_in_call(this->host_.value(x...), this->in_call_.value(x...)); }
};
template<typename... Ts> class HoldAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(bool, held)
  void play(const Ts &...x) override { this->parent_->hold(this->held_.value(x...)); }
};
template<typename... Ts> class DoorCallAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(bool, on)
  TEMPLATABLE_VALUE(uint32_t, call_id)
  TEMPLATABLE_VALUE(bool, answered)
  void play(const Ts &...x) override {
    this->parent_->door_call(this->on_.value(x...), this->call_id_.value(x...), this->answered_.value(x...));
  }
};
template<typename... Ts> class FloorKeyAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(int, key)
  void play(const Ts &...x) override { this->parent_->floor_key(this->key_.value(x...)); }
};
template<typename... Ts> class StringAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, value)
  void set_setter(void (AikosVoice::*f)(const std::string &)) { this->f_ = f; }
  void play(const Ts &...x) override { (this->parent_->*this->f_)(this->value_.value(x...)); }

 protected:
  void (AikosVoice::*f_)(const std::string &){nullptr};
};
template<typename... Ts> class BoolAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(bool, value)
  void set_setter(void (AikosVoice::*f)(bool)) { this->f_ = f; }
  void play(const Ts &...x) override { (this->parent_->*this->f_)(this->value_.value(x...)); }

 protected:
  void (AikosVoice::*f_)(bool){nullptr};
};
template<typename... Ts> class AllowSourceAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, host)
  TEMPLATABLE_VALUE(uint32_t, duration)
  void play(const Ts &...x) override {
    this->parent_->allow_source(this->host_.value(x...), this->duration_.value(x...));
  }
};
template<typename... Ts> class SetMicGainAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(float, gain)
  void play(const Ts &...x) override { this->parent_->set_mic_gain(this->gain_.value(x...)); }
};
template<typename... Ts> class SetDurationAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(uint32_t, value)
  void set_setter(void (AikosVoice::*f)(uint32_t)) { this->f_ = f; }
  void play(const Ts &...x) override { (this->parent_->*this->f_)(this->value_.value(x...)); }

 protected:
  void (AikosVoice::*f_)(uint32_t){nullptr};
};

template<typename... Ts> class IsTalkingCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->is_talking(); }
};
template<typename... Ts> class InCallCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->in_call(); }
};
template<typename... Ts> class RemoteHoldingCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->remote_holding(); }
};

}  // namespace esphome::aikos_voice
