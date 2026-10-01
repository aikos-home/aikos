#include "aikos_voice.h"

#include <esp_random.h>
#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/components/network/util.h"

namespace esphome::aikos_voice {

static const char *const TAG = "aikos_voice";

void AikosVoice::setup() {
  this->link_.configure(this->cfg_);
  this->link_.set_ssrc(esp_random(), (uint16_t) esp_random(), esp_random());
  this->link_.set_sink([this](const int16_t *pcm, size_t n) { this->play_(pcm, n); });
  this->link_.on_conversation_end = [this]() {
    ESP_LOGI(TAG, "conversation over (%u s without audio)", (unsigned) (this->cfg_.idle_ms / 1000));
    if (this->speaker_ != nullptr)
      this->speaker_->stop();
  };
  this->hp_ = ::aikos::voice::Biquad::highpass(120.0f, (float) ::aikos::voice::RATE);  // knocks, handling noise, DC out
  if (this->mic_ != nullptr)
    this->mic_->add_data_callback([this](const std::vector<uint8_t> &data) { this->on_mic_(data); });
}

void AikosVoice::loop() {
  if (!this->udp_.ready()) {  // the socket waits for the network
    if (!network::is_connected() || !this->udp_.begin(this->port_))
      return;
    this->link_.set_transport(&this->udp_);
    this->set_transcriber(this->transcriber_);
    ESP_LOGI(TAG, "voice link on UDP %u (role %s)", this->port_, this->cfg_.role == VoiceRole::DOOR ? "door" : "room");
  }
  this->link_.loop(millis());
  this->publish_();
}

void AikosVoice::dump_config() {
  ESP_LOGCONFIG(TAG,
                "aikos voice (v1):\n"
                "  Role: %s\n"
                "  Port: %u\n"
                "  Idle timeout: %u s\n"
                "  Pre-buffer: %u ms, hold max: %u s\n"
                "  Latch frames: %d, keepalive: %u s\n"
                "  Mic gain: %.1f, high-pass: %s\n"
                "  Transcriber: %s",
                this->cfg_.role == VoiceRole::DOOR ? "door" : "room", this->port_,
                (unsigned) (this->cfg_.idle_ms / 1000), (unsigned) this->cfg_.prebuffer_ms,
                (unsigned) (this->cfg_.hold_max_ms / 1000), this->cfg_.latch_frames,
                (unsigned) (this->cfg_.keepalive_ms / 1000), this->gain_, YESNO(this->highpass_),
                this->transcriber_.empty() ? "off" : this->transcriber_.c_str());
}

// microphone task: 16-bit little-endian mono -> high-pass, gain, limiter -> link
void AikosVoice::on_mic_(const std::vector<uint8_t> &data) {
  if (!this->link_.talking())
    return;
  const size_t n = data.size() / 2;
  int16_t out[256];
  size_t k = 0;
  for (size_t i = 0; i < n; i++) {
    float v = (float) (int16_t) (data[2 * i] | (data[2 * i + 1] << 8));
    if (this->highpass_)
      v = this->hp_.process(v);
    v = this->limiter_.process(v * this->gain_);
    out[k++] = (int16_t) (v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : v);
    if (k == 256) {
      this->link_.push(out, k);
      k = 0;
    }
  }
  if (k > 0)
    this->link_.push(out, k);
}

void AikosVoice::play_(const int16_t *pcm, size_t n) {
  if (this->speaker_ == nullptr)
    return;
  if (!this->speaker_->is_running())
    this->speaker_->start();
  this->speaker_->play((const uint8_t *) pcm, n * 2, 0);
}

void AikosVoice::talk(bool on) {
  if (on == this->link_.talking())
    return;
  this->link_.talk(on, millis());
  if (this->mic_ != nullptr) {
    if (on)
      this->mic_->start();
    else
      this->mic_->stop();
  }
  ESP_LOGI(TAG, "talk %s", on ? "on" : "off (drain + end packet)");
  (on ? this->talk_start_trigger_ : this->talk_stop_trigger_).trigger();
}

void AikosVoice::remote_hold(bool held, const std::string &peer_host) {
  ::aikos::voice::Addr a;
  if (held && !peer_host.empty() && !::aikos::voice::resolve(peer_host, this->port_, a)) {
    ESP_LOGW(TAG, "remote_hold: bad peer '%s'", peer_host.c_str());
    return;
  }
  this->link_.remote_hold(held, a, millis());
  ESP_LOGI(TAG, "peer %s%s", held ? "holds" : "released", held && a.valid() ? (" (" + peer_host + ")").c_str() : "");
}

void AikosVoice::set_peer(const std::string &host, int port) {
  ::aikos::voice::Addr a;
  if (!::aikos::voice::resolve(host + ":" + std::to_string(port > 0 ? port : this->port_), this->port_, a)) {
    ESP_LOGW(TAG, "set_peer: bad peer '%s'", host.c_str());
    return;
  }
  this->link_.set_peer(a, millis());
  if (this->speaker_ != nullptr)
    this->speaker_->start();
  ESP_LOGI(TAG, "peer %s", ::aikos::voice::to_string(a).c_str());
}

void AikosVoice::end_conversation() {
  this->talk(false);
  this->link_.clear_peer();
  if (this->speaker_ != nullptr)
    this->speaker_->stop();
}

void AikosVoice::set_transcriber(const std::string &host_port) {
  this->transcriber_ = host_port;
  ::aikos::voice::Addr a;
  if (::aikos::voice::resolve(host_port, 0, a)) {
    this->link_.set_tap(a);
    ESP_LOGI(TAG, "transcriber copy to %s", host_port.c_str());
  } else {
    this->link_.set_tap(::aikos::voice::Addr{});
    if (!host_port.empty())
      ESP_LOGW(TAG, "transcriber address must be host:port, got '%s'", host_port.c_str());
  }
}

void AikosVoice::set_accept(bool on) { this->link_.set_accept(on); }

void AikosVoice::allow_source(const std::string &host, uint32_t ms) {
  ::aikos::voice::Addr a;
  if (::aikos::voice::resolve(host, this->port_, a))
    this->link_.allow_source(a, millis() + ms);
}

void AikosVoice::publish_() {
  const bool talking = this->link_.talking(), conv = this->link_.in_conversation(),
             remote = this->link_.remote_holding();
  if (conv != this->was_conversation_) {
    this->was_conversation_ = conv;
    if (conv)
      this->conversation_start_trigger_.trigger();
  }
#ifdef USE_BINARY_SENSOR
  if (this->talking_bs_ != nullptr && (talking != this->was_talking_ || !this->talking_bs_->has_state()))
    this->talking_bs_->publish_state(talking);
  if (this->conv_bs_ != nullptr && (conv != this->conv_bs_->state || !this->conv_bs_->has_state()))
    this->conv_bs_->publish_state(conv);
  if (this->remote_bs_ != nullptr && (remote != this->was_remote_ || !this->remote_bs_->has_state()))
    this->remote_bs_->publish_state(remote);
#endif
  this->was_talking_ = talking;
  this->was_remote_ = remote;
#ifdef USE_SENSOR
  const uint32_t now = millis();
  if (now - this->last_publish_ >= 5000) {
    this->last_publish_ = now;
    const auto &s = this->link_.stats;
    if (this->tx_sensor_ != nullptr)
      this->tx_sensor_->publish_state(s.tx_packets);
    if (this->rx_sensor_ != nullptr)
      this->rx_sensor_->publish_state(s.rx_packets);
    if (this->held_sensor_ != nullptr)
      this->held_sensor_->publish_state(s.held_back);
    if (this->err_sensor_ != nullptr)
      this->err_sensor_->publish_state(s.tx_errors + s.overruns);
  }
#endif
}

}  // namespace esphome::aikos_voice
