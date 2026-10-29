#pragma once
#include "DashboardData.h"
#include "LoginDialog.h"
#include "Database.h"
#include "PiTcpClient.h"
#include "ConveyorProtocol.h"
#include "CctvReceiver.h"

struct ConveyorMailbox;
#include <afxwin.h>
#include <gdiplus.h>
#include <atomic>
#include <memory>
#include <thread>

class DashboardFrame : public CFrameWnd {
public:
  DashboardFrame(const CString& userId, const CString& displayName, UserRole role);
  ~DashboardFrame() override;

protected:
  afx_msg int OnCreate(LPCREATESTRUCT createStruct);
  afx_msg void OnPaint();
  afx_msg BOOL OnEraseBkgnd(CDC *dc);
  afx_msg void OnSize(UINT type, int cx, int cy);
  afx_msg void OnTimer(UINT_PTR id);
  afx_msg void OnLButtonDown(UINT flags, CPoint point);
  afx_msg void OnDestroy();
  afx_msg LRESULT OnPiResponse(WPARAM, LPARAM);
  afx_msg LRESULT OnCameraFrame(WPARAM, LPARAM);
  afx_msg LRESULT OnCctvUpdate(WPARAM, LPARAM);
  afx_msg LRESULT OnConveyorResponse(WPARAM, LPARAM); // [ESTOP]
  DECLARE_MESSAGE_MAP()
private:
  CString userId_, displayName_;
  UserRole role_ = UserRole::Worker;
  int activeTab_ = 1;
  void OnLogout();
  void ClearErrorBin();
  void ShowErrorHistory();
  void DrawAdminTab(Gdiplus::Graphics &g);
  void ShowEmbeddedSettlement();
  void PositionEmbeddedSettlement();
  CWnd* settlementPane_ = nullptr;
  void StartAdminCctv();
  void PauseAdminCctv();
  CctvReceiver cctvReceiver_;
  CctvSnapshot cctvSnapshot_;
  std::unique_ptr<Gdiplus::Bitmap> cctvFrame_;
  ULONGLONG cctvFrameAt_ = 0;
  CString cctvDecodeError_;
  ULONG_PTR gdipToken_ = 0;
  Database db_;
  DashboardData data_;
  CString iniPath_;
  bool firstRefresh_ = true;
  bool piBusy_ = false;
  bool piEnabled_ = false;
  CString piHost_ = L"127.0.0.1";
  int piPort_ = 5055;
  unsigned long piRequestNumber_ = 0;
  // [ESTOP] Independent of order piBusy_: emergency commands never wait for DB/order ACK.
  ConveyorSnapshot conveyor_;
  bool conveyorKnown_ = false;
  bool conveyorPollPending_ = false;
  bool conveyorStopPending_ = false;
  bool conveyorStartPending_ = false;
  unsigned long conveyorGeneration_ = 0;
  ULONGLONG conveyorUpdatedAt_ = 0;
  CString conveyorMessage_ = L"상태 확인 중";
  std::shared_ptr<ConveyorMailbox> conveyorMailbox_;
  void SendConveyorCommand(int kind); // 0=status, 1=stop, 2=start
  void CloseConveyorMailbox();
  std::unique_ptr<Gdiplus::Bitmap> cameraFrame_;
  std::atomic_bool cameraStop_{false};
  std::thread cameraThread_;
  bool cameraEnabled_ = false;
  CString cameraHost_;
  int cameraPort_ = 5000;
  CString cameraPath_ = L"/video_feed";
  void StartCamera();
  void StopCamera();
  void LoadPiConfig();
  void SendPiCommand(const CString &command, const CString &orderId = L"");
  void RefreshData();
  void Draw(Gdiplus::Graphics &g, float sx, float sy);
  void DrawOrders(Gdiplus::Graphics &g);
  void DrawOutbound(Gdiplus::Graphics &g);
  void DrawProcessing(Gdiplus::Graphics &g);
  void DrawCamera(Gdiplus::Graphics &g);
  void DrawStock(Gdiplus::Graphics &g);
  void DrawErrorBin(Gdiplus::Graphics &g);
  void DrawGraph(Gdiplus::Graphics &g);
  void DrawSensorLog(Gdiplus::Graphics &g);
  void DrawFanLog(Gdiplus::Graphics &g);
  void DrawReports(Gdiplus::Graphics &g);
  void Placeholder(LPCWSTR functionName, bool safety = false);

  void OnClickPlaceOrder();   // 발주 대화상자 호출
  void OnClickReceiveStock(); // 입고 대화상자 호출
};
