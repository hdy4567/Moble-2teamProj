#pragma once
#include <afxwin.h>

struct PiReply {
  bool ok = false;
  CString message;
};

class PiTcpClient {
public:
  // The caller must call this method on a worker thread (not the UI thread).
  static PiReply Send(const CString& host, int port, const CString& line);
};
