#include "PiTcpClient.h"
#include <winsock2.h>
#include <atlconv.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")

namespace {
struct SocketGuard {
  SOCKET s = INVALID_SOCKET;
  ~SocketGuard() { if (s != INVALID_SOCKET) closesocket(s); }
};
}
PiReply PiTcpClient::Send(const CString& host, int port, const CString& line) {
  PiReply answer;
  WSADATA data{};
  if (WSAStartup(MAKEWORD(2,2), &data) != 0) {
    answer.message = L"Winsock 초기화 실패";
    return answer;
  }
  struct Cleanup { ~Cleanup() { WSACleanup(); } } cleanup;
  CStringA hostUtf8(CW2A(host, CP_UTF8));
  CStringA portText;
  portText.Format("%d", port);
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  hints.ai_protocol = IPPROTO_TCP;
  addrinfo* found = nullptr;
  if (getaddrinfo(hostUtf8.GetString(), portText.GetString(), &hints, &found) != 0) {
    answer.message = L"Pi 주소 확인 실패";
    return answer;
  }
  struct FreeAddress { addrinfo* p; ~FreeAddress() { freeaddrinfo(p); } } freeAddress{found};
  SocketGuard socket;
  for (addrinfo* p = found; p; p = p->ai_next) {
    SOCKET candidate = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
    if (candidate == INVALID_SOCKET) continue;
    // Non-blocking connect with a 2-second timeout.
    u_long nonBlocking = 1;
    ioctlsocket(candidate, FIONBIO, &nonBlocking);
    int rc = connect(candidate, p->ai_addr, static_cast<int>(p->ai_addrlen));
    if (rc == SOCKET_ERROR && WSAGetLastError() != WSAEWOULDBLOCK) {
      closesocket(candidate); continue;
    }
    fd_set writable;
    FD_ZERO(&writable);
    FD_SET(candidate, &writable);
    timeval timeout{2,0};
    rc = select(0, nullptr, &writable, nullptr, &timeout);
    int socketError = 0;
    int optLen = sizeof(socketError);
    if (rc != 1 || getsockopt(candidate, SOL_SOCKET, SO_ERROR,
           reinterpret_cast<char*>(&socketError), &optLen) != 0 || socketError != 0) {
      closesocket(candidate); continue;
    }
    nonBlocking = 0;
    ioctlsocket(candidate, FIONBIO, &nonBlocking);
    socket.s = candidate;
    break;
  }
  if (socket.s == INVALID_SOCKET) {
    answer.message = L"TCP 연결 실패: IP, 포트, 방화벽을 확인하세요.";
    return answer;
  }
  DWORD timeoutMs = 3000;
  setsockopt(socket.s, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeoutMs), sizeof(timeoutMs));
  setsockopt(socket.s, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&timeoutMs), sizeof(timeoutMs));
  CStringA wire(CW2A(line, CP_UTF8));
  wire += "\n";
  int remaining = wire.GetLength(), offset = 0;
  while (remaining > 0) {
    int n = send(socket.s, wire.GetString() + offset, remaining, 0);
    if (n <= 0) { answer.message = L"명령 전송 실패"; return answer; }
    remaining -= n; offset += n;
  }
  CStringA response;
  char c = 0;
  while (response.GetLength() < 512) {
    int n = recv(socket.s, &c, 1, 0);
    if (n <= 0) { answer.message = L"Pi 응답 없음 (시간초과/연결종료)"; return answer; }
    if (c == '\n') break;
    if (c != '\r') response += c;
  }
  if (response.GetLength() >= 512) { answer.message = L"Pi 응답이 너무 깁니다"; return answer; }
  answer.message = CString(CA2W(response.GetString(), CP_UTF8));
  return answer;
}
