#pragma once
#include "DashboardData.h"
#include <sql.h>
#include <sqlext.h>
#include <vector>

class Database {
public:
  Database() = default;
  ~Database();
  bool Connect(const CString &iniPath, CString &error);
  void Disconnect();
  bool Load(DashboardData &data, CString &error);
  bool IsConnected() const { return dbc_ != SQL_NULL_HDBC; }

  // 추가 기능: SQL 직접 실행 및 발주/입고 처리
  bool Execute(const wchar_t* sql, CString& error);
  bool ExecuteAffected(const wchar_t* sql, SQLLEN& affected, CString& error);
  bool Rows(const wchar_t *sql, std::vector<std::vector<CString>> &out, CString &error);
  bool CreatePurchaseOrder(int productId, int quantity, CString& error);
  bool GetPendingPurchaseOrderInfo(int productId, int& outQty, INT64& outFirstPoId, CString& error);
  bool GetPendingOrders(int productId, std::vector<std::vector<CString>>& result, CString& error);
  bool ProcessReceiving(INT64 poId, CString& error);
  // TEST ONLY: simulate a physically completed outbound shipment in MySQL.
  bool SimulateSuccessfulDispatch(INT64 orderId, int& shipped, CString& error);
  bool RestockColor(const CString& color, int quantity, CString& error);
  bool ClearErrorBin(int& clearedCount, CString& error);
  bool LoadErrorHistory(std::vector<std::vector<CString>>& rows, CString& error);

private:
  SQLHENV env_ = SQL_NULL_HENV;
  SQLHDBC dbc_ = SQL_NULL_HDBC;
  static CString Diagnostic(SQLSMALLINT handleType, SQLHANDLE handle);
};
