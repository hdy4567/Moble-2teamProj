#pragma once
#include <afxwin.h>
#include <afxcmn.h>
#include "Database.h"

class ErrorHistoryDialog final : public CDialog {
public:
  INT_PTR Show(CWnd* parent, Database* database);
protected:
  BOOL OnInitDialog() override;
  afx_msg void OnRefresh();
  afx_msg void OnPaint();
  afx_msg HBRUSH OnCtlColor(CDC* dc,CWnd* wnd,UINT type);
  DECLARE_MESSAGE_MAP()
private:
  Database* database_ = nullptr;
  CFont font_, titleFont_;
  CBrush background_, header_;
  CStatic title_, note_, status_;
  CListCtrl list_;
  CButton refresh_, close_;
};
