#pragma once
#include <afxwin.h>
#include <vector>
#include <memory>

namespace Gdiplus { class Bitmap; }

// Local classroom demo authentication. Do not use these shared secrets in production.
enum class UserRole { Worker, Admin };

class HoverButton : public CButton {
public:
  bool IsHovered() const { return hovered_; }
protected:
  afx_msg void OnMouseMove(UINT flags, CPoint pt);
  afx_msg void OnMouseLeave();
  DECLARE_MESSAGE_MAP()
private:
  bool hovered_ = false;
};

class LoginDialog final : public CDialog {
public:
  explicit LoginDialog(CWnd* parent = nullptr);
  ~LoginDialog() override;
  INT_PTR ShowLogin();
  UserRole Role() const { return role_; }
  CString UserId() const { return userId_; }
  CString DisplayName() const { return displayName_; }

protected:
  BOOL OnInitDialog() override;
  void OnOK() override;
  void OnCancel() override;
  afx_msg void OnDrawItem(int controlId, LPDRAWITEMSTRUCT item);
  afx_msg HBRUSH OnCtlColor(CDC* dc, CWnd* window, UINT type);
  afx_msg void OnSize(UINT type, int cx, int cy);
  afx_msg void OnPaint();
  afx_msg void OnLButtonDown(UINT flags, CPoint point);
  afx_msg LRESULT OnDpiChanged(WPARAM, LPARAM);
  afx_msg void OnEditFocusChanged();
  DECLARE_MESSAGE_MAP()

private:
  void Layout();
  void FitToMonitor(const RECT* suggested = nullptr);
  void LoadBrandMark();
  std::vector<BYTE> dialogTemplate_;
  CFont font_, titleFont_, boldFont_, smallFont_, leftTitleFont_, leftSubFont_;
  CBrush background_;
  HICON icon_ = nullptr;
  std::unique_ptr<Gdiplus::Bitmap> iconBitmap_;
  double scale_ = 1.0;
  CStatic title_, description_, idLabel_, passwordLabel_, copyright_;
  CEdit idEdit_, passwordEdit_;
  HoverButton submit_, cancel_;
  UserRole role_ = UserRole::Worker;
  CString userId_, displayName_;
};
