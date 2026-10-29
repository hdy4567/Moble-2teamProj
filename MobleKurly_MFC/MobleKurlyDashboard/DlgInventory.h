#pragma once
#include <afxwin.h>
#include "Database.h"

// 1. 발주 등록 전용 모달 다이얼로그 (구매 발주 신청)
class CDlgPlaceOrder : public CWnd {
public:
    CDlgPlaceOrder() = default;
    INT_PTR DoModal(CWnd* pParent, Database* pDb, int initialProductId = -1);

protected:
    afx_msg int OnCreate(LPCREATESTRUCT lpCreateStruct);
    afx_msg void OnSetFocus(CWnd* pOldWnd);
    afx_msg void OnLButtonUp(UINT nFlags, CPoint point);
    afx_msg void OnBtnOk();
    afx_msg void OnBtnCancel();
    afx_msg void OnSelChangeProduct();
    DECLARE_MESSAGE_MAP()

private:
    void EndModal(INT_PTR result);
    void UpdateStockInfo();

    Database* pDb_ = nullptr;
    int initialProductId_ = -1;
    bool modalRunning_ = false;
    INT_PTR modalResult_ = IDCANCEL;

    CFont fontTitle_;
    CFont fontNormal_;

    CStatic lblTitle_;
    CStatic lblProduct_;
    CComboBox comboProduct_;
    CStatic lblInfo_;
    CStatic lblQty_;
    CEdit editQty_;
    CButton btnOk_;
    CButton btnCancel_;
};

// 2. 입고 등록 전용 모달 다이얼로그 (자재 및 상품 입고 완료 처리)
class CDlgReceiveStock : public CWnd {
public:
    CDlgReceiveStock() = default;
    INT_PTR DoModal(CWnd* pParent, Database* pDb, int initialProductId = -1);

protected:
    afx_msg int OnCreate(LPCREATESTRUCT lpCreateStruct);
    afx_msg void OnSetFocus(CWnd* pOldWnd);
    afx_msg void OnLButtonUp(UINT nFlags, CPoint point);
    afx_msg void OnBtnOk();
    afx_msg void OnBtnCancel();
    afx_msg void OnSelChangeProduct();
    DECLARE_MESSAGE_MAP()

private:
    void EndModal(INT_PTR result);
    void UpdateStockAndPendingInfo();

    Database* pDb_ = nullptr;
    int initialProductId_ = -1;
    bool modalRunning_ = false;
    INT_PTR modalResult_ = IDCANCEL;

    CFont fontTitle_;
    CFont fontBold_;
    CFont fontNormal_;

    CStatic lblTitle_;
    CStatic lblProduct_;
    CComboBox comboProduct_;
    CComboBox comboPurchaseOrder_; // 입고할 개별 발주번호
    CStatic lblPurchaseOrder_;

    CStatic grpStatusBox_;
    CStatic lblCurrentStock_;
    CStatic lblPendingQty_;
    CStatic lblNotice_;

    CButton btnOk_;
    CButton btnCancel_;
};

// Color-based immediate restock (no purchase order required).
// Native MFC modal dialog, using an in-memory dialog template (no .rc file).
class CDlgColorRestock : public CDialog {
public:
    CDlgColorRestock() = default;
    INT_PTR DoModal(CWnd* parent, Database* database);
protected:
    virtual BOOL OnInitDialog() override;
    virtual void OnOK() override;
    virtual void OnCancel() override;
    afx_msg void OnPaint();
    afx_msg HBRUSH OnCtlColor(CDC* dc, CWnd* wnd, UINT type);
    afx_msg void OnDrawItem(int controlId, LPDRAWITEMSTRUCT drawItem);
    DECLARE_MESSAGE_MAP()
private:
    Database* database_ = nullptr;
    CFont font_;
    CFont titleFont_;
    CFont hintFont_;
    CBrush whiteBrush_;
    CBrush paleBrush_;
    CStatic titleLabel_;
    CStatic subtitleLabel_;
    CStatic colorLabel_;
    CStatic qtyLabel_;
    CStatic hintLabel_;
    CComboBox colors_;
    CEdit qty_;
    CButton ok_;
    CButton cancel_;
};
