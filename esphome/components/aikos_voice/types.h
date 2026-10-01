// aikos::voice: the small types every part of the voice link shares. Pure C++17.
#pragma once

#include <cstdint>

namespace aikos {
namespace voice {

// IPv4 address and port, both in network byte order (as in sockaddr_in). A key is known by its IP address.
struct Addr {
  uint32_t ip = 0;
  uint16_t port = 0;
  bool valid() const { return ip != 0 && port != 0; }
  bool operator==(const Addr &o) const { return ip == o.ip && port == o.port; }
  bool operator!=(const Addr &o) const { return !(*this == o); }
};

// The two ends of a call: the door station and a room key.
enum class Role : uint8_t { DOOR, ROOM };

}  // namespace voice
}  // namespace aikos
