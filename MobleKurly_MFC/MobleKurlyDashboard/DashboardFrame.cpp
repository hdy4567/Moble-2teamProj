#include "DashboardFrame.h"
#include "DlgInventory.h"
#include "ErrorHistoryDialog.h"
#include "UiFont.h"
// The layout header is shipped with this project. The fallback below also
// allows an older working folder missing this new header to compile.
#if __has_include("DashboardLayout.h")
#include "DashboardLayout.h"
#else

// UI geometry only. No database, device, or authorization state belongs here.
namespace DashboardLayout {
struct Area { float x, y, w, h; };
inline constexpr float Width = 1536.f, Height = 1000.f;
inline constexpr Area WorkTab{330,16,160,40}, AdminTab{500,16,160,40};
inline constexpr Area Logout{930,18,100,36}, DbRefresh{1288,16,232,40};
inline constexpr Area Emergency{1350,76,170,100};
inline constexpr Area Orders{16,190,647,270}, Processing{16,472,647,228};
inline constexpr Area Outbound{16,712,647,260};
inline constexpr Area Camera{676,190,379,330}, ErrorBin{676,532,379,178};
inline constexpr Area Stock{676,722,379,250}, Graph{1067,190,453,326};
inline constexpr Area SensorLog{1067,528,453,188}, FanLog{1067,728,453,188};
inline constexpr Area Settlement{1067,928,453,44};
inline constexpr int OrderRows = 6;
inline constexpr Area Restock{Stock.x+12,Stock.y+201,Stock.w-24,36};
inline constexpr Area ClearBin{ErrorBin.x+16,ErrorBin.y+134,164,32};
inline constexpr Area BinHistory{ErrorBin.x+196,ErrorBin.y+134,167,32};
inline constexpr Area Reconnect{422,100,125,28};
inline constexpr Area Dispatch(int row) { return {Orders.x+542,Orders.y+77+row*30,83,24}; }
inline constexpr Area Retry(int row) { return {Processing.x+565,Processing.y+77+row*32,60,24}; }
}
#endif

// Existing PDF settlement module from mfc_pdf.
void OpenIntegratedSettlement(bool compact);
CWnd* CreateEmbeddedSettlement(CWnd* parent, const CRect& area);
#include <algorithm>
#include <cmath>
#include <vector>
#include <memory>
#include <winhttp.h>
#include <objidl.h>
#include <mutex>

// [ESTOP] Keep worker replies owned when the dashboard closes.
struct ConveyorMailbox {
  std::mutex mutex;
  HWND hwnd = nullptr;
};

using namespace Gdiplus;
namespace {
constexpr float W = DashboardLayout::Width, H = DashboardLayout::Height;
namespace Layout = DashboardLayout;
const BYTE jpegStart[] = {0xFF, 0xD8};
const BYTE jpegEnd[] = {0xFF, 0xD9};
const Color BACK(255, 246, 248, 250), WHITE(255, 255, 255, 255),
    INK(255, 37, 51, 67), SUB(255, 107, 122, 138);
const Color BORDER(255, 225, 232, 239), BRAND(255, 32, 120, 180),
    PALE(255, 239, 246, 251), NAVY(255, 19, 55, 91);
const Color RED(255, 224, 38, 43), GREEN(255, 17, 160, 83),
    BLUE(255, 27, 113, 236), YELLOW(255, 173, 115, 12);

CString S(int n) {
  CString s;
  s.Format(L"%d", n);
  return s;
}
CString F(double n, int prec = 1) {
  CString s;
  s.Format(prec == 1 ? L"%.1f" : L"%.2f", n);
  return s;
}

void Round(Graphics &g, float x, float y, float w, float h, float r, Color fill,
           Color stroke = BORDER, float sw = 1) {
  GraphicsPath p;
  r = std::min(r, std::min(w, h) / 2.f);
  p.AddArc(x, y, 2 * r, 2 * r, 180, 90);
  p.AddArc(x + w - 2 * r, y, 2 * r, 2 * r, 270, 90);
  p.AddArc(x + w - 2 * r, y + h - 2 * r, 2 * r, 2 * r, 0, 90);
  p.AddArc(x, y + h - 2 * r, 2 * r, 2 * r, 90, 90);
  p.CloseFigure();
  SolidBrush b(fill);
  g.FillPath(&b, &p);
  if (sw > 0) {
    Pen pen(stroke, sw);
    g.DrawPath(&pen, &p);
  }
}
void Line(Graphics &g, float x1, float y1, float x2, float y2, Color c = BORDER,
          float weight = 1) {
  Pen p(c, weight);
  g.DrawLine(&p, x1, y1, x2, y2);
}
void Txt(Graphics &g, const CString &s, float x, float y, float w, float h,
         float size = 13, Color col = INK, bool bold = false,
         StringAlignment align = StringAlignmentNear, bool middle = true) {
  FontFamily fallback(UiFont::Family());
  const FontFamily* family = UiFont::GdiPlusFamily();
  Font font(family ? family : &fallback, size, bold ? FontStyleBold : FontStyleRegular, UnitPixel);
  SolidBrush b(col);
  StringFormat format;
  format.SetAlignment(align);
  format.SetLineAlignment(middle ? StringAlignmentCenter : StringAlignmentNear);
  format.SetTrimming(StringTrimmingEllipsisCharacter);
  format.SetFormatFlags(StringFormatFlagsNoWrap);
  g.DrawString(s.GetString(), -1, &font, RectF(x, y, w, h), &format, &b);
}
void Circle(Graphics &g, float cx, float cy, float r, Color c) {
  SolidBrush b(c);
  g.FillEllipse(&b, cx - r, cy - r, r * 2, r * 2);
}
void Pill(Graphics &g, const CString &value, float x, float y, float w, float h,
          Color bg, Color fg) {
  Round(g, x, y, w, h, 6, bg, bg, 0);
  Txt(g, value, x + 2, y, w - 4, h, 12, fg, true, StringAlignmentCenter);
}
void Panel(Graphics &g, float x, float y, float w, float h,
           const CString &title) {
  Round(g, x, y, w, h, 10, WHITE);
  Line(g, x + 16, y + 42, x + w - 16, y + 42);
  Round(g, x + 15, y + 14, 3, 15, 1.5f, BRAND, BRAND, 0);
  Txt(g, title, x + 27, y + 2, w - 42, 38, 15, NAVY, true);
}
void GridHead(Graphics &g, float x, float y,
              const std::vector<std::pair<CString, float>> &cols) {
  SolidBrush bg(Color(255, 246, 248, 250));
  float sum = 0;
  for (auto &c : cols)
    sum += c.second;
  g.FillRectangle(&bg, x, y, sum, 30.f);
  float xx = x;
  for (auto &c : cols) {
    Txt(g, c.first, xx + 3, y, c.second - 6, 30, 12, SUB, true,
        StringAlignmentCenter);
    xx += c.second;

  }
  Line(g, x, y + 30, x + sum, y + 30);
}
Color StatusColor(const CString &status) {
  if (status == L"PENDING" || status == L"WAITING")
    return YELLOW;
  if (status == L"PROCESSING" || status == L"RUNNING")
    return BLUE;
  if (status == L"COMPLETED" || status == L"SUCCESS" || status == L"DONE")
    return GREEN;
  return RED;
}
CString StatusText(const CString &status) {
  if (status == L"PENDING")
    return L"대기";
  if (status == L"PROCESSING")
    return L"출고 중";
  if (status == L"COMPLETED")
    return L"완료";
  if (status == L"ERROR")
    return L"오류";
  if (status == L"SUCCESS")
    return L"정상 출고";
  if (status == L"UNKNOWN")
    return L"미식별";
  return status;
}
Color Soft(Color c) {
  return Color(255, 255 - (255 - c.GetR()) / 7, 255 - (255 - c.GetG()) / 7,
               255 - (255 - c.GetB()) / 7);
}
bool Hit(float x, float y, float bx, float by, float bw, float bh) {
  return x >= bx && x <= bx + bw && y >= by && y <= by + bh;
}
void Button(Graphics &g, CString label, float x, float y, float w, float h,
            bool primary = false) {
  Round(g, x, y, w, h, 6, primary ? BRAND : WHITE,
        primary ? BRAND : BORDER);
  Txt(g, label, x + 3, y, w - 6, h, 13, primary ? WHITE : INK, primary,
      StringAlignmentCenter);
}
// Painting and pointer hit testing share the same layout rectangles.
bool Hit(float x, float y, const Layout::Area& a) {
  return Hit(x, y, a.x, a.y, a.w, a.h);
}
void Button(Graphics& g, const CString& label, const Layout::Area& a, bool primary = false) {
  Button(g, label, a.x, a.y, a.w, a.h, primary);
}
void NavTab(Graphics& g, const CString& label, const Layout::Area& a, bool selected) {
  Round(g, a.x, a.y, a.w, a.h, 7, selected ? WHITE : NAVY,
        selected ? WHITE : Color(255, 60, 91, 122));
  Txt(g, label, a.x, a.y, a.w, a.h, 14,
      selected ? NAVY : Color(255, 208, 224, 239), true, StringAlignmentCenter);
}

} // namespace

BEGIN_MESSAGE_MAP(DashboardFrame, CFrameWnd)
ON_WM_CREATE()
ON_WM_PAINT()
ON_WM_ERASEBKGND()
ON_WM_SIZE()
ON_WM_TIMER()
ON_WM_LBUTTONDOWN()
ON_WM_DESTROY()
ON_MESSAGE(WM_APP + 30, &DashboardFrame::OnPiResponse)
ON_MESSAGE(WM_APP + 31, &DashboardFrame::OnCameraFrame)
ON_MESSAGE(WM_APP + 32, &DashboardFrame::OnConveyorResponse)
ON_MESSAGE(WM_APP + 33, &DashboardFrame::OnCctvUpdate)
END_MESSAGE_MAP()

    DashboardFrame::DashboardFrame(const CString& userId, const CString& displayName, UserRole role)
    : userId_(userId), displayName_(displayName), role_(role) {
  conveyorMailbox_ = std::make_shared<ConveyorMailbox>();
  GdiplusStartupInput in;
  GdiplusStartup(&gdipToken_, &in, nullptr);
  wchar_t path[MAX_PATH] = {};
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  iniPath_ = path;
  int slash = iniPath_.ReverseFind(L'\\');
  if (slash >= 0)
    iniPath_ = iniPath_.Left(slash + 1) + L"config.ini";
  // Create() synchronously fires WM_CREATE and StartCamera().
  // Settings path must exist BEFORE that point.
  CString cls = AfxRegisterWndClass(
      CS_HREDRAW | CS_VREDRAW, LoadCursor(nullptr, IDC_ARROW),
      reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1), nullptr);
  Create(cls, L"MobleKurly 스마트 재고 관리 시스템 | 통합 대시보드", WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
         CRect(55, 25, 1591, 1049));

}
DashboardFrame::~DashboardFrame() {
  if (gdipToken_)
    GdiplusShutdown(gdipToken_);
}
int DashboardFrame::OnCreate(LPCREATESTRUCT cs) {
  if (CFrameWnd::OnCreate(cs) == -1)
    return -1;
  LoadPiConfig();
  StartCamera();
  SetTimer(1, 3000, nullptr); // 주문 및 대시보드 자동 갱신 (3초)
  conveyorMailbox_->hwnd = GetSafeHwnd();
  SetTimer(2, 1000, nullptr); // [ESTOP] 실물 버튼/컨베이어 상태 갱신
  SendConveyorCommand(0);
  return 0;
}
void DashboardFrame::OnDestroy() {
  KillTimer(1);
  KillTimer(2); // [ESTOP]
  CloseConveyorMailbox();
  if (settlementPane_ && ::IsWindow(settlementPane_->GetSafeHwnd()))
    settlementPane_->DestroyWindow();
  settlementPane_ = nullptr;
  cctvReceiver_.Close();
  cctvFrame_.reset();
  StopCamera();
  cameraFrame_.reset();
  db_.Disconnect();
  CFrameWnd::OnDestroy();
}
BOOL DashboardFrame::OnEraseBkgnd(CDC *) { return TRUE; }
void DashboardFrame::OnSize(UINT type, int cx, int cy) {
  CFrameWnd::OnSize(type, cx, cy);
  if (cx > 0 && cy > 0) {
    PositionEmbeddedSettlement();
    Invalidate(FALSE);
  }
}
void DashboardFrame::OnTimer(UINT_PTR id) {
  if (id == 1)
    RefreshData();
  if (id == 2)
    SendConveyorCommand(0); // [ESTOP] 주문 조회와 별도 통신
  if (id == 2 && activeTab_ == 2) Invalidate(FALSE); // CCTV health status
  CFrameWnd::OnTimer(id);
}
void DashboardFrame::RefreshData() {
  CString error;
  if (!db_.IsConnected() && !db_.Connect(iniPath_, error)) {
    data_.connected = false;
    data_.error = error;
    Invalidate(FALSE);
    return;
  }
  DashboardData fetched;
  if (!db_.Load(fetched, error)) {
    db_.Disconnect();
    data_.connected = false;
    data_.error = error;
    Invalidate(FALSE);
    return;
  }
  data_ = std::move(fetched);
  Invalidate(FALSE);
}
void DashboardFrame::OnPaint() {
  CPaintDC dc(this);
  CRect rc;
  GetClientRect(&rc);
  if (rc.Width() <= 0 || rc.Height() <= 0)
    return;
  CDC mem;
  mem.CreateCompatibleDC(&dc);
  CBitmap bitmap;
  bitmap.CreateCompatibleBitmap(&dc, rc.Width(), rc.Height());
  CBitmap *old = mem.SelectObject(&bitmap);
  {
    Graphics g(mem.GetSafeHdc());
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    float sx = static_cast<float>(rc.Width()) / W,
          sy = static_cast<float>(rc.Height()) / H;
    Draw(g, sx, sy);
  }
  dc.BitBlt(0, 0, rc.Width(), rc.Height(), &mem, 0, 0, SRCCOPY);
  mem.SelectObject(old);
  if (firstRefresh_) {
    firstRefresh_ = false;
    PostMessage(WM_TIMER, 1);
  }
}

void DashboardFrame::Draw(Graphics &g, float sx, float sy) {
  g.ScaleTransform(sx, sy);
  SolidBrush back(BACK);
  g.FillRectangle(&back, 0.f, 0.f, W, H);
  SolidBrush header(NAVY), accent(Color(255, 9, 146, 242));
  g.FillRectangle(&header, 0.f, 0.f, W, 68.f);
  g.FillRectangle(&accent, 0.f, 0.f, W, 3.f);
  Txt(g, L"MobleKurly", 22, 10, 245, 30, 25, WHITE, true);
  Txt(g, L"스마트 물류 관리 시스템", 23, 40, 250, 19, 11, Color(255, 171, 200, 225));
  NavTab(g, L"작업 관리", Layout::WorkTab, activeTab_ == 1);
  NavTab(g, L"관리자", Layout::AdminTab, activeTab_ == 2);
  CString loginLabel;
  loginLabel.Format(L"%s (%s) · %s", displayName_.GetString(),
      userId_.GetString(), role_ == UserRole::Admin ? L"관리자" : L"작업자");
  Txt(g, loginLabel, 684, 15, 225, 38, 13, WHITE, false, StringAlignmentFar);
  NavTab(g, L"로그아웃", Layout::Logout, false);
  SYSTEMTIME now;
  GetLocalTime(&now);
  CString clock;
  clock.Format(L"%04d-%02d-%02d  %02d:%02d:%02d", now.wYear, now.wMonth,
               now.wDay, now.wHour, now.wMinute, now.wSecond);
  Txt(g, clock, 1048, 18, 220, 32, 12, Color(255, 190, 213, 233), false, StringAlignmentFar);
  const auto& dbButton = Layout::DbRefresh;
  Round(g, dbButton.x, dbButton.y, dbButton.w, dbButton.h, 6,
        Color(255, 28, 68, 106), Color(255, 60, 91, 122));
  Circle(g, dbButton.x + 16, dbButton.y + 20, 4, data_.connected ? GREEN : RED);
  const CString dbLabel = activeTab_ == 1
      ? CString(data_.connected ? L"DB 연결됨  ·  새로고침" : L"DB 미연결  ·  새로고침")
      : CString(data_.connected ? L"DB 연결됨" : L"DB 미연결");
  Txt(g, dbLabel,
      dbButton.x + 29, dbButton.y, dbButton.w - 39, dbButton.h, 12, WHITE);
  if (!data_.connected) {
    Txt(g, L"DB 연결 필요: " + data_.error, 18, 976, 1330, 20, 11, RED);
  } else {
    Txt(g, L"MOBLE  /  물류 운영 현황", 18, 976, 500, 20, 10, SUB);
  }
  Txt(g, L"Kurly by MOBLE", 1360, 976, 158, 20, 10, SUB, false, StringAlignmentFar);
  if (activeTab_ == 2) {
    if (role_ == UserRole::Admin) DrawAdminTab(g);
    return;
  }
  // Existing data and control actions are unchanged; only presentation is updated.


  struct Metric {
    CString label, value, sub;
    Color accent;
  };
  CString dash = L"—";
  std::vector<Metric> metrics = {
      {L"대기 주문", data_.connected ? S(data_.pending) : dash, L"승인 대기", BRAND},
      {L"출고 진행", data_.connected ? S(data_.processing) : dash, L"처리 중인 주문", BLUE},
      {L"총 재고 수량", data_.connected ? S(data_.totalStock) : dash, L"색상별 공유 재고", GREEN},
      {L"재고 부족", data_.connected ? S(data_.lowStock) : dash, L"최소 재고 확인", YELLOW},
      {L"오류 수거함", data_.connected ? S(data_.errorCount) + L" / " + S(data_.errorThreshold) : dash, L"수량 / 경고 기준", RED},
      {L"현재 온도", data_.hasSensor ? F(data_.temperature) + L"°C" : dash, L"", BLUE},
      {L"현재 습도", data_.hasSensor ? F(data_.humidity) + L"%" : dash, L"", BLUE},
      {L"팬 상태", data_.hasSensor ? CString(data_.fanOn ? L"작동 중" : L"정지") : dash, L"자동 제어", BRAND}};
  const float cardGap = 9, cardW = (1324.f - cardGap * 7) / 8.f;
  for (size_t i = 0; i < metrics.size(); ++i) {
    const float x = 16 + i * (cardW + cardGap);
    Round(g, x, 76, cardW, 100, 9, WHITE);
    Circle(g, x + 20, 99, 10, Soft(metrics[i].accent));
    Circle(g, x + 20, 99, 4.5f, metrics[i].accent);
    Txt(g, metrics[i].label, x + 34, 83, cardW - 40, 31, 12, INK, true);
    Txt(g, metrics[i].value, x + 14, 112, cardW - 28, 34, 25,
        (i == 4 ? RED : INK), true, StringAlignmentNear);
    Txt(g, metrics[i].sub, x + 14, 148, cardW - 28, 20, 10, SUB, false,
        StringAlignmentNear);
  }
  // [ESTOP] Existing stop/start state and command logic are preserved.
  const bool showRun = conveyorKnown_ && !conveyor_.running && !conveyorStartPending_;
  const bool canStart = showRun && !conveyor_.pressed && !conveyorStopPending_ &&
      GetTickCount64() - conveyorUpdatedAt_ < 2500;
  const Color buttonColor = showRun ? (canStart ? GREEN : SUB) : RED;
  Round(g, Layout::Emergency.x, Layout::Emergency.y, Layout::Emergency.w, Layout::Emergency.h, 10,
        showRun ? Soft(buttonColor) : Color(255, 255, 238, 239), buttonColor, 3);
  if (showRun) {
    Circle(g, 1435, 108, 25, buttonColor);
    Circle(g, 1435, 108, 17, canStart ? Color(255, 65, 190, 120) : Soft(SUB));
    const PointF play[] = {PointF(1428, 96), PointF(1428, 120), PointF(1447, 108)};
    SolidBrush playBrush(WHITE);
    g.FillPolygon(&playBrush, play, 3);
  } else {
    Circle(g, 1435, 108, 25, RED);
    Circle(g, 1435, 108, 17, Color(255, 245, 80, 80));
  }
  Txt(g, showRun ? L"실행" : L"비상 정지", 1366, 134, 137, 26, 17,
      buttonColor, true, StringAlignmentCenter);
  Txt(g, conveyorMessage_, 1360, 158, 150, 14, 10,
      conveyorKnown_ && conveyor_.running ? GREEN : RED, false,
      StringAlignmentCenter);

  DrawOrders(g);
  DrawProcessing(g);
  DrawOutbound(g);
  DrawCamera(g);
  DrawStock(g);
  DrawErrorBin(g);
  DrawGraph(g);
  DrawSensorLog(g);
  DrawFanLog(g);
  Button(g, L"작업 결산 열기", Layout::Settlement, true);

}

void DashboardFrame::DrawOrders(Graphics &g) {
  const auto& areaLayout = Layout::Orders;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g, x, y, w, h, L"주문 목록 (대기)");
  Txt(g, L"자동 갱신 (3초)", x + 476, y + 7, 154, 27, 12,
      GREEN, false, StringAlignmentFar);
  GridHead(g, x + 10, y + 44,
           {{L"주문번호", 77}, {L"주문시간", 98}, {L"상품명", 132},
            {L"지역", 58}, {L"수량", 55}, {L"상태", 112}, {L"출고 제어", 95}});
  for (int i = 0; i < Layout::OrderRows; ++i) {
    const float yy = y + 74 + i * 30.f;
    if (i % 2 == 0) {
      SolidBrush shade(Color(255,252,253,255));
      g.FillRectangle(&shade,x + 10,yy,627.f,30.f);
    }
    if (i < static_cast<int>(data_.orders.size())) {
      const auto &r = data_.orders[i];
      Txt(g,r.id,x + 12,yy,74,30,12,INK,false,StringAlignmentCenter);
      Txt(g,r.time,x + 88,yy,96,30,11,INK,false,StringAlignmentCenter);
      Txt(g,r.product,x + 187,yy,128,30,11);
      Txt(g,r.region,x + 318,yy,56,30,11,INK,false,StringAlignmentCenter);
      Txt(g,r.quantity,x + 376,yy,53,30,12,INK,false,StringAlignmentCenter);
      Pill(g,L"대기",x + 448,yy + 4,86,22,Soft(YELLOW),YELLOW);
      Button(g,L"출고", Layout::Dispatch(i), true);
    } else if (i == 0) {
      Txt(g,L"대기 주문 없음",x + 10,yy,625,30,13,SUB,false,StringAlignmentCenter);
    }
    Line(g,x + 10,yy + 30,x + 637,yy + 30);
  }
}

void DashboardFrame::DrawProcessing(Graphics &g) {
  const auto& areaLayout = Layout::Processing;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g,x,y,w,h,L"처리 목록 (출고 진행 중)");
  GridHead(g,x + 10,y + 44,
           {{L"주문번호",77}, {L"주문시간",98}, {L"상품명",132},
            {L"지역",58}, {L"수량",55}, {L"상태",135}, {L"작업",72}});
  for (int i = 0; i < 4; ++i) {
    const float yy = y + 74 + i * 32.f;
    if (i < static_cast<int>(data_.processingOrders.size())) {
      const auto &r = data_.processingOrders[i];
      Txt(g,r.id,x + 12,yy,74,30,12,INK,false,StringAlignmentCenter);
      Txt(g,r.time,x + 88,yy,96,30,11,INK,false,StringAlignmentCenter);
      Txt(g,r.product,x + 187,yy,128,30,11);
      Txt(g,r.region,x + 318,yy,56,30,11,INK,false,StringAlignmentCenter);
      Txt(g,r.quantity,x + 376,yy,53,30,12,INK,false,StringAlignmentCenter);
      const bool failure = r.status == L"ERROR";
      const bool waiting = r.status == L"WAITING";
      Pill(g,failure ? L"오류 처리중" : (waiting ? L"출고 대기중" : L"출고 중"),
           x + 433,yy + 4,126,22,
           Soft(failure ? RED : (waiting ? YELLOW : BLUE)),
           failure ? RED : (waiting ? YELLOW : BLUE));
      // Preserve the original RETRY_ORDER command, now on the processing panel.
      if (failure)
        Button(g,L"재시도", Layout::Retry(i));
      else
        Txt(g,L"—",x + 565,yy,60,30,12,SUB,false,StringAlignmentCenter);
    } else if (i == 0) {
      Txt(g,L"처리 중인 주문 없음",x + 10,yy,625,30,13,SUB,false,StringAlignmentCenter);
    }
    Line(g,x + 10,yy + 30,x + 637,yy + 30);
  }
}

void DashboardFrame::DrawOutbound(Graphics &g) {
  const auto& areaLayout = Layout::Outbound;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g,x,y,w,h,L"출고 이력 (최근 5건)");
  GridHead(g,x + 10,y + 44,
           {{L"일시",126}, {L"상품명",170}, {L"수량",60},
            {L"결과",110}, {L"출고 경로",161}});
  for (int i = 0; i < 5; ++i) {
    const float yy = y + 74 + i * 32.f;
    if (i < static_cast<int>(data_.outbound.size())) {
      const auto &r = data_.outbound[i];
      Txt(g,r.time,x + 12,yy,120,29,12,INK,false,StringAlignmentCenter);
      Txt(g,r.product,x + 137,yy,166,29,12,INK,false,StringAlignmentCenter);
      Txt(g,r.quantity,x + 308,yy,56,29,12,INK,false,StringAlignmentCenter);
      Pill(g,StatusText(r.result),x + 379,yy + 4,92,22,
           Soft(StatusColor(r.result)),StatusColor(r.result));
      Txt(g,r.detail,x + 484,yy,145,29,12,INK,false,StringAlignmentCenter);
    } else if (i == 0) {
      Txt(g,L"출고 기록 없음",x + 10,yy,627,29,13,SUB,false,StringAlignmentCenter);
    }
    Line(g,x + 10,yy + 30,x + 637,yy + 30);
  }
}

void DashboardFrame::DrawCamera(Graphics &g) {
  const auto& areaLayout = Layout::Camera;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g, x, y, w, h, L"실시간 분류 카메라");
  const RectF area(x + 10.f, y + 47.f, w - 20.f, h - 59.f);
  SolidBrush black(Color(255, 0, 0, 0));
  g.FillRectangle(&black, area);
  if (cameraFrame_ && cameraFrame_->GetWidth() && cameraFrame_->GetHeight()) {
    // Fit the full 640x480 source into the existing dashboard panel.
    const float iw = static_cast<float>(cameraFrame_->GetWidth());
    const float ih = static_cast<float>(cameraFrame_->GetHeight());
    const float scale = std::min(area.Width / iw, area.Height / ih);
    const float dw = iw * scale, dh = ih * scale;
    const RectF target(area.X + (area.Width - dw) / 2.f,
                       area.Y + (area.Height - dh) / 2.f, dw, dh);
    g.DrawImage(cameraFrame_.get(), target);
  } else {
    Txt(g, cameraEnabled_ ? L"카메라 연결 대기 중..." : L"config.ini에서 카메라를 설정하세요",
        area.X + 8, area.Y + area.Height / 2.f - 14, area.Width - 16,
        28, 13, WHITE, false, StringAlignmentCenter);
  }
}

void DashboardFrame::DrawStock(Graphics &g) {
  // Same four color-shared rows and same restock dialog as before; new location.
  const auto& areaLayout = Layout::Stock;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g,x,y,w,h,L"상품 재고 현황");
  GridHead(g,x + 9,y + 44,
           {{L"색상",100}, {L"현재 재고",90},
            {L"최소 재고",90}, {L"상태",81}});
  for (int i = 0; i < 4; ++i) {
    const float yy = y + 74 + i * 27.f;
    if (i < static_cast<int>(data_.stock.size())) {
      const auto &r = data_.stock[i];
      const Color c = r.color == L"RED" ? RED : r.color == L"BLUE" ? BLUE
                    : r.color == L"YELLOW" ? Color(255, 247, 172, 24) : GREEN;
      Circle(g,x + 23,yy + 13,6,c);
      Txt(g,r.color,x + 34,yy,73,26,11,INK);
      Txt(g,r.count,x + 109,yy,90,26,11,INK,false,StringAlignmentCenter);
      Txt(g,r.minStock,x + 199,yy,90,26,11,INK,false,StringAlignmentCenter);
      const bool low = _wtoi(r.count) <= _wtoi(r.minStock);
      Pill(g,low ? L"부족" : L"정상",x + 303,yy + 2,60,22,
           Soft(low ? RED : GREEN),low ? RED : GREEN);
    } else if (i == 0) {
      Txt(g,L"재고 데이터 없음",x + 9,yy,w - 18,26,12,SUB,false,StringAlignmentCenter);
    }
    Line(g,x + 9,yy + 27,x + w - 9,yy + 27);
  }
  Button(g,L"재입고 등록", Layout::Restock, true);
}
void DashboardFrame::DrawErrorBin(Graphics &g) {
  const auto& areaLayout = Layout::ErrorBin;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g, x, y, w, h, L"오류 수거함 상태");
  Txt(g, L"현재 개수", x + 24, y + 51, 148, 24, 12, SUB);
  Txt(g, L"경고 기준", x + 209, y + 51, 144, 24, 12, SUB);
  Txt(g, data_.connected ? S(data_.errorCount) + L" / " + S(data_.errorThreshold) : CString(L"—"),
      x + 24, y + 76, 149, 40, 26, RED, true);
  Txt(g, data_.connected ? S(data_.errorThreshold) + L"개" : CString(L"—"),
      x + 209, y + 76, 140, 40, 22, INK, true);
  Button(g, L"비우기 처리", Layout::ClearBin);
  Button(g, L"이력 보기", Layout::BinHistory);
}
void DashboardFrame::DrawGraph(Graphics &g) {
  const auto& areaLayout = Layout::Graph;
  const float x = areaLayout.x, y = areaLayout.y, w = areaLayout.w, h = areaLayout.h;
  Panel(g, x, y, w, h, L"온습도 그래프 (최근 30건)");
  Circle(g, x + 153, y + 62, 5, RED);
  Txt(g, L"온도 (°C)", x + 164, y + 46, 104, 31, 12, SUB);
  Circle(g, x + 283, y + 62, 5, BLUE);
  Txt(g, L"습도 (%)", x + 294, y + 46, 104, 31, 12, SUB);
  float lx = x + 53, rx = x + w - 31, top = y + 95, bottom = y + 246;
  for (int i = 0; i <= 4; i++) {
    float yy = top + (bottom - top) * i / 4.f;
    Line(g, lx, yy, rx, yy, Color(255, 233, 236, 247));
    Txt(g, S(40 - i * 10), x + 8, yy - 11, 41, 21, 10, SUB, false,
        StringAlignmentFar);
    Txt(g, S(100 - i * 25), rx + 2, yy - 11, 31, 21, 10, BLUE, false,
        StringAlignmentFar);
  }
  if (data_.sensors.size() >= 2) {
    const int n = static_cast<int>(data_.sensors.size());
    Pen tp(RED, 2), hp(BLUE, 2);
    for (int i = 0; i < n - 1; i++) {
      const auto &a = data_.sensors[n - 1 - i], &b = data_.sensors[n - 2 - i];
      float x1 = lx + (rx - lx) * i / (n - 1.f),
            x2 = lx + (rx - lx) * (i + 1) / (n - 1.f);
      float t1 = bottom -
                 (bottom - top) *
                     std::clamp(static_cast<float>(a.temp), 0.0f, 40.0f) / 40.;
      float t2 = bottom -
                 (bottom - top) *
                     std::clamp(static_cast<float>(b.temp), 0.0f, 40.0f) / 40.;
      float h1 =
          bottom - (bottom - top) *
                       std::clamp(static_cast<float>(a.humid), 0.0f, 100.0f) /
                       100.;
      float h2 =
          bottom - (bottom - top) *
                       std::clamp(static_cast<float>(b.humid), 0.0f, 100.0f) /
                       100.;
      g.DrawLine(&tp, x1, t1, x2, t2);
      g.DrawLine(&hp, x1, h1, x2, h2);
    }
    Txt(g, data_.sensors.back().time, lx, bottom + 6, 68, 22, 10, SUB);
    Txt(g, data_.sensors.front().time, rx - 70, bottom + 6, 70, 22, 10, SUB,
        false, StringAlignmentFar);
  } else
    Txt(g, L"그래프를 표시할 센서 데이터가 없습니다", lx, top + 48, rx - lx, 33,
        13, SUB, false, StringAlignmentCenter);
  Line(g, x + 15, y + 277, x + w - 15, y + 277);
  Txt(g, L"현재 온도", x + 22, y + 283, 93, 30, 13, SUB);
  Txt(g, data_.hasSensor ? (F(data_.temperature) + L" °C") : CString(L"—"),
      x + 107, y + 280, 105, 38, 22, INK, true);
  Txt(g, L"현재 습도", x + 235, y + 283, 93, 30, 13, SUB);
  Txt(g, data_.hasSensor ? (F(data_.humidity) + L" %") : CString(L"—"), x + 323,
      y + 280, 119, 38, 22, BLUE, true);
}
void DashboardFrame::DrawSensorLog(Graphics &g) {
  const auto& a = Layout::SensorLog;
  Panel(g, a.x, a.y, a.w, a.h, L"온도 로그");
  Txt(g, L"최근 5건", a.x + a.w - 100, a.y + 7, 78, 28, 11, SUB, false, StringAlignmentFar);
  GridHead(g, a.x + 12, a.y + 44, {{L"측정 시간", 256}, {L"온도 (°C)", 173}});
  for (int i = 0; i < 5; i++) {
    float yy = a.y + 74 + 22 * i;
    if (i < (int)data_.sensors.size()) {
      Txt(g, data_.sensors[i].time, a.x + 16, yy, 248, 22, 12, INK, false, StringAlignmentCenter);
      Txt(g, data_.sensors[i].temperature, a.x + 268, yy, 173, 22, 12, INK, true, StringAlignmentCenter);
    } else if (i == 0)
      Txt(g, L"기록 없음", a.x + 12, yy, a.w - 24, 22, 12, SUB, false, StringAlignmentCenter);
    Line(g, a.x + 12, yy + 22, a.x + a.w - 12, yy + 22);
  }
}
void DashboardFrame::DrawFanLog(Graphics &g) {
  const auto& a = Layout::FanLog;
  Panel(g, a.x, a.y, a.w, a.h, L"팬 동작 로그");
  Txt(g, L"최근 5건", a.x + a.w - 100, a.y + 7, 78, 28, 11, SUB, false, StringAlignmentFar);
  GridHead(g, a.x + 12, a.y + 44, {{L"시작 시각", 152}, {L"종료 시각", 152}, {L"동작 시간", 125}});
  for (int i = 0; i < 5; i++) {
    float yy = a.y + 74 + 22 * i;
    if (i < (int)data_.fans.size()) {
      const auto &r = data_.fans[i];
      Txt(g, r.start, a.x + 12, yy, 152, 22, 12, INK, false, StringAlignmentCenter);
      Txt(g, r.stop, a.x + 164, yy, 152, 22, 12, INK, false, StringAlignmentCenter);
      Txt(g, r.duration, a.x + 316, yy, 125, 22, 12, INK, true, StringAlignmentCenter);
    } else if (i == 0)
      Txt(g, L"기록 없음", a.x + 12, yy, a.w - 24, 22, 12, SUB, false, StringAlignmentCenter);
    Line(g, a.x + 12, yy + 22, a.x + a.w - 12, yy + 22);
  }
}
void DashboardFrame::DrawAdminTab(Graphics &g) {
  // Visual-only frame; actual settlement controls live in the embedded original module.
  Panel(g, 16, 92, 548, 514, L"전체 CCTV");
  Panel(g, 16, 618, 548, 354, L"운영 상태");
  Panel(g, 576, 92, 944, 880, L"매출 및 출고 보고서");
  const bool fresh = cctvFrame_ && cctvSnapshot_.status == CctvStatus::Streaming &&
      GetTickCount64() - cctvFrameAt_ < 3000;
  Txt(g, fresh ? L"영상 수신 중" : L"연결 대기", 298, 100, 108, 28,
      13, fresh ? GREEN : SUB, true, StringAlignmentFar);
  Button(g, L"다시 연결", Layout::Reconnect);

  const RectF area(32, 150, 516, 387);
  SolidBrush videoBackground(Color(255, 22, 26, 34));
  g.FillRectangle(&videoBackground, area);
  if (fresh) {
    const float iw = static_cast<float>(cctvFrame_->GetWidth());
    const float ih = static_cast<float>(cctvFrame_->GetHeight());
    const float scale = std::min(area.Width / iw, area.Height / ih);
    const float dw = iw * scale, dh = ih * scale;
    g.DrawImage(cctvFrame_.get(), RectF(area.X + (area.Width-dw)/2.f,
        area.Y + (area.Height-dh)/2.f, dw, dh));
  } else {
    CString message(cctvSnapshot_.message.c_str());
    if (!cctvDecodeError_.IsEmpty()) message = cctvDecodeError_;
    else if (cctvFrame_ && cctvSnapshot_.status == CctvStatus::Streaming)
      message = L"새 영상 수신 대기 중...";
    Txt(g, message, area.X+30, area.Y+area.Height/2.f-30, area.Width-60,
        40, 21, WHITE, false, StringAlignmentCenter);
    Txt(g, L"라즈베리파이 CCTV 송출 프로그램과 카메라 연결을 확인하세요.",
        area.X+28, area.Y+area.Height/2.f+22, area.Width-56,
        30, 14, Color(255, 190, 197, 212), false, StringAlignmentCenter);
  }
  Txt(g, L"라즈베리파이 · 전체 촬영용 USB 카메라", 32, 545, 516, 26, 13, SUB);
  CString detail = L"실시간 영상";
  if (fresh) detail.Format(L"%u × %u · 실시간 영상", cctvFrame_->GetWidth(),
      cctvFrame_->GetHeight());
  Txt(g, detail, 32, 573, 516, 22, 12, SUB, false, StringAlignmentFar);
  // Read-only presentation of existing dashboard values; no new polling or commands.
  const CString sensorText = data_.hasSensor
      ? F(data_.temperature) + L" °C  /  " + F(data_.humidity) + L" %" : CString(L"—");
  const CString binText = data_.connected
      ? S(data_.errorCount) + L" / " + S(data_.errorThreshold) : CString(L"—");
  const CString labels[] = {L"데이터베이스", L"컨베이어", L"온도 / 습도", L"냉각 팬", L"오류 수거함", L"접속 계정"};
  const CString values[] = {data_.connected ? L"연결됨" : L"미연결", conveyorMessage_,
      sensorText, data_.hasSensor ? CString(data_.fanOn ? L"작동 중" : L"정지") : CString(L"—"),
      binText, displayName_ + L" (" + userId_ + L")"};
  for (int i = 0; i < 6; ++i) {
    const float yy = 674.f + i * 46.f;
    Txt(g, labels[i], 36, yy, 150, 40, 13, SUB);
    Txt(g, values[i], 188, yy, 354, 40, 14, INK, true, StringAlignmentFar);
    if (i < 5) Line(g, 36, yy + 43, 544, yy + 43);
  }

}

void DashboardFrame::PositionEmbeddedSettlement() {
  if (!settlementPane_ || !::IsWindow(settlementPane_->GetSafeHwnd())) return;
  CRect client; GetClientRect(&client);
  if (client.Width() <= 0 || client.Height() <= 0) return;
  const int left = MulDiv(584, client.Width(), static_cast<int>(W));
  const int top = MulDiv(138, client.Height(), static_cast<int>(H));
  const int right = MulDiv(1511, client.Width(), static_cast<int>(W));
  const int bottom = MulDiv(964, client.Height(), static_cast<int>(H));
  settlementPane_->MoveWindow(left, top, right-left, bottom-top);
}
void DashboardFrame::ShowEmbeddedSettlement() {
  if (role_ != UserRole::Admin) return;
  if (!settlementPane_ || !::IsWindow(settlementPane_->GetSafeHwnd())) {
    settlementPane_ = CreateEmbeddedSettlement(this, CRect(0,0,800,820));
  }
  if (settlementPane_ && ::IsWindow(settlementPane_->GetSafeHwnd())) {
    PositionEmbeddedSettlement();
    settlementPane_->ShowWindow(SW_SHOW);
  }
}
void DashboardFrame::StartAdminCctv() {
  if (role_ != UserRole::Admin || activeTab_ != 2) return;
  CctvSettings settings;
  settings.enabled = GetPrivateProfileIntW(L"cctv", L"enabled", 1, iniPath_) != 0;
  wchar_t host[256] = {}, samePi[256] = {}, path[512] = {};
  GetPrivateProfileStringW(L"camera", L"host", piHost_.GetString(), samePi, 256, iniPath_);
  GetPrivateProfileStringW(L"cctv", L"host", L"", host, 256, iniPath_);
  CString chosenHost(host);
  chosenHost.Trim();
  if (chosenHost.IsEmpty()) chosenHost = samePi;
  chosenHost.Trim();
  settings.host = chosenHost.GetString();
  settings.port = static_cast<int>(GetPrivateProfileIntW(L"cctv", L"port", 8081, iniPath_));
  GetPrivateProfileStringW(L"cctv", L"path", L"/video_feed", path, 512, iniPath_);
  settings.path = path;
  cctvFrame_.reset();
  cctvFrameAt_ = 0;
  cctvDecodeError_.Empty();
  cctvSnapshot_ = {};
  cctvSnapshot_.message = L"라즈베리파이 CCTV에 연결 중...";
  cctvReceiver_.Configure(settings, GetSafeHwnd(), WM_APP + 33);
  Invalidate(FALSE);
}

void DashboardFrame::PauseAdminCctv() {
  cctvReceiver_.Pause();
  cctvFrame_.reset();
  cctvFrameAt_ = 0;
  cctvDecodeError_.Empty();
}

LRESULT DashboardFrame::OnCctvUpdate(WPARAM, LPARAM) {
  cctvSnapshot_ = cctvReceiver_.Consume();
  if (role_ != UserRole::Admin || activeTab_ != 2 || !cctvSnapshot_.jpeg) {
    cctvFrame_.reset();
    cctvFrameAt_ = 0;
    cctvDecodeError_.Empty();
    Invalidate(FALSE);
    return 0;
  }
  const auto& jpeg = *cctvSnapshot_.jpeg;
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, jpeg.size());
  if (!memory) return 0;
  void* data = GlobalLock(memory);
  if (!data) { GlobalFree(memory); return 0; }
  memcpy(data, jpeg.data(), jpeg.size());
  GlobalUnlock(memory);
  IStream* raw = nullptr;
  if (FAILED(CreateStreamOnHGlobal(memory, TRUE, &raw))) {
    GlobalFree(memory);
    return 0;
  }
  const auto release = [](IStream* stream) { if (stream) stream->Release(); };
  std::unique_ptr<IStream, decltype(release)> stream(raw, release);
  Gdiplus::Bitmap decoded(stream.get());
  if (decoded.GetLastStatus() == Gdiplus::Ok && decoded.GetWidth() && decoded.GetHeight()) {
    std::unique_ptr<Gdiplus::Bitmap> frame(decoded.Clone(0, 0,
        decoded.GetWidth(), decoded.GetHeight(), PixelFormat32bppARGB));
    if (frame && frame->GetLastStatus() == Gdiplus::Ok) {
      cctvFrame_ = std::move(frame);
      cctvFrameAt_ = cctvSnapshot_.receivedAt;
      cctvDecodeError_.Empty();
      Invalidate(FALSE);
      return 0;
    }
  }
  cctvFrame_.reset();
  cctvDecodeError_ = L"CCTV 영상 형식을 읽을 수 없습니다";
  Invalidate(FALSE);
  return 0;
}


void DashboardFrame::OnLogout() {
  PauseAdminCctv();
  ShowWindow(SW_HIDE);
  LoginDialog login;
  if (login.ShowLogin() != IDOK) {
    PostMessage(WM_CLOSE);
    return;
  }
  userId_ = login.UserId();
  displayName_ = login.DisplayName();
  role_ = login.Role();
  activeTab_ = 1;
  SetWindowTextW(L"MobleKurly 스마트 재고 관리 시스템 | 통합 대시보드");
  ShowWindow(SW_SHOW);
  Invalidate(FALSE);
}

void DashboardFrame::DrawReports(Graphics &g) {
  // Align report left edge with the temperature-log left edge (x=1067).
  // Two columns by two rows keep all four report actions readable in 453px.
  float x = 1067, y = 792, w = 453, h = 208;
  Panel(g, x, y, w, h, L"보고서 내보내기");
  const wchar_t *titles[] = {L"전체 출고 보고서", L"오류 보고서",
                             L"재고 현황 보고서", L"팬 동작 보고서"};
  const wchar_t *subs[] = {L"기간별 출고 기록", L"오류 발생 내역",
                           L"현재 재고 / 변동", L"팬 작동 이력"};
  constexpr float cardW = 209.f, cardH = 66.f;
  for (int i = 0; i < 4; i++) {
    float xx = x + 12 + (i % 2) * 220;
    float yy = y + 53 + (i / 2) * 75;
    Round(g, xx, yy, cardW, cardH, 7, WHITE, Color(255, 213, 215, 244));
    Circle(g, xx + 28, yy + 33, 17, i == 1 ? Soft(RED) : Soft(BRAND));
    Txt(g, i == 1 ? L"!" : L"PDF", xx + 9, yy + 21, 38, 23, 12,
        i == 1 ? RED : BRAND, true, StringAlignmentCenter);
    Txt(g, titles[i], xx + 52, yy + 10, 150, 25, 12, INK, true);
    Txt(g, subs[i], xx + 52, yy + 34, 150, 22, 11, SUB);
  }
}
void DashboardFrame::Placeholder(LPCWSTR name, bool safety) {
  CString msg;
  msg.Format(safety
                 ? L"%s: 장치에 연결되지 않아 정지 요청을 전달할 수 없습니다.\n"
                   L"장치의 비상정지 버튼을 사용해주세요."
                 : L"%s 기능을 현재 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
             name);
  AfxMessageBox(msg, MB_ICONWARNING | MB_OK);
}
void DashboardFrame::OnLButtonDown(UINT flags, CPoint point) {
  CRect rect;
  GetClientRect(&rect);
  if (rect.Width() <= 0 || rect.Height() <= 0)
    return;
  float x = point.x * W / rect.Width(), y = point.y * H / rect.Height();
  if (Hit(x, y, Layout::Logout)) { OnLogout(); return; }
  if (Hit(x, y, Layout::WorkTab)) { PauseAdminCctv(); activeTab_ = 1;
    if (settlementPane_ && ::IsWindow(settlementPane_->GetSafeHwnd())) settlementPane_->ShowWindow(SW_HIDE);
    Invalidate(FALSE); return; }
  if (activeTab_ == 1 && Hit(x, y, Layout::Settlement)) {
    OpenIntegratedSettlement(true); return;
  }
  if (Hit(x, y, Layout::AdminTab)) {
    if (role_ != UserRole::Admin) {
      AfxMessageBox(L"관리자 계정으로 로그인해주세요.", MB_ICONWARNING);
      return;
    }
    activeTab_ = 2; StartAdminCctv(); ShowEmbeddedSettlement(); Invalidate(FALSE); return;
  }
  if (activeTab_ == 2) {
    if (role_ != UserRole::Admin) { activeTab_ = 1; Invalidate(FALSE); return; }
    if (Hit(x, y, Layout::Reconnect)) { StartAdminCctv(); return; }
    return;
  }
  if (Hit(x, y, Layout::Emergency)) {
    // [ESTOP] 확인된 정지 상태에서는 실행, 그 외에는 정지. 실행 응답 대기 중에도 정지 가능.
    const bool showRun = conveyorKnown_ && !conveyor_.running && !conveyorStartPending_;
    SendConveyorCommand(showRun ? 2 : 1);
    return;
  }
  if (Hit(x, y, Layout::DbRefresh)) {
    RefreshData();
    if (!data_.connected)
      AfxMessageBox(data_.error, MB_ICONWARNING);
    return;
  }
  // Each shipment button belongs to one visible order row.
  for (int i = 0; i < Layout::OrderRows && i < static_cast<int>(data_.orders.size()); ++i) {
    if (!Hit(x, y, Layout::Dispatch(i))) continue;
    // Copy values before RefreshData replaces the vector (avoid dangling references).
    const CString orderId = data_.orders[i].id;
    const CString status = data_.orders[i].status;
    if (status == L"PENDING") {
      // Phase 1: forward an order ID to Pi. Do NOT decrement stock on TCP ACK.
      SendPiCommand(L"DISPATCH_ORDER", orderId);
    } else if (status == L"ERROR") {
      SendPiCommand(L"RETRY_ORDER", orderId);
    }
    return;
  }
  // Retry hit area matches the visible processing row.
  for (int i = 0; i < 4 && i < static_cast<int>(data_.processingOrders.size()); ++i) {
    if (!Hit(x, y, Layout::Retry(i))) continue;
    const CString orderId = data_.processingOrders[i].id;
    const CString status = data_.processingOrders[i].status;
    if (status == L"ERROR") SendPiCommand(L"RETRY_ORDER",orderId);
    return;
  }
  if (Hit(x, y, Layout::Restock)) {
    CDlgColorRestock dlg;
    if (dlg.DoModal(this, &db_) == IDOK)
      RefreshData();
    return;
  }
  if (Hit(x, y, Layout::ClearBin)) {
    ClearErrorBin();
    return;
  }
  if (Hit(x, y, Layout::BinHistory)) {
    ShowErrorHistory();
    return;
  }
  CFrameWnd::OnLButtonDown(flags, point);
}

void DashboardFrame::ClearErrorBin() {
  if (!db_.IsConnected()) RefreshData();
  if (!db_.IsConnected()) {
    AfxMessageBox(L"서버에 연결되지 않았습니다. 연결 상태를 확인해주세요.", MB_ICONWARNING);
    return;
  }
  if (AfxMessageBox(L"오류 수거함 비우기 처리를 완료하시겠습니까?\n\n"
                   L"수거함을 비운 후 확인을 눌러주세요.",
                   MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return;
  int cleared = 0;
  CString error;
  if (!db_.ClearErrorBin(cleared, error)) {
    AfxMessageBox(L"오류 수거함을 비우기 처리하지 못했습니다.\n" + error, MB_ICONWARNING);
    return;
  }
  RefreshData();
  AfxMessageBox(L"오류 수거함 비우기 처리가 완료되었습니다.", MB_OK | MB_ICONINFORMATION);
}

void DashboardFrame::ShowErrorHistory() {
  if (!db_.IsConnected()) RefreshData();
  if (!db_.IsConnected()) {
    AfxMessageBox(L"서버에 연결되지 않았습니다. 연결 상태를 확인해주세요.", MB_ICONWARNING);
    return;
  }
  ErrorHistoryDialog dialog;
  if (dialog.Show(this, &db_) == -1)
    AfxMessageBox(L"오류 발생 이력 창을 열지 못했습니다.", MB_ICONWARNING);
}

namespace {
struct PiTask {
  HWND hwnd = nullptr;
  CString host;
  int port = 5055;
  CString line;
  CString requestId;
};
struct PiTaskResult {
  bool ok = false;
  CString explanation;
};
UINT PiWorker(LPVOID ptr) {
  std::unique_ptr<PiTask> task(static_cast<PiTask*>(ptr));
  PiReply r = PiTcpClient::Send(task->host, task->port, task->line);
  std::unique_ptr<PiTaskResult> result(new PiTaskResult());
  CString prefix;
  prefix.Format(L"ACK|%s|", task->requestId.GetString());
  CString pong;
  pong.Format(L"PONG|%s", task->requestId.GetString());
  // ACK only confirms queueing; it never confirms physical shipment.
  result->ok = r.message.Left(prefix.GetLength()) == prefix || r.message == pong;
  if (r.message.Left(4) == L"ERR|") result->ok = false;
  result->explanation = r.message;
  if (!result->ok && r.ok == false && result->explanation.IsEmpty())
    result->explanation = L"TCP 응답 오류";
  if (IsWindow(task->hwnd) && PostMessage(task->hwnd, WM_APP + 30, 0,
                                          reinterpret_cast<LPARAM>(result.get())))
    result.release();
  return 0;
}
} // namespace

void DashboardFrame::LoadPiConfig() {
  // Always read the config beside the running EXE. Changes are applied on
  // the next TCP command, without restarting the dashboard.
  wchar_t enabled[32] = {};
  GetPrivateProfileStringW(L"pi", L"enabled", L"0", enabled, 32, iniPath_);
  CString enabledValue(enabled);
  enabledValue.Trim();
  piEnabled_ = enabledValue == L"1";

  wchar_t host[256] = {};
  GetPrivateProfileStringW(L"pi", L"host", L"127.0.0.1", host, 256, iniPath_);
  piHost_ = host;
  piHost_.Trim();
  piPort_ = GetPrivateProfileIntW(L"pi", L"port", 5055, iniPath_);
}
void DashboardFrame::SendPiCommand(const CString &command, const CString &orderId) {
  if (command == L"DISPATCH_ORDER" || command == L"RETRY_ORDER") {
    CString prompt;
    prompt.Format(command == L"RETRY_ORDER"
        ? L"주문 %s\n\n출고를 다시 시도하시겠습니까?"
        : L"주문 %s\n\n출고 처리하시겠습니까?", orderId.GetString());
    if (AfxMessageBox(prompt, MB_ICONQUESTION | MB_YESNO | MB_DEFBUTTON2) != IDYES)
      return;
  }
  // Re-read on every click: settings edited after launch also take effect.
  LoadPiConfig();
  Invalidate(FALSE);
  if (!piEnabled_) {
    CString msg;
    msg = L"출고 장치 연결이 비활성화되어 있습니다.\n연결 설정을 확인해주세요.";
    AfxMessageBox(msg, MB_ICONINFORMATION | MB_OK);
    return;
  }
  if (piBusy_) {
    AfxMessageBox(L"이전 요청을 처리하고 있습니다. 잠시 후 다시 시도해주세요.", MB_ICONINFORMATION);
    return;
  }
  if (piPort_ < 1 || piPort_ > 65535 || piHost_.IsEmpty()) {
    AfxMessageBox(L"출고 장치의 연결 설정을 확인해주세요.", MB_ICONWARNING);
    return;
  }
  // Avoid delimiters, multiline input, and oversized requests.
  if (orderId.GetLength() > 16 || orderId.FindOneOf(L"|\r\n") >= 0) return;
  auto task = std::unique_ptr<PiTask>(new PiTask());
  task->hwnd = GetSafeHwnd();
  task->host = piHost_;
  task->port = piPort_;
  task->requestId.Format(L"MFC-%lu", ++piRequestNumber_);
  task->line.Format(L"%s|%s|%s", command.GetString(), orderId.IsEmpty() ? L"-" : orderId.GetString(),
                    task->requestId.GetString());
  piBusy_ = true;
  if (!AfxBeginThread(&PiWorker, task.get())) {
    piBusy_ = false;
    AfxMessageBox(L"출고 요청을 시작하지 못했습니다. 다시 시도해주세요.", MB_ICONWARNING);
    return;
  }
  task.release();
}
LRESULT DashboardFrame::OnPiResponse(WPARAM, LPARAM lp) {
  std::unique_ptr<PiTaskResult> r(reinterpret_cast<PiTaskResult*>(lp));
  piBusy_ = false;
  CString msg;
  if (r->ok)
    msg = L"출고 요청을 접수했습니다.\n진행 상황은 처리 목록에서 확인해주세요.";
  else
    msg.Format(L"출고 요청을 처리하지 못했습니다.\n\n%s", r->explanation.GetString());
  AfxMessageBox(msg, (r->ok ? MB_ICONINFORMATION : MB_ICONWARNING) | MB_OK);
  return 0;
}

// 
void DashboardFrame::OnClickPlaceOrder() {
  CDlgPlaceOrder dlg;
  if (dlg.DoModal(this, &db_) == IDOK) {
    RefreshData();
  }
}

void DashboardFrame::OnClickReceiveStock() {
  CDlgReceiveStock dlg;
  if (dlg.DoModal(this, &db_) == IDOK) {
    RefreshData();
  }
}


// Camera HTTP/MJPEG receiver. Runs off the UI thread so stalled network I/O
// cannot freeze order dispatch, inventory dialogs or the dashboard.
void DashboardFrame::StartCamera() {
  wchar_t enabled[16] = {};
  GetPrivateProfileStringW(L"camera", L"enabled", L"0", enabled, 16, iniPath_);
  cameraEnabled_ = (CString(enabled) == L"1");
  if (!cameraEnabled_) return;

  wchar_t host[256] = {}, path[256] = {};
  GetPrivateProfileStringW(L"camera", L"host", L"127.0.0.1", host, 256, iniPath_);
  GetPrivateProfileStringW(L"camera", L"path", L"/video_feed", path, 256, iniPath_);
  cameraHost_ = host;
  cameraPath_ = path;
  cameraPort_ = GetPrivateProfileIntW(L"camera", L"port", 5000, iniPath_);
  if (cameraHost_.IsEmpty() || cameraPath_.IsEmpty() || cameraPort_ <= 0 || cameraPort_ > 65535)
    return;

  cameraStop_ = false;
  const HWND hwnd = GetSafeHwnd();
  const CString hostName = cameraHost_, endpoint = cameraPath_;
  const INTERNET_PORT port = static_cast<INTERNET_PORT>(cameraPort_);
  cameraThread_ = std::thread([this, hwnd, hostName, endpoint, port]() {
    while (!cameraStop_) {
      HINTERNET session = WinHttpOpen(L"MobleKurly-MFC-Camera/1.0",
          WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME,
          WINHTTP_NO_PROXY_BYPASS, 0);
      HINTERNET connection = nullptr, request = nullptr;
      if (session) {
        WinHttpSetTimeouts(session, 2000, 2000, 2000, 1300);
        connection = WinHttpConnect(session, hostName, port, 0);
        if (connection) request = WinHttpOpenRequest(connection, L"GET", endpoint,
            nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
      }
      if (request && WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS,
                                        0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
                     WinHttpReceiveResponse(request, nullptr)) {
        DWORD status = 0, size = sizeof(status);
        if (WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                WINHTTP_HEADER_NAME_BY_INDEX, &status, &size,
                                WINHTTP_NO_HEADER_INDEX) && status == 200) {
          std::vector<BYTE> bytes;
          bytes.reserve(131072);
          ULONGLONG lastPosted = 0;
          BYTE buf[8192];
          while (!cameraStop_) {
            DWORD read = 0;
            if (!WinHttpReadData(request, buf, sizeof(buf), &read) || read == 0) break;
            bytes.insert(bytes.end(), buf, buf + read);
            // MJPEG parts carry JPEG SOI (FF D8) and EOI (FF D9) markers.
            // Limit buffering to guard against malformed/unreachable streams.
            for (;;) {
              auto start = std::search(bytes.begin(), bytes.end(),
                                      std::begin(jpegStart), std::end(jpegStart));
              if (start == bytes.end()) { bytes.clear(); break; }
              if (start != bytes.begin()) bytes.erase(bytes.begin(), start);
              auto end = std::search(bytes.begin() + 2, bytes.end(),
                                    std::begin(jpegEnd), std::end(jpegEnd));
              if (end == bytes.end()) break;
              const size_t count = static_cast<size_t>(end - bytes.begin()) + 2;
              const ULONGLONG now = GetTickCount64();
              if (now - lastPosted >= 100 && count < 2 * 1024 * 1024) {
                auto *frame = new std::vector<BYTE>(bytes.begin(), bytes.begin() + count);
                if (!::PostMessageW(hwnd, WM_APP + 31, 0, reinterpret_cast<LPARAM>(frame)))
                  delete frame;
                lastPosted = now;
              }
              bytes.erase(bytes.begin(), bytes.begin() + count);
            }
            if (bytes.size() > 2 * 1024 * 1024) bytes.clear();
          }
        }
      }
      if (request) WinHttpCloseHandle(request);
      if (connection) WinHttpCloseHandle(connection);
      if (session) WinHttpCloseHandle(session);
      // Short interruptible reconnect delay.
      for (int i = 0; i < 10 && !cameraStop_; ++i) Sleep(100);
    }
  });
}

void DashboardFrame::StopCamera() {
  cameraStop_ = true;
  if (cameraThread_.joinable()) cameraThread_.join();
  // Drain any pending frames posted before thread shutdown.
  MSG message;
  while (PeekMessage(&message, GetSafeHwnd(), WM_APP + 31, WM_APP + 31, PM_REMOVE))
    delete reinterpret_cast<std::vector<BYTE> *>(message.lParam);
}

LRESULT DashboardFrame::OnCameraFrame(WPARAM, LPARAM param) {
  std::unique_ptr<std::vector<BYTE>> jpeg(reinterpret_cast<std::vector<BYTE> *>(param));
  if (!jpeg || jpeg->empty()) return 0;
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, jpeg->size());
  if (!memory) return 0;
  void *ptr = GlobalLock(memory);
  if (!ptr) { GlobalFree(memory); return 0; }
  memcpy(ptr, jpeg->data(), jpeg->size());
  GlobalUnlock(memory);
  IStream *stream = nullptr;
  if (FAILED(CreateStreamOnHGlobal(memory, TRUE, &stream))) {
    GlobalFree(memory);
    return 0;
  }
  Gdiplus::Bitmap decoded(stream);
  if (decoded.GetLastStatus() == Gdiplus::Ok && decoded.GetWidth() > 0 && decoded.GetHeight() > 0) {
    std::unique_ptr<Gdiplus::Bitmap> frame(decoded.Clone(0, 0, decoded.GetWidth(),
        decoded.GetHeight(), PixelFormat32bppARGB));
    if (frame && frame->GetLastStatus() == Gdiplus::Ok) {
      cameraFrame_ = std::move(frame);
      Invalidate(FALSE);
    }
  }
  stream->Release();
  return 0;
}

// [ESTOP BEGIN] Conveyor control has its own worker and reply channel.
namespace {
struct ConveyorTask {
  std::shared_ptr<ConveyorMailbox> mailbox;
  CString host, line, requestId;
  int port = 5055;
  int kind = 0;
  unsigned long generation = 0;
};
struct ConveyorResult {
  int kind = 0;
  unsigned long generation = 0;
  bool ok = false;
  ConveyorSnapshot snapshot;
  CString explanation;
};
UINT ConveyorWorker(LPVOID ptr) {
  std::unique_ptr<ConveyorTask> task(static_cast<ConveyorTask *>(ptr));
  auto result = std::make_unique<ConveyorResult>();
  result->kind = task->kind;
  result->generation = task->generation;
  const PiReply reply = PiTcpClient::Send(task->host, task->port, task->line);
  result->explanation = reply.message;
  result->ok = ParseConveyorReply(reply.message.GetString(),
                                 task->requestId.GetString(), result->snapshot);
  if (result->ok && task->kind == 1 && result->snapshot.running) result->ok = false;
  if (result->ok && task->kind == 2 && !result->snapshot.running) result->ok = false;
  std::lock_guard<std::mutex> lock(task->mailbox->mutex);
  if (task->mailbox->hwnd &&
      PostMessage(task->mailbox->hwnd, WM_APP + 32, 0,
                  reinterpret_cast<LPARAM>(result.get()))) result.release();
  return 0;
}
} // namespace

void DashboardFrame::CloseConveyorMailbox() {
  {
    std::lock_guard<std::mutex> lock(conveyorMailbox_->mutex);
    conveyorMailbox_->hwnd = nullptr;
  }
  MSG message;
  while (PeekMessage(&message, GetSafeHwnd(), WM_APP + 32, WM_APP + 32, PM_REMOVE))
    delete reinterpret_cast<ConveyorResult *>(message.lParam);
}

void DashboardFrame::SendConveyorCommand(int kind) {
  LoadPiConfig();
  if (!piEnabled_ || piHost_.IsEmpty() || piPort_ < 1 || piPort_ > 65535) {
    conveyorKnown_ = false;
    conveyorMessage_ = L"Pi 연결 설정 필요";
    Invalidate(FALSE);
    if (kind != 0)
      AfxMessageBox(L"컨베이어 연결 설정을 확인해주세요.", MB_ICONWARNING);
    return;
  }
  if (kind == 0 && (conveyorPollPending_ || conveyorStopPending_ || conveyorStartPending_))
    return;
  if (kind == 1 && conveyorStopPending_) return;
  if (kind == 2) {
    if (conveyorStopPending_ || conveyorStartPending_) return;
    if (!conveyorKnown_ || GetTickCount64() - conveyorUpdatedAt_ >= 2500) {
      conveyorMessage_ = L"상태 확인 후 실행";
      SendConveyorCommand(0);
      Invalidate(FALSE);
      return;
    }
    if (conveyor_.pressed) {
      AfxMessageBox(L"실물 비상정지 버튼이 눌려 있습니다. 해제 후 실행을 눌러주세요.", MB_ICONWARNING);
      return;
    }
    if (conveyor_.running) return;
  }
  auto task = std::make_unique<ConveyorTask>();
  task->mailbox = conveyorMailbox_;
  task->host = piHost_;
  task->port = piPort_;
  task->kind = kind;
  if (kind != 0) ++conveyorGeneration_; // old poll/start cannot overwrite a later STOP
  task->generation = conveyorGeneration_;
  task->requestId.Format(L"MFC-C%lu", ++piRequestNumber_);
  CString argument = L"-";
  if (kind == 2) argument.Format(L"%lu", static_cast<unsigned long>(conveyor_.revision));
  const wchar_t *command = kind == 1 ? L"EMERGENCY_STOP" :
                          kind == 2 ? L"START_CONVEYOR" : L"CONVEYOR_STATUS";
  task->line.Format(L"%s|%s|%s", command, argument.GetString(), task->requestId.GetString());
  if (kind == 0) conveyorPollPending_ = true;
  if (kind == 1) {
    conveyorStopPending_ = true;
    conveyorStartPending_ = false;
    conveyorKnown_ = false;
    conveyorMessage_ = L"정지 응답 대기 중";
  }
  if (kind == 2) {
    conveyorStartPending_ = true;
    conveyorMessage_ = L"실행 응답 대기 중";
  }
  if (!AfxBeginThread(&ConveyorWorker, task.get())) {
    if (kind == 0) conveyorPollPending_ = false;
    if (kind == 1) conveyorStopPending_ = false;
    if (kind == 2) conveyorStartPending_ = false;
    conveyorKnown_ = false;
    conveyorMessage_ = L"제어 스레드 오류";
  } else task.release();
  Invalidate(FALSE);
}

LRESULT DashboardFrame::OnConveyorResponse(WPARAM, LPARAM lp) {
  std::unique_ptr<ConveyorResult> result(reinterpret_cast<ConveyorResult *>(lp));
  if (result->kind == 0) conveyorPollPending_ = false;
  if (result->generation != conveyorGeneration_) return 0;
  if (result->kind == 1) conveyorStopPending_ = false;
  if (result->kind == 2) conveyorStartPending_ = false;
  conveyorKnown_ = result->ok;
  if (result->ok) {
    conveyor_ = result->snapshot;
    conveyorUpdatedAt_ = GetTickCount64();
    conveyorMessage_ = conveyor_.pressed ? L"실물 버튼 눌림" :
                        conveyor_.running ? L"컨베이어 가동 중" : L"정지 · 실행 대기";
  } else {
    conveyorMessage_ = L"통신 오류 · 상태 미확인";
    if (result->kind != 0) {
      CString message;
      message.Format(L"컨베이어를 제어하지 못했습니다:\n%s", result->explanation.GetString());
      AfxMessageBox(message, MB_ICONWARNING);
    }
  }
  Invalidate(FALSE);
  return 0;
}
// [ESTOP END]
