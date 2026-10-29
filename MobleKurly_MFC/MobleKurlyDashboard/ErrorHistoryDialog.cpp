#include "ErrorHistoryDialog.h"
#include "UiFont.h"
#pragma comment(lib, "comctl32.lib")

namespace {
constexpr UINT kRefresh = 5601, kList = 5602;
struct HistoryTemplate { DLGTEMPLATE dialog; WORD menu, windowClass, title; };
}
BEGIN_MESSAGE_MAP(ErrorHistoryDialog, CDialog)
ON_WM_PAINT()
ON_WM_CTLCOLOR()
ON_BN_CLICKED(kRefresh, &ErrorHistoryDialog::OnRefresh)
END_MESSAGE_MAP()

INT_PTR ErrorHistoryDialog::Show(CWnd* parent, Database* database) {
  database_ = database;
  INITCOMMONCONTROLSEX controls = {sizeof(controls), ICC_LISTVIEW_CLASSES};
  if (!InitCommonControlsEx(&controls)) return -1;
  HistoryTemplate tpl = {};
  tpl.dialog.style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME;
  tpl.dialog.cx = 600; tpl.dialog.cy = 330;
  if (!InitModalIndirect(&tpl.dialog, parent)) return -1;
  return DoModal();
}

BOOL ErrorHistoryDialog::OnInitDialog() {
  CDialog::OnInitDialog();
  SetWindowTextW(L"모블 컬리 | 오류 발생 이력");
  SetWindowPos(nullptr, 0, 0, 1080, 620, SWP_NOMOVE | SWP_NOZORDER);
  CenterWindow();
  CRect client; GetClientRect(&client);
  const int right = client.Width() - 24, bottom = client.Height() - 20;
  background_.CreateSolidBrush(RGB(255,255,255));
  header_.CreateSolidBrush(RGB(239,246,251));
  font_.CreatePointFont(100, UiFont::Family());
  titleFont_.CreatePointFont(150, UiFont::Family());
  title_.Create(L"오류 발생 이력", WS_CHILD | WS_VISIBLE,
                CRect(24, 20, right, 55), this);
  title_.SetFont(&titleFont_);
  note_.Create(L"오류 발생 시각 기준 최신 200건 · 수거함을 비워도 오류 기록은 유지됩니다.",
               WS_CHILD | WS_VISIBLE, CRect(24, 65, right, 90), this);
  note_.SetFont(&font_);
  list_.Create(WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_BORDER | LVS_REPORT |
               LVS_SINGLESEL | LVS_SHOWSELALWAYS | LVS_NOSORTHEADER,
               CRect(24, 104, right, bottom - 66), this, kList);
  list_.SetFont(&font_);
  list_.SetExtendedStyle(LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER);
  list_.SetBkColor(RGB(255,255,255));
  list_.SetTextBkColor(RGB(255,255,255));
  list_.SetTextColor(RGB(37,51,67));
  const wchar_t* columns[] = {L"발생 시각", L"이력 번호", L"주문번호", L"예상 상품",
                             L"검출 상품", L"판정 결과", L"배출 위치"};
  const int widths[] = {165, 75, 110, 170, 170, 90, 120};
  for (int i = 0; i < 7; ++i) list_.InsertColumn(i, columns[i], LVCFMT_LEFT, widths[i]);
  status_.Create(L"조회 중…", WS_CHILD | WS_VISIBLE,
                 CRect(24, bottom - 48, right - 265, bottom - 12), this);
  status_.SetFont(&font_);
  refresh_.Create(L"새로고침", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                  CRect(right - 240, bottom - 44, right - 126, bottom - 6), this, kRefresh);
  close_.Create(L"닫기", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                CRect(right - 114, bottom - 44, right, bottom - 6), this, IDOK);
  refresh_.SetFont(&font_); close_.SetFont(&font_);
  OnRefresh();
  return TRUE;
}

void ErrorHistoryDialog::OnRefresh() {
  list_.DeleteAllItems();
  std::vector<std::vector<CString>> rows;
  CString error;
  if (!database_ || !database_->LoadErrorHistory(rows, error)) {
    status_.SetWindowTextW(L"조회 실패 · 오류 기록이 없다는 뜻은 아닙니다.");
    if (error.IsEmpty()) error = L"서버 연결 상태를 확인해주세요.";
    AfxMessageBox(error, MB_ICONWARNING);
    return;
  }
  for (const auto& row : rows) {
    if (row.size() < 7) continue;
    const int index = list_.InsertItem(list_.GetItemCount(), row[0]);
    for (int col = 1; col < 7; ++col) {
      CString value = row[col];
      if (col == 2 && value != L"-") value.Format(L"MK-%06lld", _wtoi64(row[col]));
      list_.SetItemText(index, col, value);
    }
  }
  CString summary;
  if (rows.empty()) summary = L"등록된 오류 발생 기록이 없습니다.";
  else summary.Format(L"최신순 %d건 · 비운 이력은 표시하지 않습니다.", list_.GetItemCount());
  status_.SetWindowTextW(summary);
}

void ErrorHistoryDialog::OnPaint() {
  CPaintDC dc(this); CRect r; GetClientRect(&r);
  dc.FillSolidRect(r,RGB(255,255,255));
  dc.FillSolidRect(0,0,r.Width(),94,RGB(239,246,251));
  dc.FillSolidRect(0,0,r.Width(),3,RGB(32,120,180));
  dc.FillSolidRect(24,94,r.Width()-48,1,RGB(225,232,239));
}
HBRUSH ErrorHistoryDialog::OnCtlColor(CDC* dc,CWnd* wnd,UINT type) {
  if(type==CTLCOLOR_STATIC){
    const bool title=wnd->GetSafeHwnd()==title_.GetSafeHwnd();
    const bool header=title || wnd->GetSafeHwnd()==note_.GetSafeHwnd();
    dc->SetBkMode(TRANSPARENT);
    dc->SetTextColor(title ? RGB(19,55,91) : RGB(107,122,138));
    return static_cast<HBRUSH>((header ? header_ : background_).GetSafeHandle());
  }
  return CDialog::OnCtlColor(dc,wnd,type);
}
