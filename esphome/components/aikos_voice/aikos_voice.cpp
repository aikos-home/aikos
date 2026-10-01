#include "aikos_voice.h"

#include <cmath>
#include <cstdlib>
#include <cstring>
#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/components/network/util.h"

namespace esphome::aikos_voice {

static const char *const TAG = "aikos_voice";
using ::aikos::voice::Addr;
using ::aikos::voice::CallEnd;
using ::aikos::voice::Role;
using ::aikos::voice::Verdict;

void AikosVoice::setup() {
  this->link_.configure(this->link_cfg_);
  this->link_.set_ssrc(random_uint32(), (uint16_t) random_uint32(), random_uint32());  // hardware random on the chip
  this->link_.set_sink([this](const int16_t *pcm, size_t n) { this->on_play_(pcm, n); });
  this->link_.set_policy([this](const Addr &from, uint32_t now) { return this->policy_(from, now); });
  this->door_.configure(this->call_cfg_);
  this->door_.seed_id(random_uint32());  // call ids never repeat across reboots (RoomKey review)
  this->key_.configure(this->call_cfg_);
  this->hp_ = ::aikos::voice::Biquad::highpass(120.0f, (float) ::aikos::voice::RATE);  // knocks, handling noise, DC out
#ifdef USE_MICROPHONE
  if (this->mic_ != nullptr)
    this->mic_->add_data_callback([this](const std::vector<uint8_t> &data) { this->on_mic_(data); });
#endif
}

void AikosVoice::loop() {
  const uint32_t now = millis();
  if (!this->udp_.ready()) {  // the socket waits for the network
    if (!network::is_connected() || !this->udp_.begin(this->port_))
      return;
    this->link_.set_transport(&this->udp_);
    this->set_transcriber(this->transcriber_);
    if (!this->door_role_())
      this->set_door(this->door_host_);
    ESP_LOGI(TAG, "voice link on UDP %u (role %s)", this->port_, this->door_role_() ? "door" : "room");
  }
  if (this->door_role_())
    this->loop_door_(now);
  else
    this->loop_key_(now);
  this->link_.loop(now);
  this->publish_(now);
}

// ── the door ────────────────────────────────────────────────────────────────────────────────────────────────────────
void AikosVoice::loop_door_(uint32_t now) {
  if (this->mic_gate_.voiced_since(this->mic_voice_seen_ + 1)) {  // the visitor (or anyone at the door) speaks
    this->mic_voice_seen_ = this->mic_gate_.last_voice_ms();
    this->door_.speech(Role::DOOR, now);
  }
  if (this->rx_gate_.voiced_since(this->rx_voice_seen_ + 1)) {  // the room speaks through the door speaker
    this->rx_voice_seen_ = this->rx_gate_.last_voice_ms();
    this->door_.speech(Role::ROOM, now);
  }
  this->door_.loop(now);
  const int edge = this->call_edge_.update(this->door_.active());
  if (edge > 0) {
    ESP_LOGI(TAG, "call %u starts: %s", (unsigned) this->door_.id(), ::aikos::voice::to_string(this->door_.started_by()));
    this->set_mic_(true);  // R17.2: the door mic is open for the whole call
    this->call_start_trigger_.trigger();
  } else if (edge < 0) {
    ESP_LOGI(TAG, "call %u ends: %s", (unsigned) this->door_.id(), ::aikos::voice::to_string(this->door_.ended_by()));
    this->set_mic_(false);
#ifdef USE_SPEAKER
    if (this->speaker_ != nullptr)
      this->speaker_->stop();
#endif
    this->call_end_trigger_.trigger(::aikos::voice::to_string(this->door_.ended_by()));
  }
  this->talk_(this->door_.mic_open(), now);
  this->link_.send_to_targets(this->door_.mic_to_keys(now));  // R17.16: muted towards the keys while the speaker plays
  const Addr *f = this->door_.floor();
  const uint32_t ip = f != nullptr ? f->ip : 0;
  if (ip != this->floor_ip_) {
    this->floor_ip_ = ip;
    if (f != nullptr) {
      this->link_.flush(*f, now);  // its first words arrived a moment before its "holds"
      ESP_LOGI(TAG, "floor: %s", ::aikos::voice::to_string(*f).c_str());
    } else {
      ESP_LOGI(TAG, "floor: nobody");
    }
  }
}

void AikosVoice::ring() {
  this->door_.ring(millis());
  ESP_LOGI(TAG, "ring");
}
void AikosVoice::visitor_speak() {
  this->door_.visitor_speak(millis());
  ESP_LOGI(TAG, "the visitor pressed Sprechen");
}
void AikosVoice::key_hold(const std::string &host, bool held) {
  Addr a;
  if (!this->resolve_(host, a)) {
    ESP_LOGW(TAG, "key_hold: bad key address '%s'", host.c_str());
    return;
  }
  this->door_.hold(a, held, millis());
}
void AikosVoice::key_in_call(const std::string &host, bool in) {
  Addr a;
  if (!this->resolve_(host, a)) {
    ESP_LOGW(TAG, "key_in_call: bad key address '%s'", host.c_str());
    return;
  }
  this->door_.key_in_call(a, in, millis());
}
void AikosVoice::set_keys(const std::string &hosts) {
  Addr list[::aikos::voice::Link::MAX_TARGETS];
  int n = 0;
  size_t pos = 0;
  while (pos <= hosts.size() && n < ::aikos::voice::Link::MAX_TARGETS) {
    size_t comma = hosts.find(',', pos);
    if (comma == std::string::npos)
      comma = hosts.size();
    std::string h = hosts.substr(pos, comma - pos);
    while (!h.empty() && h.front() == ' ')
      h.erase(0, 1);
    while (!h.empty() && h.back() == ' ')
      h.pop_back();
    if (!h.empty()) {
      if (this->resolve_(h, list[n]))
        n++;
      else
        ESP_LOGW(TAG, "set_keys: bad key address '%s'", h.c_str());
    }
    pos = comma + 1;
  }
  this->link_.set_targets(list, n, millis());
  ESP_LOGI(TAG, "%d key(s) get the door's audio during a call", n);
}

// ── a room key ──────────────────────────────────────────────────────────────────────────────────────────────────────
void AikosVoice::loop_key_(uint32_t now) {
  if (this->mic_gate_.voiced_since(this->mic_voice_seen_ + 1)) {
    this->mic_voice_seen_ = this->mic_gate_.last_voice_ms();
    this->key_.speech(Role::ROOM, now);
  }
  if (this->rx_gate_.voiced_since(this->rx_voice_seen_ + 1)) {
    this->rx_voice_seen_ = this->rx_gate_.last_voice_ms();
    this->key_.speech(Role::DOOR, now);
  }
  this->key_.loop(now);
  const int edge = this->call_edge_.update(this->key_.in_call());
  if (edge > 0) {
    ESP_LOGI(TAG, "in the door's call");
    this->call_start_trigger_.trigger();
  } else if (edge < 0) {
    ESP_LOGI(TAG, "left the call: %s", ::aikos::voice::to_string(this->key_.left_by()));
#ifdef USE_SPEAKER
    if (this->speaker_ != nullptr)
      this->speaker_->stop();
#endif
    this->call_end_trigger_.trigger(::aikos::voice::to_string(this->key_.left_by()));
  }
  this->set_mic_(this->key_.mic_open() || this->record_);
  this->talk_(this->key_.sends() || this->record_, now);  // a busy key sends nothing (RoomKey review)
  this->link_.send_to_targets(!this->record_);           // a test recording never reaches the door
}

void AikosVoice::hold(bool held) {
  this->key_.hold(held, millis());
  if (this->key_.busy())
    ESP_LOGI(TAG, "busy: another key has the floor");
}
void AikosVoice::join() { this->key_.join(millis()); }
void AikosVoice::door_call(bool on, uint32_t id, bool answered) { this->key_.door_call(on, id, answered, millis()); }
void AikosVoice::floor_key(int last_octet) {
  if (this->own_octet_ < 0)
    this->own_octet_ = this->find_own_octet_();
  this->floor_key_ = last_octet;
  this->key_.floor_taken(last_octet != 0 && last_octet != this->own_octet_);
}
void AikosVoice::set_door(const std::string &host_port) {
  this->door_host_ = host_port;
  if (!this->udp_.ready())
    return;  // applied when the socket opens
  Addr a;
  if (!host_port.empty() && !this->resolve_(host_port, a)) {
    ESP_LOGW(TAG, "set_door: bad address '%s'", host_port.c_str());
    return;
  }
  this->door_addr_ = a;
  this->link_.set_target(a, millis());
  if (a.valid())
    ESP_LOGI(TAG, "door at %s", ::aikos::voice::to_string(a).c_str());
}
void AikosVoice::record(bool on) {
  this->record_ = on;
  ESP_LOGI(TAG, "test recording %s (transcriber only)", on ? "on" : "off");
}

// ── both ────────────────────────────────────────────────────────────────────────────────────────────────────────────
Verdict AikosVoice::policy_(const Addr &from, uint32_t now) {
  (void) now;
  if (this->door_role_()) {
    if (!this->door_.active())
      return Verdict::DROP;
    return this->door_.plays(from) ? Verdict::PLAY : Verdict::HOLD;  // held briefly: its "holds" may still be coming
  }
  return from.ip == this->door_addr_.ip && this->key_.plays_door(this->hear_visitor_) ? Verdict::PLAY : Verdict::DROP;
}

void AikosVoice::speech(Role side) {
  if (this->door_role_())
    this->door_.speech(side, millis());
  else
    this->key_.speech(side, millis());
}

void AikosVoice::end_call() {
  if (this->door_role_())
    this->door_.end(CallEnd::EXTERNAL, millis());
  else
    this->key_.front_door(millis());
}

void AikosVoice::set_call_silence_end(uint32_t ms) {
  this->call_cfg_.silence_end_ms = ms;
  this->door_.configure(this->call_cfg_);
  this->key_.configure(this->call_cfg_);
}
void AikosVoice::set_call_max_length(uint32_t ms) {
  this->call_cfg_.max_length_ms = ms;
  this->door_.configure(this->call_cfg_);
  this->key_.configure(this->call_cfg_);
}

std::string AikosVoice::member_octets() const {
  ::aikos::voice::Addr list[::aikos::voice::DoorCall::MAX_KEYS];
  const int n = this->door_.member_list(list, ::aikos::voice::DoorCall::MAX_KEYS);
  std::string out;
  for (int i = 0; i < n; i++)
    out += (out.empty() ? "" : ",") + std::to_string((list[i].ip >> 24) & 0xFF);  // network order, little-endian chip
  return out;
}

bool AikosVoice::in_call() const { return this->door_role_() ? this->door_.active() : this->key_.in_call(); }

int AikosVoice::floor_last_octet() const {
  const Addr *f = this->door_.floor();
  return f != nullptr ? (int) ((f->ip >> 24) & 0xFF) : 0;  // network byte order on a little-endian chip
}

void AikosVoice::set_transcriber(const std::string &host_port) {
  this->transcriber_ = host_port;
  Addr a;
  if (::aikos::voice::resolve(host_port, 0, a)) {
    this->link_.set_tap(a);
    ESP_LOGI(TAG, "transcriber copy to %s", host_port.c_str());
  } else {
    this->link_.set_tap(Addr{});
    if (!host_port.empty())
      ESP_LOGW(TAG, "transcriber address must be host:port, got '%s'", host_port.c_str());
  }
}

void AikosVoice::allow_source(const std::string &host, uint32_t ms) {
  Addr a;
  if (this->resolve_(host, a))
    this->link_.allow_source(a, millis() + ms);
}

int AikosVoice::find_own_octet_() const {
  char buf[network::IP_ADDRESS_BUFFER_SIZE];
  for (auto &ip : network::get_ip_addresses()) {
    if (!ip.is_set() || !ip.is_ip4())
      continue;
    const char *s = ip.str_to(buf);
    const char *dot = strrchr(s, '.');
    if (dot != nullptr)
      return atoi(dot + 1);
  }
  // a host build has no network interface component: the address this device sends to the door from
  const uint32_t ip = ::aikos::voice::local_ip_toward(this->door_addr_);
  return ip != 0 ? (int) ((ip >> 24) & 0xFF) : -1;  // network byte order on a little-endian machine
}

bool AikosVoice::resolve_(const std::string &host, Addr &out) const {
  return ::aikos::voice::resolve(host, this->port_, out);
}

void AikosVoice::set_mic_(bool on) {
  if (on == this->mic_on_.load())
    return;
  if (on)
    this->mute_left_ = this->mic_start_mute_samples_;
  this->mic_on_.store(on);  // push_samples() follows this; a real mic is started and stopped
#ifdef USE_MICROPHONE
  if (this->mic_ != nullptr) {
    if (on)
      this->mic_->start();
    else
      this->mic_->stop();
  }
#endif
}

void AikosVoice::talk_(bool on, uint32_t now) {
  const int edge = this->talk_edge_.update(on);
  if (edge == 0)
    return;
  this->link_.talk(on, now);
  ESP_LOGI(TAG, "talk %s", on ? "on" : "off (drain + end packet)");
  (on ? this->talk_start_trigger_ : this->talk_stop_trigger_).trigger();
}

// the mic path, from the microphone task or push_samples(): sample(i) -> high-pass, gain, limiter -> link; its level ->
// the speech detector. Blocks of any length: the link takes any count, the gate collects whole 20 ms blocks.
template<typename Sample> void AikosVoice::process_(size_t n, Sample sample) {
  int16_t out[256];
  size_t k = 0;
  auto flush = [&]() {
    this->link_.push(out, k);
    k = 0;
  };
  // the speech detector sees whole 20 ms blocks: a 2-sample rest of a callback would read as "silence" and pull its
  // noise floor down to -100 dBFS (door 0.7.1 diagnostics)
  auto gate = [&](int16_t s) {
    this->gate_acc_ += (double) s * s;
    if (++this->gate_n_ < (uint32_t) ::aikos::voice::FRAME)
      return;
    const double ms = this->gate_acc_ / this->gate_n_ / (32768.0 * 32768.0);
    const float db = ms < 1e-12 ? -120.0f : (float) (10.0 * log10(ms));
    this->gate_acc_ = 0.0;
    this->gate_n_ = 0;
    this->mic_gate_.note(db, millis());
    if (db > this->mic_block_max_.load(std::memory_order_relaxed))
      this->mic_block_max_.store(db, std::memory_order_relaxed);
  };
  for (size_t i = 0; i < n; i++) {
    float v = (float) sample(i);
    if (this->mute_left_ > 0) {  // some boards pop when the mic starts (RoomKey must-have)
      this->mute_left_--;
      v = 0.0f;
    }
    if (this->highpass_)
      v = this->hp_.process(v);
    v = this->limiter_.process(v * this->gain_);
    out[k] = (int16_t) (v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : v);
    gate(out[k++]);
    if (k == 256)
      flush();
  }
  if (k > 0)
    flush();
}

#ifdef USE_MICROPHONE
// microphone task: 16-bit little-endian mono
void AikosVoice::on_mic_(const std::vector<uint8_t> &data) {
  const uint8_t *d = data.data();
  this->process_(data.size() / 2, [d](size_t i) { return (int16_t) (d[2 * i] | (d[2 * i + 1] << 8)); });
}
#endif

void AikosVoice::push_samples(const int16_t *pcm, size_t n) {
#ifdef USE_MICROPHONE
  if (this->mic_ != nullptr) {  // two producers would race in the link's ring buffer
    if (!this->push_warned_)
      ESP_LOGW(TAG, "push_samples: ignored, this device has a microphone");
    this->push_warned_ = true;
    return;
  }
#endif
  if (pcm == nullptr || n == 0 || !this->mic_on_.load())
    return;  // like a real mic, which is stopped while the call has it closed
  this->process_(n, [pcm](size_t i) { return pcm[i]; });
}

void AikosVoice::on_play_(const int16_t *pcm, size_t n) {
  const uint32_t now = millis();
  if (this->door_role_())
    this->door_.door_played(now);  // R17.16: the door mic stays muted towards the keys a little longer
  this->rx_gate_.note(::aikos::voice::level_db(pcm, (int) n), now);
#ifdef USE_SPEAKER
  if (this->speaker_ == nullptr)
    return;
  if (!this->speaker_->is_running())
    this->speaker_->start();
  this->speaker_->play((const uint8_t *) pcm, n * 2, 0);
#endif
}

void AikosVoice::publish_(uint32_t now) {
#ifdef USE_BINARY_SENSOR
  auto put = [](binary_sensor::BinarySensor *b, bool v) {
    if (b != nullptr && (!b->has_state() || b->state != v))
      b->publish_state(v);
  };
  put(this->talking_bs_, this->link_.talking());
  put(this->call_bs_, this->in_call());
  put(this->remote_bs_, this->remote_holding());
  put(this->answered_bs_, this->door_role_() && this->door_.answered());
  put(this->busy_bs_, !this->door_role_() && this->key_.busy());
  put(this->speech_bs_, this->mic_on_.load() && this->mic_gate_.voiced_since(now - 500));
#endif
#ifdef USE_SENSOR
  auto put_num = [](sensor::Sensor *s, float v) {
    if (s != nullptr && (!s->has_state() || s->state != v))
      s->publish_state(v);
  };
  // door: the id while a call is on, 0 when none (sent every second to the keys: a sensor fires on every packet,
  // a binary sensor only on change, so this number is also the keys' "the door is still there")
  const uint32_t id = this->door_role_() ? (this->door_.active() ? this->door_.id() : 0) : this->key_.door_id();
  put_num(this->id_sensor_, (float) id);  // 24 bits: exact as a float
  put_num(this->floor_sensor_, (float) this->floor_last_octet());
  put_num(this->members_sensor_, (float) this->door_.members());
  put_num(this->key_state_sensor_, (float) this->key_state());
  if (now - this->last_diag_ >= 1000) {  // diagnostics of the speech detector on our own mic, once a second
    this->last_diag_ = now;
    if (this->speech_floor_sensor_ != nullptr)
      this->speech_floor_sensor_->publish_state(this->mic_gate_.floor_db());
    if (this->speech_level_sensor_ != nullptr)
      this->speech_level_sensor_->publish_state(this->mic_block_max_.exchange(-120.0f));
  }
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

void AikosVoice::dump_config() {
  ESP_LOGCONFIG(TAG,
                "aikos voice (v2):\n"
                "  Role: %s\n"
                "  Port: %u\n"
                "  Call: silence end %u s, max length %u s, mute tail %u ms, hold refresh %u ms\n"
                "  Pre-buffer: %u ms, latch frames: %d, keepalive: %u s\n"
                "  Mic gain: %.1f, high-pass: %s, start mute: %u ms\n"
                "  Transcriber: %s",
                this->door_role_() ? "door" : "room", this->port_, (unsigned) (this->call_cfg_.silence_end_ms / 1000),
                (unsigned) (this->call_cfg_.max_length_ms / 1000), (unsigned) this->call_cfg_.mute_tail_ms,
                (unsigned) this->call_cfg_.hold_refresh_ms, (unsigned) this->link_cfg_.prebuffer_ms,
                this->link_cfg_.latch_frames, (unsigned) (this->link_cfg_.keepalive_ms / 1000), this->gain_,
                YESNO(this->highpass_), (unsigned) (this->mic_start_mute_samples_ / 16),
                this->transcriber_.empty() ? "off" : this->transcriber_.c_str());
  if (!this->door_role_())
    ESP_LOGCONFIG(TAG, "  Door: %s", this->door_host_.empty() ? "(not set)" : this->door_host_.c_str());
}

}  // namespace esphome::aikos_voice
