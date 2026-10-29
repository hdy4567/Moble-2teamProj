#pragma once

#include <afxwin.h>

// Drop-in branded replacement for AfxMessageBox.  It preserves Win32 return
// values such as IDYES, IDNO and IDOK so existing business logic is unchanged.
int ThemedMessageBox(const CString& text, UINT type = MB_OK,
                     CWnd* parent = nullptr,
                     const CString& caption = L"모블 컬리");
