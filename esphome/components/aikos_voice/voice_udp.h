// aikos_voice: the UDP transport for the voice link (lwIP sockets on the ESP32, BSD sockets on a host build).
#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>
#include "voice_core.h"

#ifdef USE_HOST
#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#else
#include <lwip/netdb.h>
#include <lwip/sockets.h>
#endif

namespace aikos {
namespace voice {

// "host" or "host:port" -> Addr (default_port if none). Names are resolved too. false = not usable.
inline bool resolve(const std::string &host_port, uint16_t default_port, Addr &out) {
  out = Addr{};
  if (host_port.empty())
    return false;
  const size_t colon = host_port.rfind(':');
  const std::string host = colon == std::string::npos ? host_port : host_port.substr(0, colon);
  const int port = colon == std::string::npos ? default_port : atoi(host_port.c_str() + colon + 1);
  if (host.empty() || port <= 0 || port > 65535)
    return false;
  in_addr a{};
  if (::inet_aton(host.c_str(), &a) == 0) {
    addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    if (::getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || res == nullptr)
      return false;
    a = ((sockaddr_in *) res->ai_addr)->sin_addr;
    ::freeaddrinfo(res);
  }
  out.ip = a.s_addr;
  out.port = htons((uint16_t) port);
  return true;
}

// the local IPv4 address this device sends from to reach `to` (0 = unknown). A connected UDP socket sends nothing; it
// only asks the routing table. For a host build, which has no ESPHome network interface that knows its address.
inline uint32_t local_ip_toward(const Addr &to) {
  if (!to.valid())
    return 0;
  const int s = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (s < 0)
    return 0;
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_addr.s_addr = to.ip;
  a.sin_port = to.port;
  sockaddr_in me{};
  socklen_t ml = sizeof me;
  uint32_t ip = 0;
  if (::connect(s, (const sockaddr *) &a, sizeof a) == 0 && ::getsockname(s, (sockaddr *) &me, &ml) == 0)
    ip = me.sin_addr.s_addr;
  ::close(s);
  return ip;
}

inline std::string to_string(const Addr &a) {
  in_addr i{};
  i.s_addr = a.ip;
  return std::string(::inet_ntoa(i)) + ":" + std::to_string(ntohs(a.port));
}

class UdpTransport : public Transport {
 public:
  bool begin(uint16_t port) {
    if (sock_ >= 0)
      return true;
    sock_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);  // ::, ESPHome has a socket namespace
    if (sock_ < 0)
      return false;
    sockaddr_in me{};
    me.sin_family = AF_INET;
    me.sin_addr.s_addr = htonl(INADDR_ANY);
    me.sin_port = htons(port);
    if (::bind(sock_, (const sockaddr *) &me, sizeof me) != 0) {
      ::close(sock_);
      sock_ = -1;
      return false;
    }
    ::fcntl(sock_, F_SETFL, ::fcntl(sock_, F_GETFL, 0) | O_NONBLOCK);
    return true;
  }
  bool ready() const { return sock_ >= 0; }
  bool send(const Addr &to, const uint8_t *data, size_t len) override {
    if (sock_ < 0 || !to.valid())
      return false;
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = to.ip;
    a.sin_port = to.port;
    return ::sendto(sock_, data, len, 0, (const sockaddr *) &a, sizeof a) == (int) len;
  }
  int recv(uint8_t *buf, size_t cap, Addr &from) override {
    if (sock_ < 0)
      return -1;
    sockaddr_in a{};
    socklen_t al = sizeof a;
    const int n = ::recvfrom(sock_, buf, cap, 0, (sockaddr *) &a, &al);
    if (n > 0) {
      from.ip = a.sin_addr.s_addr;
      from.port = a.sin_port;
    }
    return n;
  }

 protected:
  int sock_ = -1;
};

}  // namespace voice
}  // namespace aikos
