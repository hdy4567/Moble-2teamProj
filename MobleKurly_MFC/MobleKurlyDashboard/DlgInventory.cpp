#include "DlgInventory.h"
#include "UiFont.h"

// 컨트롤 ID 상수
constexpr UINT IDC_DLG_COMBO_PRODUCT = 2001;
constexpr UINT IDC_DLG_EDIT_QTY = 2002;
constexpr UINT IDC_DLG_COMBO_PO = 2003;

// ==========================================
// CDlgPlaceOrder 구현 (발주 등록)
// ==========================================
BEGIN_MESSAGE_MAP(CDlgPlaceOrder, CWnd)
ON_WM_CREATE()
ON_WM_SETFOCUS()
ON_BN_CLICKED(IDOK, &CDlgPlaceOrder::OnBtnOk)
ON_COMMAND(IDOK, &CDlgPlaceOrder::OnBtnOk)
ON_BN_CLICKED(IDCANCEL, &CDlgPlaceOrder::OnBtnCancel)
ON_COMMAND(IDCANCEL, &CDlgPlaceOrder::OnBtnCancel)
ON_CBN_SELCHANGE(IDC_DLG_COMBO_PRODUCT, &CDlgPlaceOrder::OnSelChangeProduct)
END_MESSAGE_MAP()

INT_PTR CDlgPlaceOrder::DoModal(CWnd *pParent, Database *pDb,
                                int initialProductId) {
  pDb_ = pDb;
  initialProductId_ = initialProductId;
  modalResult_ = IDCANCEL;
  modalRunning_ = true;

  CString cls = AfxRegisterWndClass(CS_HREDRAW | CS_VREDRAW,
                                    LoadCursor(nullptr, IDC_ARROW),
                                    (HBRUSH)(COLOR_BTNFACE + 1));
  int w = 440, h = 280;
  CRect pRc(100, 100, 900, 700);
  if (pParent && pParent->GetSafeHwnd())
    pParent->GetWindowRect(&pRc);
  int x = pRc.left + (pRc.Width() - w) / 2;
  int y = pRc.top + (pRc.Height() - h) / 2;

  if (!CreateEx(WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, cls,
                L"자재 발주 등록 (Purchase Order)",
                WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                CRect(x, y, x + w, y + h), pParent, 0)) {
    return IDCANCEL;
  }

  if (pParent && pParent->GetSafeHwnd())
    pParent->EnableWindow(FALSE);

  ShowWindow(SW_SHOWNORMAL);
  UpdateWindow();
  SetForegroundWindow();
  SetActiveWindow();
  editQty_.SetFocus();
  editQty_.SetSel(0, -1);

  MSG msg;
  while (modalRunning_ && GetMessage(&msg, nullptr, 0, 0)) {
    if (msg.message == WM_KEYDOWN) {
      if (msg.wParam == VK_ESCAPE) {
        EndModal(IDCANCEL);
        break;
      }
      if (msg.wParam == VK_RETURN) {
        OnBtnOk();
        break;
      }
      if (msg.wParam == VK_TAB) {
        bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        CWnd *pCur = GetFocus();
        CWnd *pNext = GetNextDlgTabItem(pCur, shift ? TRUE : FALSE);
        if (pNext)
          pNext->SetFocus();
        continue;
      }
    }
    TranslateMessage(&msg);
    DispatchMessage(&msg);
  }

  if (pParent && pParent->GetSafeHwnd()) {
    pParent->EnableWindow(TRUE);
    pParent->SetActiveWindow();
    pParent->SetForegroundWindow();
    pParent->SetFocus();
  }
  DestroyWindow();
  return modalResult_;
}

void CDlgPlaceOrder::OnSetFocus(CWnd *pOldWnd) {
  CWnd::OnSetFocus(pOldWnd);
  if (editQty_.GetSafeHwnd())
    editQty_.SetFocus();
}

void CDlgPlaceOrder::EndModal(INT_PTR result) {
  modalResult_ = result;
  modalRunning_ = false;
}

int CDlgPlaceOrder::OnCreate(LPCREATESTRUCT lpCreateStruct) {
  if (CWnd::OnCreate(lpCreateStruct) == -1)
    return -1;

  fontTitle_.CreatePointFont(105, UiFont::Family());
  fontNormal_.CreatePointFont(95, UiFont::Family());

  lblTitle_.Create(L"📦 자재 구매 발주 등록", WS_CHILD | WS_VISIBLE,
                   CRect(25, 18, 400, 42), this);
  lblTitle_.SetFont(&fontTitle_);

  lblProduct_.Create(L"발주 대상 품목:", WS_CHILD | WS_VISIBLE,
                     CRect(25, 48, 400, 68), this);
  lblProduct_.SetFont(&fontNormal_);

  comboProduct_.Create(WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL |
                           WS_TABSTOP,
                       CRect(25, 72, 400, 200), this, IDC_DLG_COMBO_PRODUCT);
  comboProduct_.SetFont(&fontNormal_);

  std::vector<std::vector<CString>> productRows;
  CString productError;
  if (pDb_ && pDb_->Rows(L"SELECT product_id,name,color FROM products ORDER BY product_id", productRows, productError)) {
    for (const auto& r : productRows) {
      if (r.size() < 3) continue;
      CString title;
      title.Format(L"%s (%s)", r[1].GetString(), r[2].GetString());
      int pos = comboProduct_.AddString(title);
      if (pos >= 0) comboProduct_.SetItemData(pos, static_cast<DWORD_PTR>(_wtoi(r[0])));
    }
  }

  int sel = 0;
  for (int i = 0; i < comboProduct_.GetCount(); ++i)
    if (static_cast<int>(comboProduct_.GetItemData(i)) == initialProductId_) sel = i;
  if (comboProduct_.GetCount() > 0) comboProduct_.SetCurSel(sel);

  lblInfo_.Create(L"현재고 확인 중...", WS_CHILD | WS_VISIBLE,
                  CRect(25, 108, 400, 128), this);
  lblInfo_.SetFont(&fontNormal_);

  lblQty_.Create(L"발주 수량(개):", WS_CHILD | WS_VISIBLE,
                 CRect(25, 136, 120, 156), this);
  lblQty_.SetFont(&fontNormal_);

  editQty_.CreateEx(WS_EX_CLIENTEDGE, L"EDIT", L"10",
                    WS_CHILD | WS_VISIBLE | ES_NUMBER | ES_AUTOHSCROLL |
                        WS_TABSTOP,
                    CRect(130, 133, 230, 160), this, IDC_DLG_EDIT_QTY);
  editQty_.SetFont(&fontNormal_);

  btnOk_.Create(L"발주 신청",
                WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON | WS_TABSTOP,
                CRect(190, 185, 295, 220), this, IDOK);
  btnOk_.SetFont(&fontNormal_);

  btnCancel_.Create(L"취소", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | WS_TABSTOP,
                    CRect(305, 185, 400, 220), this, IDCANCEL);
  btnCancel_.SetFont(&fontNormal_);

  UpdateStockInfo();
  return 0;
}

void CDlgPlaceOrder::OnSelChangeProduct() { UpdateStockInfo(); }

void CDlgPlaceOrder::UpdateStockInfo() {
  if (!pDb_)
    return;
  int idx = comboProduct_.GetCurSel();
  if (idx < 0)
    return;
  int productId = static_cast<int>(comboProduct_.GetItemData(idx));

  CString sql;
  sql.Format(L"SELECT MAX(stock), MIN(min_stock), MIN(color) FROM products "
             L"WHERE color=(SELECT color FROM products WHERE product_id=%d);",
             productId);
  std::vector<std::vector<CString>> rows;
  CString err;
  if (pDb_->Rows(sql, rows, err) && !rows.empty() && rows[0].size() >= 2) {
    int stock = _wtoi(rows[0][0]);
    int minStock = _wtoi(rows[0][1]);
    CString color = rows[0].size() >= 3 ? rows[0][2] : CString(L"-");
    CString info;
    info.Format(L"📊 공유재고(%s): %d개  /  안전재고: %d개  (%s)", color.GetString(), stock, minStock,
                stock <= minStock ? L"⚠️ 재고 부족" : L"정상");
    lblInfo_.SetWindowText(info);
  }
}

void CDlgPlaceOrder::OnBtnOk() {
  int idx = comboProduct_.GetCurSel();
  if (idx < 0) {
    AfxMessageBox(L"발주할 품목을 선택하세요.", MB_ICONWARNING);
    return;
  }
  int productId = static_cast<int>(comboProduct_.GetItemData(idx));

  CString strQty;
  editQty_.GetWindowText(strQty);
  int qty = _wtoi(strQty);
  if (qty <= 0) {
    AfxMessageBox(L"발주 수량은 1개 이상이어야 합니다.", MB_ICONWARNING);
    editQty_.SetFocus();
    return;
  }

  CString selectedName;
  comboProduct_.GetLBText(idx, selectedName);
  CString prompt;
  prompt.Format(L"품목: %s\n수량: %d개\n\n발주 등록하시겠습니까?",
                selectedName.GetString(), qty);

  if (AfxMessageBox(prompt, MB_YESNO | MB_ICONQUESTION) != IDYES)
    return;

  CString error;
  if (pDb_->CreatePurchaseOrder(productId, qty, error)) {
    AfxMessageBox(L"발주 등록이 완료되었습니다.",
                  MB_ICONINFORMATION);
    EndModal(IDOK);
  } else {
    AfxMessageBox(L"발주 등록 실패: " + error, MB_ICONERROR);
  }
}

void CDlgPlaceOrder::OnBtnCancel() { EndModal(IDCANCEL); }

// ==========================================
// CDlgReceiveStock 구현 (입고 완료)
// ==========================================
BEGIN_MESSAGE_MAP(CDlgReceiveStock, CWnd)
ON_WM_CREATE()
ON_WM_SETFOCUS()
ON_BN_CLICKED(IDOK, &CDlgReceiveStock::OnBtnOk)
ON_COMMAND(IDOK, &CDlgReceiveStock::OnBtnOk)
ON_BN_CLICKED(IDCANCEL, &CDlgReceiveStock::OnBtnCancel)
ON_COMMAND(IDCANCEL, &CDlgReceiveStock::OnBtnCancel)
ON_CBN_SELCHANGE(IDC_DLG_COMBO_PRODUCT, &CDlgReceiveStock::OnSelChangeProduct)
END_MESSAGE_MAP()

INT_PTR CDlgReceiveStock::DoModal(CWnd *pParent, Database *pDb,
                                  int initialProductId) {
  pDb_ = pDb;
  initialProductId_ = initialProductId;
  modalResult_ = IDCANCEL;
  modalRunning_ = true;

  CString cls = AfxRegisterWndClass(CS_HREDRAW | CS_VREDRAW,
                                    LoadCursor(nullptr, IDC_ARROW),
                                    (HBRUSH)(COLOR_BTNFACE + 1));
  int w = 480, h = 395;
  CRect pRc(100, 100, 1000, 750);
  if (pParent && pParent->GetSafeHwnd())
    pParent->GetWindowRect(&pRc);
  int x = pRc.left + (pRc.Width() - w) / 2;
  int y = pRc.top + (pRc.Height() - h) / 2;

  if (!CreateEx(WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, cls,
                L"자재 및 상품 입고 완료 처리",
                WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                CRect(x, y, x + w, y + h), pParent, 0)) {
    return IDCANCEL;
  }

  if (pParent && pParent->GetSafeHwnd())
    pParent->EnableWindow(FALSE);

  ShowWindow(SW_SHOWNORMAL);
  UpdateWindow();
  SetForegroundWindow();
  SetActiveWindow();
  comboProduct_.SetFocus();

  MSG msg;
  while (modalRunning_ && GetMessage(&msg, nullptr, 0, 0)) {
    if (msg.message == WM_KEYDOWN) {
      if (msg.wParam == VK_ESCAPE) {
        EndModal(IDCANCEL);
        break;
      }
      if (msg.wParam == VK_RETURN) {
        OnBtnOk();
        break;
      }
      if (msg.wParam == VK_TAB) {
        bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        CWnd *pCur = GetFocus();
        CWnd *pNext = GetNextDlgTabItem(pCur, shift ? TRUE : FALSE);
        if (pNext)
          pNext->SetFocus();
        continue;
      }
    }
    TranslateMessage(&msg);
    DispatchMessage(&msg);
  }

  if (pParent && pParent->GetSafeHwnd()) {
    pParent->EnableWindow(TRUE);
    pParent->SetActiveWindow();
    pParent->SetForegroundWindow();
    pParent->SetFocus();
  }
  DestroyWindow();
  return modalResult_;
}

void CDlgReceiveStock::OnSetFocus(CWnd *pOldWnd) {
  CWnd::OnSetFocus(pOldWnd);
  if (comboProduct_.GetSafeHwnd())
    comboProduct_.SetFocus();
}

void CDlgReceiveStock::EndModal(INT_PTR result) {
  modalResult_ = result;
  modalRunning_ = false;
}

int CDlgReceiveStock::OnCreate(LPCREATESTRUCT lpCreateStruct) {
  if (CWnd::OnCreate(lpCreateStruct) == -1)
    return -1;

  fontTitle_.CreatePointFont(110, UiFont::Family());
  fontBold_.CreatePointFont(95, UiFont::Family());
  fontNormal_.CreatePointFont(95, UiFont::Family());

  // 1. 상단 타이틀 영역
  lblTitle_.Create(L"자재 및 상품 입고 완료 처리", WS_CHILD | WS_VISIBLE,
                   CRect(28, 18, 452, 48), this);
  lblTitle_.SetFont(&fontTitle_);

  // 2. 품목 선택 영역 (ComboBox)
  lblProduct_.Create(L"입고 대상 품목 선택:", WS_CHILD | WS_VISIBLE,
                     CRect(28, 56, 452, 76), this);
  lblProduct_.SetFont(&fontNormal_);

  comboProduct_.Create(WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL |
                           WS_TABSTOP,
                       CRect(28, 80, 452, 240), this, IDC_DLG_COMBO_PRODUCT);
  comboProduct_.SetFont(&fontNormal_);

  std::vector<std::vector<CString>> productRows;
  CString productError;
  if (pDb_ && pDb_->Rows(L"SELECT product_id,name,color FROM products ORDER BY product_id", productRows, productError)) {
    for (const auto& r : productRows) {
      if (r.size() < 3) continue;
      CString title;
      title.Format(L"%s (%s)", r[1].GetString(), r[2].GetString());
      int pos = comboProduct_.AddString(title);
      if (pos >= 0) comboProduct_.SetItemData(pos, static_cast<DWORD_PTR>(_wtoi(r[0])));
    }
  }


  // 실제 product_id 기반 선택 (상품 번호가 1~4라는 가정 제거)
  int defaultSel = 0;
  for (int i = 0; i < comboProduct_.GetCount(); ++i) {
    int id = static_cast<int>(comboProduct_.GetItemData(i));
    if (id == initialProductId_) { defaultSel = i; break; }
  }
  if (initialProductId_ < 0 && pDb_) {
    for (int i = 0; i < comboProduct_.GetCount(); ++i) {
      int id = static_cast<int>(comboProduct_.GetItemData(i));
      int q = 0; INT64 po = 0; CString err;
      if (pDb_->GetPendingPurchaseOrderInfo(id, q, po, err) && q > 0) {
        defaultSel = i; break;
      }
    }
  }
  if (comboProduct_.GetCount() > 0) comboProduct_.SetCurSel(defaultSel);

  // 개별 발주 선택: 같은 품목의 여러 발주를 한 번에 입고하지 않음
  comboPurchaseOrder_.Create(WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL | WS_TABSTOP,
                             CRect(142, 248, 438, 336), this, IDC_DLG_COMBO_PO);
  comboPurchaseOrder_.SetFont(&fontNormal_);

  // 3. 상태 표시 영역 (Static Text 그룹)
  grpStatusBox_.Create(L" 재고 및 발주 대기 상태 ",
                       WS_CHILD | WS_VISIBLE | BS_GROUPBOX,
                       CRect(28, 122, 452, 236), this);
  grpStatusBox_.SetFont(&fontNormal_);

  lblCurrentStock_.Create(L"• 선택 품목의 현재고: 확인 중...",
                          WS_CHILD | WS_VISIBLE, CRect(42, 146, 438, 170),
                          this);
  lblCurrentStock_.SetFont(&fontNormal_);

  lblPendingQty_.Create(L"• 발주(대기) 수량: 확인 중...", WS_CHILD | WS_VISIBLE,
                        CRect(42, 174, 438, 198), this);
  lblPendingQty_.SetFont(&fontNormal_);

  lblNotice_.Create(
      L"상품을 확인한 후 입고 완료를 눌러주세요.",
      WS_CHILD | WS_VISIBLE, CRect(42, 202, 438, 226), this);
  lblNotice_.SetFont(&fontNormal_);

  lblPurchaseOrder_.Create(L"입고 발주번호:", WS_CHILD | WS_VISIBLE,
                  CRect(42, 250, 138, 274), this);
  lblPurchaseOrder_.SetFont(&fontNormal_);

  // 4. 하단 버튼 영역
  btnOk_.Create(L"입고 완료",
                WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON | WS_TABSTOP,
                CRect(244, 305, 350, 341), this, IDOK);
  btnOk_.SetFont(&fontNormal_);

  btnCancel_.Create(L"취소", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | WS_TABSTOP,
                    CRect(360, 305, 452, 341), this, IDCANCEL);
  btnCancel_.SetFont(&fontNormal_);

  UpdateStockAndPendingInfo();
  return 0;
}

void CDlgReceiveStock::OnSelChangeProduct() { UpdateStockAndPendingInfo(); }

void CDlgReceiveStock::UpdateStockAndPendingInfo() {
  if (!pDb_)
    return;
  int idx = comboProduct_.GetCurSel();
  if (idx < 0)
    return;
  int productId = static_cast<int>(comboProduct_.GetItemData(idx));

  // 1. 현재고 조회
  int stock = 0;
  int minStock = 0;
  CString sql;
  sql.Format(L"SELECT MAX(stock), MIN(min_stock), MIN(color) FROM products "
             L"WHERE color=(SELECT color FROM products WHERE product_id=%d);",
             productId);
  std::vector<std::vector<CString>> rows;
  CString err;
  CString color = L"-";
  if (pDb_->Rows(sql, rows, err) && !rows.empty() && rows[0].size() >= 2) {
    stock = _wtoi(rows[0][0]);
    minStock = _wtoi(rows[0][1]);
    if (rows[0].size() >= 3) color = rows[0][2];
  }

  // 2. 발주(대기) 수량 조회
  int pendingQty = 0;
  INT64 firstPoId = 0;
  pDb_->GetPendingPurchaseOrderInfo(productId, pendingQty, firstPoId, err);

  // 발주번호별 선택: 각 ORDERED 발주건을 개별 처리
  comboPurchaseOrder_.ResetContent();
  std::vector<std::vector<CString>> poRows;
  if (pDb_->GetPendingOrders(productId, poRows, err)) {
    for (const auto& r : poRows) {
      if (r.size() < 3) continue;
      CString label;
      label.Format(L"발주 #%s / %s개 / %s", r[0].GetString(), r[1].GetString(), r[2].GetString());
      int pos = comboPurchaseOrder_.AddString(label);
      if (pos >= 0) comboPurchaseOrder_.SetItemData(pos, static_cast<DWORD_PTR>(_wtoi64(r[0])));
    }
  }
  if (comboPurchaseOrder_.GetCount() > 0) comboPurchaseOrder_.SetCurSel(0);

  // 3. UI 갱신 (지정된 형식으로 표시)
  CString strStock;
  strStock.Format(L"• 선택 색상 공유재고(%s):    %d개  (안전재고: %d개)", color.GetString(), stock,
                  minStock);
  lblCurrentStock_.SetWindowText(strStock);

  CString strPending;
  if (pendingQty > 0) {
    strPending.Format(
        L"• 입고 대기 수량:       %d개",
        pendingQty);
    lblNotice_.SetWindowText(
        L"상품을 확인한 후 입고 완료를 눌러주세요.");
  } else {
    strPending = L"• 입고 대기 수량:       0개";
    lblNotice_.SetWindowText(
        L"입고 대기 중인 발주가 없습니다. 먼저 발주를 등록해주세요.");
  }
  lblPendingQty_.SetWindowText(strPending);
}

void CDlgReceiveStock::OnBtnOk() {
  int idx = comboProduct_.GetCurSel();
  int poIndex = comboPurchaseOrder_.GetCurSel();
  if (idx < 0 || poIndex < 0) {
    AfxMessageBox(L"입고할 상품과 발주번호를 선택하세요.", MB_ICONWARNING);
    return;
  }
  const INT64 poId = static_cast<INT64>(comboPurchaseOrder_.GetItemData(poIndex));
  CString productName, poName;
  comboProduct_.GetLBText(idx, productName);
  comboPurchaseOrder_.GetLBText(poIndex, poName);
  CString prompt;
  prompt.Format(L"품목: %s\n발주: %s\n\n입고 완료 처리하시겠습니까?",
                productName.GetString(), poName.GetString());
  if (AfxMessageBox(prompt, MB_YESNO | MB_ICONQUESTION) != IDYES) return;
  CString error;
  if (pDb_->ProcessReceiving(poId, error)) {
    AfxMessageBox(L"입고 처리가 완료되었습니다.", MB_ICONINFORMATION);
    EndModal(IDOK);
  } else {
    AfxMessageBox(L"입고 처리 실패: " + error, MB_ICONERROR);
    UpdateStockAndPendingInfo();
  }
}

void CDlgReceiveStock::OnBtnCancel() { EndModal(IDCANCEL); }

// =========================================================
// Color-shared restock: native MFC CDialog modal processing.
// The previous custom CWnd/GetMessage loop could freeze all UI input.
// =========================================================
namespace {
constexpr UINT IDC_RESTOCK_COLOR = 2401;
constexpr UINT IDC_RESTOCK_QTY = 2402;

// A dialog template with zero child controls; controls are created in OnInitDialog.
// All three zero WORDs (menu / class / title) must follow DLGTEMPLATE.
struct RestockDialogTemplate {
    DLGTEMPLATE dialog;
    WORD menu;
    WORD windowClass;
    WORD title;
};
}
BEGIN_MESSAGE_MAP(CDlgColorRestock, CDialog)
ON_WM_PAINT()
ON_WM_CTLCOLOR()
ON_WM_DRAWITEM()
END_MESSAGE_MAP()

INT_PTR CDlgColorRestock::DoModal(CWnd* parent, Database* database) {
    database_ = database;
    RestockDialogTemplate tpl = {};
    tpl.dialog.style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME;
    tpl.dialog.dwExtendedStyle = 0;
    tpl.dialog.cdit = 0;
    tpl.dialog.x = 0;
    tpl.dialog.y = 0;
    tpl.dialog.cx = 335;
    tpl.dialog.cy = 246;
    // The template remains alive throughout CDialog::DoModal().
    if (!InitModalIndirect(&tpl.dialog, parent)) {
        AfxMessageBox(L"재입고 창을 초기화하지 못했습니다.", MB_ICONERROR);
        return IDCANCEL;
    }
    return CDialog::DoModal();
}

BOOL CDlgColorRestock::OnInitDialog() {
    CDialog::OnInitDialog();
    SetWindowText(L"MobleKurly | 재입고 등록");

    CRect client;
    GetClientRect(&client);
    const int left = 26;
    const int right = client.Width() - 26;
    const int width = right - left;
    const int bottom = client.Height();

    // Blue/white palette shared with the login screen.
    whiteBrush_.CreateSolidBrush(RGB(255, 255, 255));
    paleBrush_.CreateSolidBrush(RGB(239, 246, 251));
    font_.CreatePointFont(100, UiFont::Family());
    titleFont_.CreatePointFont(155, UiFont::Family(), nullptr);
    hintFont_.CreatePointFont(90, UiFont::Family());

    titleLabel_.Create(L"재입고 등록", WS_CHILD | WS_VISIBLE,
                       CRect(left, 15, right, 47), this);
    titleLabel_.SetFont(&titleFont_);
    subtitleLabel_.Create(L"색상별 공유 재고를 등록합니다.", WS_CHILD | WS_VISIBLE,
                          CRect(left, 49, right, 71), this);
    subtitleLabel_.SetFont(&hintFont_);

    colorLabel_.Create(L"재입고 색상", WS_CHILD | WS_VISIBLE,
                       CRect(left, 90, right, 113), this);
    colorLabel_.SetFont(&font_);
    colors_.Create(WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL | WS_TABSTOP,
                   CRect(left, 119, right, 260), this, IDC_RESTOCK_COLOR);
    colors_.SetFont(&font_);
    const wchar_t* codes[] = {L"RED", L"BLUE", L"YELLOW", L"GREEN"};
    for (const auto* code : codes) colors_.AddString(code);
    colors_.SetCurSel(0);

    qtyLabel_.Create(L"추가 수량 (개)", WS_CHILD | WS_VISIBLE,
                     CRect(left, 169, right, 192), this);
    qtyLabel_.SetFont(&font_);
    qty_.CreateEx(WS_EX_CLIENTEDGE, L"EDIT", L"10",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_NUMBER | ES_AUTOHSCROLL,
        CRect(left, 199, right, 232), this, IDC_RESTOCK_QTY);
    qty_.SetFont(&font_);
    hintLabel_.Create(L"재입고할 상품의 색상과 수량을 확인해주세요.",
        WS_CHILD | WS_VISIBLE, CRect(left, 246, right, 276), this);
    hintLabel_.SetFont(&hintFont_);

    const int buttonY = bottom - 58;
    const int buttonGap = 10;
    const int cancelWidth = 105;
    const int okWidth = 150;
    const int okLeft = right - cancelWidth - buttonGap - okWidth;
    ok_.Create(L"재입고 등록", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
               CRect(okLeft, buttonY, okLeft + okWidth, buttonY + 38), this, IDOK);
    ok_.SetFont(&font_);
    cancel_.Create(L"취소", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
                   CRect(right - cancelWidth, buttonY, right, buttonY + 38), this, IDCANCEL);
    cancel_.SetFont(&font_);

    qty_.SetFocus();
    qty_.SetSel(0, -1);
    return FALSE;
}

void CDlgColorRestock::OnPaint() {
    CPaintDC dc(this);
    CRect rect;
    GetClientRect(&rect);
    dc.FillSolidRect(rect, RGB(255, 255, 255));
    // Login-style blue header and neutral footer.
    dc.FillSolidRect(CRect(0, 0, rect.Width(), 79), RGB(239, 246, 251));
    dc.FillSolidRect(CRect(0, rect.Height() - 77, rect.Width(), rect.Height()),
                     RGB(246, 248, 250));
    CPen separator(PS_SOLID, 1, RGB(225, 232, 239));
    CPen* previous = dc.SelectObject(&separator);
    dc.MoveTo(0, 79);
    dc.LineTo(rect.Width(), 79);
    dc.MoveTo(0, rect.Height() - 77);
    dc.LineTo(rect.Width(), rect.Height() - 77);
    dc.SelectObject(previous);
}

HBRUSH CDlgColorRestock::OnCtlColor(CDC* dc, CWnd* wnd, UINT type) {
    HBRUSH base = CDialog::OnCtlColor(dc, wnd, type);
    if (type == CTLCOLOR_STATIC) {
        dc->SetBkMode(TRANSPARENT);
        const HWND hwnd = wnd ? wnd->GetSafeHwnd() : nullptr;
        if (hwnd == titleLabel_.GetSafeHwnd()) {
            dc->SetTextColor(RGB(32, 120, 180));
            return static_cast<HBRUSH>(paleBrush_.GetSafeHandle());
        }
        if (hwnd == subtitleLabel_.GetSafeHwnd()) {
            dc->SetTextColor(RGB(107, 122, 138));
            return static_cast<HBRUSH>(paleBrush_.GetSafeHandle());
        }
        if (hwnd == hintLabel_.GetSafeHwnd()) {
            dc->SetTextColor(RGB(107, 122, 138));
        } else {
            dc->SetTextColor(RGB(37, 51, 67));
        }
        return static_cast<HBRUSH>(whiteBrush_.GetSafeHandle());
    }
    if (type == CTLCOLOR_EDIT || type == CTLCOLOR_LISTBOX) {
        dc->SetBkColor(RGB(255, 255, 255));
        return static_cast<HBRUSH>(whiteBrush_.GetSafeHandle());
    }
    return base;
}

void CDlgColorRestock::OnDrawItem(int controlId, LPDRAWITEMSTRUCT info) {
    if (controlId != IDOK && controlId != IDCANCEL) {
        CDialog::OnDrawItem(controlId, info);
        return;
    }
    CDC dc;
    dc.Attach(info->hDC);
    CRect r(info->rcItem);
    const bool primary = (controlId == IDOK);
    const bool pressed = (info->itemState & ODS_SELECTED) != 0;
    const COLORREF fill = primary ? (pressed ? RGB(19, 55, 91) : RGB(32, 120, 180))
                                  : (pressed ? RGB(225, 237, 247) : RGB(255, 255, 255));
    const COLORREF border = primary ? RGB(32, 120, 180) : RGB(200, 210, 222);
    CBrush brush(fill);
    CPen pen(PS_SOLID, 1, border);
    CBrush* oldBrush = dc.SelectObject(&brush);
    CPen* oldPen = dc.SelectObject(&pen);
    dc.RoundRect(r, CPoint(12, 12));
    dc.SelectObject(oldPen);
    dc.SelectObject(oldBrush);
    CString label = primary ? L"재입고 등록" : L"취소";
    dc.SetBkMode(TRANSPARENT);
    dc.SetTextColor(primary ? RGB(255, 255, 255) : RGB(37, 51, 67));
    CFont* oldFont = dc.SelectObject(&font_);
    dc.DrawText(label, r, DT_SINGLELINE | DT_CENTER | DT_VCENTER);
    dc.SelectObject(oldFont);
    if (info->itemState & ODS_FOCUS) {
        CRect focus(r);
        focus.DeflateRect(4, 4);
        dc.DrawFocusRect(focus);
    }
    dc.Detach();
}

void CDlgColorRestock::OnOK() {
    const int index = colors_.GetCurSel();
    if (index < 0) {
        AfxMessageBox(L"재입고할 색상을 선택하세요.", MB_ICONWARNING);
        return;
    }
    CString color, text;
    colors_.GetLBText(index, color);
    qty_.GetWindowText(text);
    text.Trim();
    if (text.IsEmpty()) {
        AfxMessageBox(L"추가할 수량을 입력하세요.", MB_ICONWARNING);
        return;
    }
    for (int i = 0; i < text.GetLength(); ++i) {
        if (text[i] < L'0' || text[i] > L'9') {
            AfxMessageBox(L"수량에는 숫자만 입력하세요.", MB_ICONWARNING);
            return;
        }
    }
    const INT64 count = _wtoi64(text);
    if (count <= 0 || count > 1000000) {
        AfxMessageBox(L"수량은 1~1,000,000개 사이로 입력하세요.", MB_ICONWARNING);
        return;
    }
    if (!database_) {
        AfxMessageBox(L"서버에 연결되지 않았습니다. 연결 상태를 확인해주세요.", MB_ICONERROR);
        return;
    }
    CString error;
    if (!database_->RestockColor(color, static_cast<int>(count), error)) {
        AfxMessageBox(L"재입고 실패: " + error, MB_ICONWARNING);
        return;
    }
    CString message;
    message.Format(L"%s 상품 %lld개 재입고가 완료되었습니다.",
                   color.GetString(), static_cast<long long>(count));
    AfxMessageBox(message, MB_ICONINFORMATION);
    CDialog::OnOK();
}

void CDlgColorRestock::OnCancel() {
    CDialog::OnCancel();
}
