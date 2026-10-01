// aikos_voice: ESPHome component around the shared voice link (voice_core.h), used by the door talk computer and the
// RoomKeys. Behaviour = voice v1, see voice_core.h. Everything that is not the voice link itself (screens, buttons, HA
// glue) stays in the device configs, so it can change as often as it likes without touching this.
#pragma once

#include <string>
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/components/microphone/microphone_source.h"
#include "esphome/components/speaker/speaker.h"
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
  // configuration
  void set_microphone_source(microphone::MicrophoneSource *m) { this->mic_ = m; }
  void set_speaker(speaker::Speaker *s) { this->speaker_ = s; }
  void set_role(VoiceRole r) { this->cfg_.role = r; }
  void set_port(uint16_t p) { this->port_ = p; }
  void set_idle_timeout(uint32_t ms) { this->cfg_.idle_ms = ms; }
  void set_prebuffer(uint32_t ms) { this->cfg_.prebuffer_ms = ms; }
  void set_hold_max(uint32_t ms) { this->cfg_.hold_max_ms = ms; }
  void set_latch_frames(int n) { this->cfg_.latch_frames = n; }
  void set_keepalive(uint32_t ms) { this->cfg_.keepalive_ms = ms; }
  void set_highpass(bool on) { this->highpass_ = on; }
  void set_initial_transcriber(const std::string &a) { this->transcriber_ = a; }

  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }
  void setup() override;
  void loop() override;
  void dump_config() override;

  // ── what devices and HA do with it ───────────────────────────────────────────────────────────────────────────
  void talk(bool on);                                         // local push-to-talk
  void remote_hold(bool held, const std::string &peer_host);  // a peer's button (door role: forwarded by HA)
  void set_peer(const std::string &host, int port);
  void end_conversation();
  void set_transcriber(const std::string &host_port);         // "" = off
  void set_accept(bool on);                                   // room role: audio in only during a conversation
  void allow_source(const std::string &host, uint32_t ms);    // a trusted stream (e.g. TTS later) for ms
  void set_mic_gain(float g) { this->gain_ = g; }
  float get_mic_gain() const { return this->gain_; }

  bool is_talking() const { return this->link_.talking(); }
  bool in_conversation() const { return this->link_.in_conversation(); }
  bool remote_holding() const { return this->link_.remote_holding(); }
  const ::aikos::voice::Stats &stats() const { return this->link_.stats; }

  Trigger<> *get_talk_start_trigger() { return &this->talk_start_trigger_; }
  Trigger<> *get_talk_stop_trigger() { return &this->talk_stop_trigger_; }
  Trigger<> *get_conversation_start_trigger() { return &this->conversation_start_trigger_; }
  Trigger<> *get_conversation_end_trigger() { return &this->conversation_end_trigger_; }

#ifdef USE_SENSOR
  void set_tx_packets_sensor(sensor::Sensor *s) { this->tx_sensor_ = s; }
  void set_rx_packets_sensor(sensor::Sensor *s) { this->rx_sensor_ = s; }
  void set_held_back_sensor(sensor::Sensor *s) { this->held_sensor_ = s; }
  void set_tx_errors_sensor(sensor::Sensor *s) { this->err_sensor_ = s; }
#endif
#ifdef USE_BINARY_SENSOR
  void set_talking_binary_sensor(binary_sensor::BinarySensor *b) { this->talking_bs_ = b; }
  void set_in_conversation_binary_sensor(binary_sensor::BinarySensor *b) { this->conv_bs_ = b; }
  void set_remote_holding_binary_sensor(binary_sensor::BinarySensor *b) { this->remote_bs_ = b; }
#endif

 protected:
  void on_mic_(const std::vector<uint8_t> &data);
  void play_(const int16_t *pcm, size_t n);
  void publish_();

  ::aikos::voice::Config cfg_;
  ::aikos::voice::Link link_;
  ::aikos::voice::UdpTransport udp_;
  microphone::MicrophoneSource *mic_{nullptr};
  speaker::Speaker *speaker_{nullptr};
  uint16_t port_{5004};
  std::string transcriber_;
  bool highpass_{true};
  float gain_{4.0f};
  ::aikos::voice::Biquad hp_;
  ::aikos::voice::Limiter limiter_;
  bool was_talking_{false}, was_conversation_{false}, was_remote_{false};
  uint32_t last_publish_{0};

  Trigger<> talk_start_trigger_, talk_stop_trigger_, conversation_start_trigger_, conversation_end_trigger_;
#ifdef USE_SENSOR
  sensor::Sensor *tx_sensor_{nullptr}, *rx_sensor_{nullptr}, *held_sensor_{nullptr}, *err_sensor_{nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *talking_bs_{nullptr}, *conv_bs_{nullptr}, *remote_bs_{nullptr};
#endif
};

// ── actions and conditions ───────────────────────────────────────────────────────────────────────────────────────
template<typename... Ts> class TalkStartAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->talk(true); }
};
template<typename... Ts> class TalkStopAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->talk(false); }
};
template<typename... Ts> class RemoteHoldAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(bool, held)
  TEMPLATABLE_VALUE(std::string, peer_host)
  void play(const Ts &...x) override {
    this->parent_->remote_hold(this->held_.value(x...), this->peer_host_.value(x...));
  }
};
template<typename... Ts> class SetPeerAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, host)
  TEMPLATABLE_VALUE(int, port)
  void play(const Ts &...x) override { this->parent_->set_peer(this->host_.value(x...), this->port_.value(x...)); }
};
template<typename... Ts> class EndAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->end_conversation(); }
};
template<typename... Ts> class SetTranscriberAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(std::string, address)
  void play(const Ts &...x) override { this->parent_->set_transcriber(this->address_.value(x...)); }
};
template<typename... Ts> class SetAcceptAction : public Action<Ts...>, public Parented<AikosVoice> {
 public:
  TEMPLATABLE_VALUE(bool, accept)
  void play(const Ts &...x) override { this->parent_->set_accept(this->accept_.value(x...)); }
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

template<typename... Ts> class IsTalkingCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->is_talking(); }
};
template<typename... Ts> class InConversationCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->in_conversation(); }
};
template<typename... Ts> class RemoteHoldingCondition : public Condition<Ts...>, public Parented<AikosVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->remote_holding(); }
};

}  // namespace esphome::aikos_voice
