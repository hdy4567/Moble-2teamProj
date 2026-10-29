#include "ThemedMessageBox.h"

#include "resource.h"
#include <algorithm>
#include <cmath>
#include <vector>

namespace {
constexpr COLORREF kBrand = RGB(32, 120, 180);
constexpr COLORREF kNavy = RGB(19, 55, 91);
constexpr COLORREF kInk = RGB(37, 51, 67);
constexpr COLORREF kMuted = RGB(100, 115, 130);
constexpr COLORREF kLine = RGB(225, 233, 240);
constexpr COLORREF kPale = RGB(246, 249, 251);
constexpr COLORREF kWarning = RGB(184, 118, 0);
constexpr COLORREF kError = RGB(211, 39, 43);
constexpr wchar_t kUiFontFamily[] = L"Pretendard";

UINT MessageDpi(HWND hwnd) {
  using GetDpi = UINT(WINAPI*)(HWND);
  const auto getDpi = reinterpret_cast<GetDpi>(
      GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
  return getDpi ? getDpi(hwnd) : 96;
}

struct EmptyDialogTemplate {
  DLGTEMPLATE dialog;
  WORD menu;
  WORD windowClass;
  WORD title;
};

class ThemedMessageDialog final : public CDialog {
 public:
  ThemedMessageDialog(const CString& text, UINT type, CWnd* parent,
                      const CString& caption)
      : text_(text), type_(type), parent_(parent), caption_(caption) {
    template_.dialog.style = WS_POPUP | WS_CAPTION | WS_SYSMENU |
                             DS_MODALFRAME | WS_CLIPCHILDREN;
    template_.dialog.cdit = 0;
    template_.dialog.cx = 390;
    template_.dialog.cy = 205;
    ready_ = InitModalIndirect(&template_.dialog, parent) != FALSE;
  }

  INT_PTR Show() { return ready_ ? DoModal() : -1; }

 protected:
  BOOL OnInitDialog() override {
    CDialog::OnInitDialog();
    const UINT iconType = type_ & MB_ICONMASK;
    semanticColor_ = iconType == MB_ICONERROR ? kError
                     : iconType == MB_ICONWARNING ? kWarning : kBrand;
    kind_ = iconType == MB_ICONERROR ? L"오류"
            : iconType == MB_ICONWARNING ? L"확인 필요"
            : iconType == MB_ICONQUESTION ? L"선택 확인" : L"안내";
    SetWindowTextW(caption_ + L" | " + kind_);
    const HICON icon = AfxGetApp()->LoadIcon(IDI_MOBLE_ADMIN);
    if (icon) { SetIcon(icon, TRUE); SetIcon(icon, FALSE); }

    whiteBrush_.CreateSolidBrush(RGB(255, 255, 255));
    paleBrush_.CreateSolidBrush(kPale);
    title_.Create(kind_, WS_CHILD | WS_VISIBLE | SS_LEFT, CRect(), this);
    message_.Create(text_, WS_CHILD | WS_VISIBLE | SS_LEFT, CRect(), this);

    const bool question = (type_ & MB_TYPEMASK) == MB_YESNO;
    primary_.Create(question ? L"예" : L"확인",
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                    CRect(), this, IDOK);
    if (question) {
      secondary_.Create(L"아니오",
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                        CRect(), this, IDCANCEL);
    }
    FitToMonitor();
    Layout();
    const bool defaultNo = question && (type_ & MB_DEFMASK) == MB_DEFBUTTON2;
    SetDefID(defaultNo ? IDCANCEL : IDOK);
    (defaultNo ? static_cast<CWnd*>(&secondary_)
               : static_cast<CWnd*>(&primary_))->SetFocus();
    return FALSE;
  }

  void OnOK() override {
    EndDialog((type_ & MB_TYPEMASK) == MB_YESNO ? IDYES : IDOK);
  }

  void OnCancel() override {
    EndDialog((type_ & MB_TYPEMASK) == MB_YESNO ? IDNO : IDOK);
  }

  void FitToMonitor(const RECT* suggested = nullptr) {
    MONITORINFO monitor{sizeof(monitor)};
    const HMONITOR target = suggested
        ? MonitorFromRect(suggested, MONITOR_DEFAULTTONEAREST)
        : MonitorFromWindow(parent_ && parent_->GetSafeHwnd()
                                ? parent_->GetSafeHwnd() : GetSafeHwnd(),
                            MONITOR_DEFAULTTONEAREST);
    if (!GetMonitorInfoW(target, &monitor)) return;
    const CRect work(monitor.rcWork);
    const double dpi = MessageDpi(GetSafeHwnd()) / 96.0;
    const int width = std::min(static_cast<int>(std::lround(600 * dpi)),
                               work.Width() - 24);
    const int height = std::min(static_cast<int>(std::lround(320 * dpi)),
                                work.Height() - 24);
    const int left = suggested
        ? std::clamp<LONG>(suggested->left, work.left, work.right - width)
        : work.left + (work.Width() - width) / 2;
    const int top = suggested
        ? std::clamp<LONG>(suggested->top, work.top, work.bottom - height)
        : work.top + (work.Height() - height) / 2;
    SetWindowPos(nullptr, left, top, width, height,
                 SWP_NOZORDER | SWP_NOACTIVATE);
  }

  void Layout() {
    if (!primary_.GetSafeHwnd()) return;
    CRect client; GetClientRect(&client);
    scale_ = std::max(0.65, std::min({MessageDpi(GetSafeHwnd()) / 96.0,
                                     client.Width() / 560.0,
                                     client.Height() / 280.0}));
    auto px = [this](int value) {
      return static_cast<int>(std::lround(value * scale_));
    };
    const int iconRight = px(76);
    title_.MoveWindow(iconRight, px(28), client.Width() - iconRight - px(28),
                      px(31), FALSE);
    message_.MoveWindow(iconRight, px(74), client.Width() - iconRight - px(32),
                        client.Height() - px(154), FALSE);
    const int buttonY = client.Height() - px(60);
    const int buttonW = px(118), gap = px(10), right = client.Width() - px(28);
    primary_.MoveWindow(right - buttonW, buttonY, buttonW, px(40), FALSE);
    if (secondary_.GetSafeHwnd())
      secondary_.MoveWindow(right - buttonW * 2 - gap, buttonY,
                            buttonW, px(40), FALSE);

    font_.DeleteObject(); titleFont_.DeleteObject();
    font_.CreateFontW(-px(14), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                      DEFAULT_CHARSET, OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS,
                      CLEARTYPE_NATURAL_QUALITY, DEFAULT_PITCH,
                      kUiFontFamily);
    titleFont_.CreateFontW(-px(22), 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                           DEFAULT_CHARSET, OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS,
                           CLEARTYPE_NATURAL_QUALITY, DEFAULT_PITCH,
                           kUiFontFamily);
    title_.SetFont(&titleFont_, FALSE);
    message_.SetFont(&font_, FALSE);
    primary_.SetFont(&font_, FALSE);
    if (secondary_.GetSafeHwnd()) secondary_.SetFont(&font_, FALSE);
    Invalidate(FALSE);
  }

  afx_msg void OnPaint() {
    CPaintDC dc(this);
    CRect client; GetClientRect(&client);
    dc.FillSolidRect(client, RGB(255, 255, 255));
    dc.FillSolidRect(0, 0, client.Width(),
                     std::max(3, static_cast<int>(4 * scale_)), kBrand);
    const int footerTop = client.Height() - static_cast<int>(78 * scale_);
    dc.FillSolidRect(0, footerTop, client.Width(), client.Height() - footerTop,
                     kPale);
    dc.FillSolidRect(0, footerTop, client.Width(), 1, kLine);

    const int cx = static_cast<int>(42 * scale_);
    const int cy = static_cast<int>(44 * scale_);
    const int radius = std::max(14, static_cast<int>(18 * scale_));
    CBrush fill(RGB(239, 247, 252));
    CPen pen(PS_SOLID, std::max(2, static_cast<int>(2 * scale_)), semanticColor_);
    CBrush* oldBrush = dc.SelectObject(&fill);
    CPen* oldPen = dc.SelectObject(&pen);
    dc.Ellipse(cx - radius, cy - radius, cx + radius, cy + radius);
    dc.SelectObject(oldPen); dc.SelectObject(oldBrush);
    dc.SetBkMode(TRANSPARENT);
    dc.SetTextColor(semanticColor_);
    CFont symbol;
    symbol.CreateFontW(-std::max(15, static_cast<int>(18 * scale_)), 0, 0, 0,
                       FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                       OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS,
                       CLEARTYPE_NATURAL_QUALITY, DEFAULT_PITCH,
                       kUiFontFamily);
    CFont* oldFont = dc.SelectObject(&symbol);
    const CString glyph = (type_ & MB_ICONMASK) == MB_ICONQUESTION ? L"?" :
                          (type_ & MB_ICONMASK) == MB_ICONINFORMATION ? L"i" : L"!";
    dc.DrawText(glyph, CRect(cx - radius, cy - radius, cx + radius, cy + radius),
                DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    dc.SelectObject(oldFont);
  }

  afx_msg HBRUSH OnCtlColor(CDC* dc, CWnd* window, UINT type) {
    if (type == CTLCOLOR_DLG || type == CTLCOLOR_STATIC) {
      dc->SetBkMode(TRANSPARENT);
      dc->SetTextColor(window == &title_ ? kNavy : kInk);
      return static_cast<HBRUSH>(whiteBrush_.GetSafeHandle());
    }
    return CDialog::OnCtlColor(dc, window, type);
  }

  afx_msg void OnDrawItem(int controlId, LPDRAWITEMSTRUCT item) {
    if (controlId != IDOK && controlId != IDCANCEL) {
      CDialog::OnDrawItem(controlId, item);
      return;
    }
    CDC dc; dc.Attach(item->hDC);
    CRect rect(item->rcItem);
    const bool primary = controlId == IDOK;
    const bool pressed = (item->itemState & ODS_SELECTED) != 0;
    const COLORREF fill = primary ? (pressed ? kNavy : kBrand)
                                  : (pressed ? RGB(235, 242, 247) : RGB(255, 255, 255));
    dc.FillSolidRect(rect, fill);
    dc.Draw3dRect(rect, primary ? kBrand : kLine,
                  primary ? kBrand : kLine);
    dc.SetBkMode(TRANSPARENT);
    dc.SetTextColor(primary ? RGB(255, 255, 255) : kInk);
    CFont* oldFont = dc.SelectObject(&font_);
    CString label; GetDlgItem(controlId)->GetWindowTextW(label);
    dc.DrawText(label, rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    if (item->itemState & ODS_FOCUS) {
      rect.DeflateRect(4, 4); dc.DrawFocusRect(rect);
    }
    dc.SelectObject(oldFont); dc.Detach();
  }

  afx_msg void OnSize(UINT type, int cx, int cy) {
    CDialog::OnSize(type, cx, cy);
    if (type != SIZE_MINIMIZED) Layout();
  }

  afx_msg LRESULT OnDpiChanged(WPARAM, LPARAM value) {
    FitToMonitor(reinterpret_cast<const RECT*>(value));
    Layout();
    return 0;
  }

  DECLARE_MESSAGE_MAP()

 private:
  CString text_, kind_, caption_;
  UINT type_ = MB_OK;
  CWnd* parent_ = nullptr;
  bool ready_ = false;
  EmptyDialogTemplate template_{};
  CStatic title_, message_;
  CButton primary_, secondary_;
  CFont font_, titleFont_;
  CBrush whiteBrush_, paleBrush_;
  COLORREF semanticColor_ = kBrand;
  double scale_ = 1.0;
};

BEGIN_MESSAGE_MAP(ThemedMessageDialog, CDialog)
ON_WM_PAINT()
ON_WM_CTLCOLOR()
ON_WM_DRAWITEM()
ON_WM_SIZE()
ON_MESSAGE(WM_DPICHANGED, &ThemedMessageDialog::OnDpiChanged)
END_MESSAGE_MAP()
}  // namespace

int ThemedMessageBox(const CString& text, UINT type, CWnd* parent,
                     const CString& caption) {
  // Prefer the window the operator is currently using.  This keeps messages
  // above login/order/receiving modal dialogs instead of assigning the
  // disabled main frame as their owner.
  if (!parent) {
    const HWND active = ::GetActiveWindow();
    parent = active ? CWnd::FromHandle(active) : AfxGetMainWnd();
  }
  ThemedMessageDialog dialog(text, type, parent, caption);
  const INT_PTR result = dialog.Show();
  if (result >= 0) return static_cast<int>(result);
  const HWND owner = parent ? parent->GetSafeHwnd() : nullptr;
  return ::MessageBoxW(owner, text, caption, type);
}
