#pragma once
#include <cstdint>
#include <string>

// [ESTOP] A queue ACK is never a conveyor state confirmation.
struct ConveyorSnapshot {
  bool running = false;
  bool pressed = false;
  std::uint32_t revision = 0;
};

inline bool ParseConveyorReply(const std::wstring &line,
                              const std::wstring &requestId,
                              ConveyorSnapshot &snapshot) {
  const std::wstring prefix = L"ACK|" + requestId + L"|CONVEYOR,";
  if (line.compare(0, prefix.size(), prefix) != 0) return false;
  const std::wstring payload = line.substr(prefix.size());
  const auto a = payload.find(L',');
  if (a == std::wstring::npos) return false;
  const auto b = payload.find(L',', a + 1);
  if (b == std::wstring::npos) return false;
  const auto motion = payload.substr(0, a);
  const auto button = payload.substr(a + 1, b - a - 1);
  const auto number = payload.substr(b + 1);
  if ((motion != L"RUNNING" && motion != L"STOPPED") ||
      (button != L"PRESSED" && button != L"RELEASED") || number.empty() ||
      (motion == L"RUNNING" && button == L"PRESSED")) return false;
  std::uint32_t revision = 0;
  for (wchar_t c : number) {
    if (c < L'0' || c > L'9') return false;
    const auto digit = static_cast<std::uint32_t>(c - L'0');
    if (revision > (UINT32_MAX - digit) / 10U) return false;
    revision = revision * 10U + digit;
  }
  snapshot = {motion == L"RUNNING", button == L"PRESSED", revision};
  return true;
}
