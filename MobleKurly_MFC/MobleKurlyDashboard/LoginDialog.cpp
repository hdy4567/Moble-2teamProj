#include "LoginDialog.h"
#include "UiFont.h"
#include "resource.h"
#include "ThemedMessageBox.h"
#include <gdiplus.h>
#include <algorithm>
#include <cwctype>
#include <cmath>

namespace {
constexpr UINT kIdInput = 5101;
constexpr UINT kPasswordInput = 5102;
const COLORREF kBrand = RGB(32, 120, 180),
               kBrandDark = RGB(19, 55, 91),
               kSkyBlue = RGB(9, 146, 242),
               kGold = RGB(217, 155, 32),
               kInk = RGB(37, 51, 67),
               kMuted = RGB(125, 135, 146),
               kLine = RGB(233, 237, 241),
               kSurface = RGB(246, 248, 250),
               kFieldBorder = RGB(200, 210, 222),
               kGreen = RGB(46, 175, 102);

UINT DialogDpi(HWND hwnd) {
  using GetDpi = UINT(WINAPI*)(HWND);
  const auto getDpi = reinterpret_cast<GetDpi>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
  return getDpi ? getDpi(hwnd) : 96;
}

struct Member { const wchar_t* id; const wchar_t* name; };
constexpr Member kMembers[] = {
  {L"pjs", L"박지수"}, {L"cjh", L"최종현"}, {L"hdy", L"함동윤"},
  {L"kdw", L"김도완"}, {L"psh", L"박상하"}, {L"lhj", L"이해준"}
};

void DrawRoundedRect(Gdiplus::Graphics& g, float x, float y, float w, float h, float r,
                     const Gdiplus::Brush* fillBrush, const Gdiplus::Pen* strokePen) {
  Gdiplus::GraphicsPath path;
  float d = std::min(r * 2.0f, std::min(w, h));
  path.AddArc(x, y, d, d, 180.0f, 90.0f);
  path.AddArc(x + w - d, y, d, d, 270.0f, 90.0f);
  path.AddArc(x + w - d, y + h - d, d, d, 0.0f, 90.0f);
  path.AddArc(x, y + h - d, d, d, 90.0f, 90.0f);
  path.CloseFigure();
  if (fillBrush) g.FillPath(fillBrush, &path);
  if (strokePen) g.DrawPath(strokePen, &path);
}
}

BEGIN_MESSAGE_MAP(HoverButton, CButton)
ON_WM_MOUSEMOVE()
ON_WM_MOUSELEAVE()
END_MESSAGE_MAP()

void HoverButton::OnMouseMove(UINT flags, CPoint pt) {
  if (!hovered_) {
    hovered_ = true;
    TRACKMOUSEEVENT tme{sizeof(tme), TME_LEAVE, m_hWnd, 0};
    TrackMouseEvent(&tme);
    Invalidate(FALSE);
  }
  CButton::OnMouseMove(flags, pt);
}

void HoverButton::OnMouseLeave() {
  hovered_ = false;
  Invalidate(FALSE);
}

BEGIN_MESSAGE_MAP(LoginDialog, CDialog)
ON_WM_CTLCOLOR()
ON_WM_SIZE()
ON_WM_PAINT()
ON_WM_LBUTTONDOWN()
ON_WM_DRAWITEM()
ON_MESSAGE(WM_DPICHANGED, &LoginDialog::OnDpiChanged)
ON_EN_SETFOCUS(kIdInput, &LoginDialog::OnEditFocusChanged)
ON_EN_KILLFOCUS(kIdInput, &LoginDialog::OnEditFocusChanged)
ON_EN_SETFOCUS(kPasswordInput, &LoginDialog::OnEditFocusChanged)
ON_EN_KILLFOCUS(kPasswordInput, &LoginDialog::OnEditFocusChanged)
END_MESSAGE_MAP()

LoginDialog::LoginDialog(CWnd* parent) : CDialog() {
  background_.CreateSolidBrush(RGB(255, 255, 255));
  // Resource-free modal dialog: avoids modifying the existing .rc resource setup.
  dialogTemplate_.resize(sizeof(DLGTEMPLATE) + sizeof(WORD) * 3 + 4);
  std::fill(dialogTemplate_.begin(), dialogTemplate_.end(), BYTE{0});
  auto* d = reinterpret_cast<DLGTEMPLATE*>(dialogTemplate_.data());
  d->style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME | WS_CLIPCHILDREN;
  d->dwExtendedStyle = 0;
  d->cdit = 0;
  d->x = 0; d->y = 0; d->cx = 450; d->cy = 280;
  InitModalIndirect(d, parent);
}

LoginDialog::~LoginDialog() = default;

INT_PTR LoginDialog::ShowLogin() { return DoModal(); }

void LoginDialog::OnEditFocusChanged() {
  CRect client; GetClientRect(&client);
  auto px = [this](int value) { return static_cast<int>(std::lround(value * scale_)); };
  const int leftWidth = px(260);
  const int formX = leftWidth + px(36);
  const int formRight = client.Width() - px(36);
  CRect fieldsRect(formX - px(4), px(138), formRight + px(4), px(272));
  InvalidateRect(&fieldsRect, FALSE);
}

void LoginDialog::LoadBrandMark() {
  if (iconBitmap_) return;
  wchar_t path[MAX_PATH] = {0};
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  CString exePath(path);
  int slash = exePath.ReverseFind(L'\\');
  CString appDir;
  if (slash >= 0) {
    appDir = exePath.Left(slash + 1);
  }
  const CString candidatePaths[] = {
    appDir + L"ikon.png",
    appDir + L"..\\ikon.png",
    appDir + L"..\\..\\MobleKurlyDashboard\\ikon.png",
    CString(L"ikon.png")
  };
  for (const auto& candidate : candidatePaths) {
    if (GetFileAttributesW(candidate) != INVALID_FILE_ATTRIBUTES) {
      auto bmp = std::make_unique<Gdiplus::Bitmap>(candidate);
      if (bmp && bmp->GetLastStatus() == Gdiplus::Ok) {
        iconBitmap_ = std::move(bmp);
        break;
      }
    }
  }
}

BOOL LoginDialog::OnInitDialog() {
  CDialog::OnInitDialog();
  SetWindowTextW(L"MobleKurly | 스마트 물류 시스템 로그인");
  
  LoadBrandMark();

  const UINT dpi = DialogDpi(GetSafeHwnd());
  HICON bigIcon = static_cast<HICON>(LoadImageW(AfxGetResourceHandle(), MAKEINTRESOURCEW(IDI_MOBLE_ADMIN),
      IMAGE_ICON, GetSystemMetricsForDpi(SM_CXICON, dpi), GetSystemMetricsForDpi(SM_CYICON, dpi), LR_DEFAULTCOLOR));
  HICON smIcon = static_cast<HICON>(LoadImageW(AfxGetResourceHandle(), MAKEINTRESOURCEW(IDI_MOBLE_ADMIN),
      IMAGE_ICON, GetSystemMetricsForDpi(SM_CXSMICON, dpi), GetSystemMetricsForDpi(SM_CYSMICON, dpi), LR_DEFAULTCOLOR));
  icon_ = bigIcon ? bigIcon : AfxGetApp()->LoadIcon(IDI_MOBLE_ADMIN);
  SetIcon(icon_, TRUE);
  SetIcon(smIcon ? smIcon : icon_, FALSE);

  auto label = [this](CStatic& ctl, LPCWSTR text, const CRect& r) {
    ctl.Create(text, WS_CHILD | WS_VISIBLE | SS_LEFT, r, this);
    ctl.SetFont(&font_);
  };

  label(title_, L"LOGIN", CRect(0, 0, 100, 30));
  label(description_, L"작업자 및 관리자 인증을 진행해주세요.", CRect(0, 0, 100, 30));
  label(idLabel_, L"아이디 (사번)", CRect(0, 0, 100, 30));
  label(passwordLabel_, L"비밀번호", CRect(0, 0, 100, 30));
  label(copyright_, L"Copyright © MOBLE Kurly. All rights reserved.", CRect(0, 0, 100, 30));
  copyright_.ModifyStyle(0, SS_CENTER);

  idEdit_.Create(WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                 CRect(0, 0, 100, 30), this, kIdInput);
  passwordEdit_.Create(WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_PASSWORD | ES_AUTOHSCROLL,
                       CRect(0, 0, 100, 30), this, kPasswordInput);
  idEdit_.SetFont(&font_);
  passwordEdit_.SetFont(&font_);

  submit_.Create(L"로그인", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                 CRect(0, 0, 100, 30), this, IDOK);
  cancel_.Create(L"종료", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                 CRect(0, 0, 100, 30), this, IDCANCEL);
  submit_.SetFont(&boldFont_);
  cancel_.SetFont(&font_);

  SetDefID(IDOK);
  FitToMonitor();
  Layout();
  idEdit_.SetFocus();
  return FALSE;
}

void LoginDialog::FitToMonitor(const RECT* suggested) {
  MONITORINFO monitor = {sizeof(monitor)};
  const HMONITOR target = suggested ? MonitorFromRect(suggested, MONITOR_DEFAULTTONEAREST)
                                    : MonitorFromWindow(GetSafeHwnd(), MONITOR_DEFAULTTONEAREST);
  if (!GetMonitorInfoW(target, &monitor)) return;
  const CRect work(monitor.rcWork);
  const double dpi = DialogDpi(GetSafeHwnd()) / 96.0;
  const int width = std::min(static_cast<int>(std::lround(680 * dpi)), work.Width() - 24);
  const int height = std::min(static_cast<int>(std::lround(430 * dpi)), work.Height() - 24);
  const int left = suggested ? std::clamp<LONG>(suggested->left, work.left, work.right - width)
                             : work.left + (work.Width() - width) / 2;
  const int top = suggested ? std::clamp<LONG>(suggested->top, work.top, work.bottom - height)
                            : work.top + (work.Height() - height) / 2;
  SetWindowPos(nullptr, left, top, width, height, SWP_NOZORDER | SWP_NOACTIVATE);
}

void LoginDialog::Layout() {
  if (!idEdit_.GetSafeHwnd()) return;
  CRect client; GetClientRect(&client);
  scale_ = std::min({DialogDpi(GetSafeHwnd()) / 96.0, client.Width() / 680.0, client.Height() / 430.0});
  scale_ = std::max(0.5, scale_);
  auto px = [this](int value) { return static_cast<int>(std::lround(value * scale_)); };

  const int leftWidth = px(260);
  const int formX = leftWidth + px(36);
  const int formWidth = client.Width() - formX - px(36);

  title_.MoveWindow(formX, px(34), formWidth, px(32), FALSE);
  description_.MoveWindow(formX, px(70), formWidth, px(22), FALSE);
  idLabel_.MoveWindow(formX, px(118), formWidth, px(20), FALSE);
  passwordLabel_.MoveWindow(formX, px(200), formWidth, px(20), FALSE);

  const int buttonTop = px(296);
  const int buttonHeight = px(44);
  const int cancelWidth = px(88);
  const int gap = px(12);
  const int submitWidth = formWidth - cancelWidth - gap;
  submit_.MoveWindow(formX, buttonTop, submitWidth, buttonHeight, FALSE);
  cancel_.MoveWindow(formX + submitWidth + gap, buttonTop, cancelWidth, buttonHeight, FALSE);

  // Fonts using project standard Pretendard
  font_.DeleteObject(); titleFont_.DeleteObject(); boldFont_.DeleteObject();
  smallFont_.DeleteObject(); leftTitleFont_.DeleteObject(); leftSubFont_.DeleteObject();

  font_.CreateFontW(-px(13), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                    OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());
  boldFont_.CreateFontW(-px(13), 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());
  titleFont_.CreateFontW(-px(24), 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                         OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());
  smallFont_.CreateFontW(-px(11), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                         OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());
  leftTitleFont_.CreateFontW(-px(20), 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                             OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());
  leftSubFont_.CreateFontW(-px(12), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                           OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, UiFont::Family());

  title_.SetFont(&titleFont_, FALSE);
  description_.SetFont(&font_, FALSE);
  idLabel_.SetFont(&boldFont_, FALSE);
  passwordLabel_.SetFont(&boldFont_, FALSE);
  submit_.SetFont(&boldFont_, FALSE);
  cancel_.SetFont(&font_, FALSE);

  const int copyrightHeight = px(16);
  const int copyrightY = client.Height() - px(22) - copyrightHeight;
  copyright_.MoveWindow(formX, copyrightY, formWidth, copyrightHeight, FALSE);
  copyright_.SetFont(&smallFont_, FALSE);

  CClientDC dc(this);
  CFont* oldFont = dc.SelectObject(&font_);
  TEXTMETRIC metrics{}; dc.GetTextMetrics(&metrics);
  dc.SelectObject(oldFont);

  const int fieldHeight = px(42);
  const int editHeight = std::min(fieldHeight - 2, static_cast<int>(metrics.tmHeight) + 2);
  const int insetY = (fieldHeight - editHeight) / 2;
  const int insetX = px(10); // Clear the 6px rounded corners cleanly

  idEdit_.SetFont(&font_, FALSE);
  passwordEdit_.SetFont(&font_, FALSE);
  idEdit_.MoveWindow(formX + insetX, px(142) + insetY, formWidth - insetX * 2, editHeight, FALSE);
  passwordEdit_.MoveWindow(formX + insetX, px(224) + insetY, formWidth - insetX * 2, editHeight, FALSE);
  idEdit_.SendMessage(EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(px(2), px(2)));
  passwordEdit_.SendMessage(EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(px(2), px(2)));

  Invalidate();
}

void LoginDialog::OnSize(UINT type, int cx, int cy) {
  CDialog::OnSize(type, cx, cy);
  if (type != SIZE_MINIMIZED) Layout();
}

LRESULT LoginDialog::OnDpiChanged(WPARAM, LPARAM position) {
  FitToMonitor(reinterpret_cast<const RECT*>(position));
  Layout();
  return 0;
}

HBRUSH LoginDialog::OnCtlColor(CDC* dc, CWnd* window, UINT type) {
  if (type == CTLCOLOR_DLG || type == CTLCOLOR_STATIC || type == CTLCOLOR_EDIT) {
    dc->SetBkColor(RGB(255, 255, 255));
    if (window == &title_) dc->SetTextColor(kBrandDark);
    else if (window == &description_) dc->SetTextColor(kMuted);
    else if (window == &copyright_) dc->SetTextColor(RGB(155, 165, 175));
    else if (window == &idLabel_ || window == &passwordLabel_) dc->SetTextColor(kInk);
    else dc->SetTextColor(kInk);
    return static_cast<HBRUSH>(background_.GetSafeHandle());
  }
  return CDialog::OnCtlColor(dc, window, type);
}

void LoginDialog::OnPaint() {
  CPaintDC dc(this);
  CRect client; GetClientRect(&client);
  CRect clip; dc.GetClipBox(&clip);
  auto px = [this](int value) { return static_cast<int>(std::lround(value * scale_)); };
  const int leftWidth = px(260);

  // 1. Left Branding Panel (Skipped completely when only right input fields are invalidated)
  if (clip.left < leftWidth) {
    CRect leftRect(0, 0, leftWidth, client.Height());
    dc.FillSolidRect(leftRect, kBrandDark);
    dc.FillSolidRect(0, 0, leftWidth, std::max(3, px(4)), kSkyBlue);

    // Draw Official Brand Mark with Bicubic Anti-aliased High Quality
    const int iconSize = px(56);
    if (iconBitmap_) {
      Gdiplus::Graphics graphics(dc.m_hDC);
      graphics.SetInterpolationMode(Gdiplus::InterpolationModeHighQualityBicubic);
      graphics.SetSmoothingMode(Gdiplus::SmoothingModeHighQuality);
      graphics.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHighQuality);
      graphics.DrawImage(iconBitmap_.get(), px(32), px(36), iconSize, iconSize);
    } else {
      HICON hiRes = static_cast<HICON>(LoadImageW(
          AfxGetResourceHandle(),
          MAKEINTRESOURCEW(IDI_MOBLE_ADMIN),
          IMAGE_ICON,
          iconSize,
          iconSize,
          LR_DEFAULTCOLOR));
      if (hiRes) {
        DrawIconEx(dc.m_hDC, px(32), px(36), hiRes, iconSize, iconSize, 0, NULL, DI_NORMAL);
        DestroyIcon(hiRes);
      } else if (icon_) {
        DrawIconEx(dc.m_hDC, px(32), px(36), icon_, iconSize, iconSize, 0, NULL, DI_NORMAL);
      }
    }

    // Left panel typography
    dc.SetBkMode(TRANSPARENT);
    CFont* oldFont = dc.SelectObject(&leftTitleFont_);
    dc.SetTextColor(RGB(255, 255, 255));
    dc.TextOutW(px(32), px(102), L"MobleKurly");

    dc.SelectObject(&leftSubFont_);
    dc.SetTextColor(RGB(145, 195, 240));
    dc.TextOutW(px(32), px(132), L"스마트 물류 제어 시스템");

    dc.FillSolidRect(px(32), px(164), leftWidth - px(64), 1, RGB(35, 75, 115));

    

    dc.SetTextColor(RGB(145, 175, 205));
    dc.TextOutW(px(32), px(204), L"실시간 컨베이어 · 재고 연동");

    

    dc.SetTextColor(RGB(125, 160, 195));
    dc.TextOutW(px(32), client.Height() - px(46), L"일상에 기술을 더하다");

    dc.SelectObject(&boldFont_);
    dc.SetTextColor(kGold);
    dc.TextOutW(px(32), client.Height() - px(28), L"Kurly by MOBLE");
    dc.SelectObject(oldFont);
  }

  // 2. Right Form Panel
  if (clip.right > leftWidth) {
    const int formX = leftWidth + px(36);
    const int formWidth = client.Width() - formX - px(36);

    // Static panel backgrounds and lines are only drawn when whole dialog or headers are dirty
    if (clip.top < px(105) || clip.bottom > px(280)) {
      CRect rightRect(leftWidth, 0, client.Width(), client.Height());
      dc.FillSolidRect(rightRect, RGB(255, 255, 255));
      dc.FillSolidRect(leftWidth, 0, client.Width() - leftWidth, std::max(3, px(4)), kBrand);
      dc.FillSolidRect(leftWidth, 0, 1, client.Height(), kLine);
      dc.FillSolidRect(formX, px(98), formWidth, 1, kLine);
    }

    // Draw modern input field borders with rounded corners (Radius 6px) and dynamic focus state
    const HWND focusedWnd = ::GetFocus();
    const int tops[] = {142, 224};
    const bool focused[] = {focusedWnd == idEdit_.GetSafeHwnd(), focusedWnd == passwordEdit_.GetSafeHwnd()};

    Gdiplus::Graphics gRight(dc.m_hDC);
    gRight.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);

    Gdiplus::SolidBrush whiteBrush(Gdiplus::Color(255, 255, 255));
    Gdiplus::Pen focusPen(Gdiplus::Color(255, 9, 146, 242), static_cast<float>(std::max(2, px(2))));
    Gdiplus::Pen normalPen(Gdiplus::Color(255, 200, 204, 208), 1.0f);

    for (int i = 0; i < 2; ++i) {
      DrawRoundedRect(gRight, static_cast<float>(formX), static_cast<float>(px(tops[i])),
                      static_cast<float>(formWidth), static_cast<float>(px(42)),
                      static_cast<float>(px(6)), &whiteBrush, focused[i] ? &focusPen : &normalPen);
    }
  }
}

void LoginDialog::OnLButtonDown(UINT flags, CPoint point) {
  CRect client; GetClientRect(&client);
  auto px = [this](int value) { return static_cast<int>(std::lround(value * scale_)); };
  const int leftWidth = px(260);
  const int formX = leftWidth + px(36);
  const int formRight = client.Width() - px(36);

  if (CRect(formX, px(142), formRight, px(184)).PtInRect(point)) { idEdit_.SetFocus(); return; }
  if (CRect(formX, px(224), formRight, px(266)).PtInRect(point)) { passwordEdit_.SetFocus(); return; }
  CDialog::OnLButtonDown(flags, point);
}

void LoginDialog::OnDrawItem(int controlId, LPDRAWITEMSTRUCT item) {
  if (item->CtlID != IDOK && item->CtlID != IDCANCEL) { CDialog::OnDrawItem(controlId, item); return; }
  CDC dc; dc.Attach(item->hDC);
  CRect rect(item->rcItem);
  auto px = [this](int value) { return static_cast<int>(std::lround(value * scale_)); };

  const bool primary = (item->CtlID == IDOK);
  const bool pressed = ((item->itemState & ODS_SELECTED) != 0);
  const bool hovered = primary ? submit_.IsHovered() : cancel_.IsHovered();
  const bool focused = ((item->itemState & ODS_FOCUS) != 0);

  // Clear background of button so rounded corners blend seamlessly onto the white dialog
  dc.FillSolidRect(rect, RGB(255, 255, 255));

  Gdiplus::Graphics g(item->hDC);
  g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
  g.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHighQuality);

  float x = 0.5f;
  float y = 0.5f;
  float w = static_cast<float>(rect.Width()) - 1.0f;
  float h = static_cast<float>(rect.Height()) - 1.0f;
  float r = static_cast<float>(px(6)); // Smooth 6px rounded corners

  Gdiplus::Color bgCol, borderCol;
  if (primary) {
    if (pressed) {
      bgCol = Gdiplus::Color(255, 19, 55, 91);       // Brand Dark Navy (#13375B)
      borderCol = Gdiplus::Color(255, 19, 55, 91);
    } else if (hovered) {
      bgCol = Gdiplus::Color(255, 45, 138, 205);     // Brighter, lively Blue on hover
      borderCol = Gdiplus::Color(255, 45, 138, 205);
    } else {
      bgCol = Gdiplus::Color(255, 32, 120, 180);     // Brand Blue (#2078B4)
      borderCol = Gdiplus::Color(255, 32, 120, 180);
    }
  } else {
    if (pressed) {
      bgCol = Gdiplus::Color(255, 225, 230, 236);
      borderCol = Gdiplus::Color(255, 200, 208, 218);
    } else if (hovered) {
      bgCol = Gdiplus::Color(255, 238, 242, 246);    // Soft elevated gray on hover
      borderCol = Gdiplus::Color(255, 205, 213, 222);
    } else {
      bgCol = Gdiplus::Color(255, 246, 248, 250);    // Light surface (#F6F8FA)
      borderCol = Gdiplus::Color(255, 230, 234, 238);
    }
  }

  Gdiplus::SolidBrush fillBrush(bgCol);
  Gdiplus::Pen borderPen(borderCol, 1.0f);
  DrawRoundedRect(g, x, y, w, h, r, &fillBrush, &borderPen);

  dc.SetBkMode(TRANSPARENT);
  dc.SetTextColor(primary ? RGB(255, 255, 255) : kInk);
  CFont* old = dc.SelectObject(primary ? &boldFont_ : &font_);
  CString text; GetDlgItem(item->CtlID)->GetWindowTextW(text);
  dc.DrawText(text, rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

  if (focused && !primary) {
    CRect focusRect(rect);
    focusRect.DeflateRect(px(4), px(4));
    dc.DrawFocusRect(focusRect);
  }
  dc.SelectObject(old);
  dc.Detach();
}

void LoginDialog::OnOK() {
  CString id, password;
  idEdit_.GetWindowTextW(id);
  passwordEdit_.GetWindowTextW(password);
  id.Trim(); id.MakeLower();
  const Member* matched = nullptr;
  for (const auto& member : kMembers) {
    if (id == member.id) { matched = &member; break; }
  }
  if (!matched || (password != L"1234" && password != L"1111")) {
    passwordEdit_.SetWindowTextW(L"");
    ThemedMessageBox(L"아이디 또는 비밀번호가 올바르지 않습니다.", MB_ICONWARNING);
    passwordEdit_.SetFocus();
    return;
  }
  userId_ = id;
  displayName_ = matched->name;
  role_ = (password == L"1111") ? UserRole::Admin : UserRole::Worker;
  CDialog::OnOK();
}

void LoginDialog::OnCancel() { CDialog::OnCancel(); }
