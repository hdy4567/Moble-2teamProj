#include "Database.h"
#include <cstdlib>
#include <windows.h>

Database::~Database() { Disconnect(); }

void Database::Disconnect() {
  if (dbc_ != SQL_NULL_HDBC) {
    SQLDisconnect(dbc_);
    SQLFreeHandle(SQL_HANDLE_DBC, dbc_);
    dbc_ = SQL_NULL_HDBC;
  }
  if (env_ != SQL_NULL_HENV) {
    SQLFreeHandle(SQL_HANDLE_ENV, env_);
    env_ = SQL_NULL_HENV;
  }
}

CString Database::Diagnostic(SQLSMALLINT type, SQLHANDLE handle) {
  SQLWCHAR state[6] = {}, msg[512] = {};
  SQLINTEGER native = 0;
  SQLSMALLINT len = 0;
  if (SQL_SUCCEEDED(
          SQLGetDiagRecW(type, handle, 1, state, &native, msg, 511, &len)))
    return CString(reinterpret_cast<const wchar_t *>(msg));
  return L"ODBC 오류 (상세 메시지 없음)";
}

bool Database::Connect(const CString &iniPath, CString &error) {
  Disconnect();
  wchar_t driver[128] = {}, host[128] = {}, port[32] = {}, db[128] = {},
          user[128] = {}, pwd[256] = {};
  GetPrivateProfileStringW(L"mysql", L"driver",
                           L"MySQL ODBC 26.7 Unicode Driver", driver, 128,
                           iniPath);
  GetPrivateProfileStringW(L"mysql", L"host", L"192.168.0.90", host, 128,
                           iniPath);
  GetPrivateProfileStringW(L"mysql", L"port", L"3306", port, 32, iniPath);
  GetPrivateProfileStringW(L"mysql", L"database", L"moblekurly", db, 128,
                           iniPath);
  GetPrivateProfileStringW(L"mysql", L"user", L"moblekurly", user, 128,
                           iniPath);
  GetPrivateProfileStringW(L"mysql", L"password", L"", pwd, 256, iniPath);
  if (!*pwd) {
    error = L"서버 연결 정보를 확인해주세요.";
    return false;
  }

  if (!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &env_))) {
    error = L"서버 연결을 준비하지 못했습니다.";
    return false;
  }
  if (!SQL_SUCCEEDED(SQLSetEnvAttr(env_, SQL_ATTR_ODBC_VERSION,
                                   reinterpret_cast<SQLPOINTER>(SQL_OV_ODBC3),
                                   0))) {
    error = L"서버 연결을 준비하지 못했습니다.";
    Disconnect();
    return false;
  }
  if (!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_DBC, env_, &dbc_))) {
    error = L"서버에 연결하지 못했습니다.";
    Disconnect();
    return false;
  }
  SQLSetConnectAttr(dbc_, SQL_ATTR_LOGIN_TIMEOUT,
                    reinterpret_cast<SQLPOINTER>(5), 0);
  CString conn;
  conn.Format(L"DRIVER={%s};SERVER=%s;PORT=%s;DATABASE=%s;UID=%s;PWD=%s;"
              L"CHARSET=utf8mb4;OPTION=3;",
              driver, host, port, db, user, pwd);
  wchar_t completed[1024] = {};
  SQLSMALLINT outputLen = 0;
  SQLRETURN ret = SQLDriverConnectW(
      dbc_, nullptr, reinterpret_cast<SQLWCHAR *>(conn.GetBuffer()), SQL_NTS,
      reinterpret_cast<SQLWCHAR *>(completed), 1024, &outputLen,
      SQL_DRIVER_NOPROMPT);
  conn.ReleaseBuffer();
  SecureZeroMemory(pwd, sizeof(pwd));
  if (!SQL_SUCCEEDED(ret)) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    Disconnect();
    return false;
  }
  error.Empty();
  return true;
}

bool Database::Rows(const wchar_t *sql, std::vector<std::vector<CString>> &out,
                    CString &error) {
  SQLHSTMT stmt = SQL_NULL_HSTMT;
  if (!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_STMT, dbc_, &stmt))) {
    error = L"요청을 준비하지 못했습니다. 다시 시도해주세요.";
    return false;
  }
  SQLSetStmtAttr(stmt, SQL_ATTR_QUERY_TIMEOUT, reinterpret_cast<SQLPOINTER>(5),
                 0);
  SQLRETURN r = SQLExecDirectW(
      stmt, reinterpret_cast<SQLWCHAR *>(const_cast<wchar_t *>(sql)), SQL_NTS);
  if (!SQL_SUCCEEDED(r)) {
    error = Diagnostic(SQL_HANDLE_STMT, stmt);
    SQLFreeHandle(SQL_HANDLE_STMT, stmt);
    return false;
  }
  SQLSMALLINT cols = 0;
  SQLNumResultCols(stmt, &cols);
  while ((r = SQLFetch(stmt)) == SQL_SUCCESS || r == SQL_SUCCESS_WITH_INFO) {
    std::vector<CString> row;
    for (SQLUSMALLINT i = 1; i <= static_cast<SQLUSMALLINT>(cols); ++i) {
      SQLWCHAR value[2048] = {};
      SQLLEN indicator = 0;
      SQLRETURN c =
          SQLGetData(stmt, i, SQL_C_WCHAR, value, sizeof(value), &indicator);
      if (!SQL_SUCCEEDED(c) || indicator == SQL_NULL_DATA)
        row.push_back(L"");
      else
        row.push_back(CString(reinterpret_cast<const wchar_t *>(value)));
    }
    out.push_back(std::move(row));
  }
  bool ok = (r == SQL_NO_DATA);
  if (!ok)
    error = Diagnostic(SQL_HANDLE_STMT, stmt);
  SQLFreeHandle(SQL_HANDLE_STMT, stmt);
  return ok;
}

bool Database::Load(DashboardData &data, CString &error) {
  if (!IsConnected()) {
    error = L"서버에 연결되지 않았습니다.";
    return false;
  }
  DashboardData d;
  std::vector<std::vector<CString>> rows;
  auto get = [&](const wchar_t *sql) {
    rows.clear();
    return Rows(sql, rows, error);
  };
  if (!get(L"SELECT "
           L"(SELECT COUNT(*) FROM orders WHERE status='PENDING'),"
           L"(SELECT COUNT(*) FROM orders WHERE status='PROCESSING'),"
           L"(SELECT COALESCE(SUM(color_stock),0) FROM (SELECT color, MAX(stock) AS color_stock FROM products GROUP BY color) c),"
           L"(SELECT COUNT(*) FROM (SELECT color FROM products GROUP BY color HAVING MAX(stock) <= MIN(min_stock)) c2)"))
    return false;
  if (!rows.empty() && rows[0].size() >= 4) {
    d.pending = _wtoi(rows[0][0]);
    d.processing = _wtoi(rows[0][1]);
    d.totalStock = _wtoi(rows[0][2]);
    d.lowStock = _wtoi(rows[0][3]);
  }
  if (!get(L"SELECT item_count,warning_threshold FROM error_bin ORDER BY "
           L"bin_id LIMIT 1"))
    return false;
  if (!rows.empty()) {
    d.errorCount = _wtoi(rows[0][0]);
    d.errorThreshold = _wtoi(rows[0][1]);
  }

  // Waiting orders: first placed first. Only PENDING rows show dispatch buttons.
  if (!get(L"SELECT o.order_id, DATE_FORMAT(o.ordered_at,'%m-%d %H:%i'),"
           L"COALESCE(GROUP_CONCAT(CONCAT(p.name,' x',oi.quantity) ORDER BY oi.item_id SEPARATOR ', '),'-'),"
           L"COALESCE(SUM(oi.quantity),0),o.status, "
           L"CASE UPPER(TRIM(o.delivery_region)) "
           L"WHEN 'SEOUL' THEN '서울' "
           L"WHEN 'GYEONGGI' THEN '경기' "
           L"WHEN 'CHUNGCHEONG' THEN '충청' "
           L"ELSE COALESCE(NULLIF(o.delivery_region,''),'미지정') END "
           L"FROM orders o "
           L"LEFT JOIN order_items oi ON o.order_id=oi.order_id "
           L"LEFT JOIN products p ON oi.product_id=p.product_id "
           L"WHERE o.status='PENDING' "
           L"GROUP BY o.order_id,o.ordered_at,o.status,o.delivery_region "
           L"ORDER BY o.ordered_at ASC,o.order_id ASC LIMIT 6"))
    return false;
  for (auto &r : rows)
    if (r.size() >= 6)
      d.orders.push_back({r[0],r[1],r[2],r[3],r[4],r[5]});

  // Existing order states determine which rows appear in the processing panel.
  // This SELECT does not modify the dispatch/retry or database state transitions.
  if (!get(L"SELECT o.order_id,DATE_FORMAT(o.ordered_at,'%m-%d %H:%i'),"
           L"COALESCE(GROUP_CONCAT(CONCAT(p.name,' x',oi.quantity) ORDER BY oi.item_id SEPARATOR ', '),'-'),"
           L"COALESCE(SUM(oi.quantity),0),"
           L"CASE WHEN o.status='ERROR' THEN 'ERROR' "
           L"WHEN EXISTS(SELECT 1 FROM order_items oi2 "
           L"JOIN outbound_jobs j ON j.item_id=oi2.item_id "
           L"WHERE oi2.order_id=o.order_id AND j.status='RUNNING') THEN 'RUNNING' "
           L"ELSE 'WAITING' END, "
           L"CASE UPPER(TRIM(o.delivery_region)) "
           L"WHEN 'SEOUL' THEN '서울' "
           L"WHEN 'GYEONGGI' THEN '경기' "
           L"WHEN 'CHUNGCHEONG' THEN '충청' "
           L"ELSE COALESCE(NULLIF(o.delivery_region,''),'미지정') END "
           L"FROM orders o "
           L"LEFT JOIN order_items oi ON o.order_id=oi.order_id "
           L"LEFT JOIN products p ON oi.product_id=p.product_id "
           L"WHERE o.status IN ('PROCESSING','ERROR') "
           L"GROUP BY o.order_id,o.ordered_at,o.status,o.delivery_region "
           L"ORDER BY o.ordered_at ASC,o.order_id ASC LIMIT 4"))
    return false;
  for (auto &r : rows)
    if (r.size() >= 6)
      d.processingOrders.push_back({r[0],r[1],r[2],r[3],r[4],r[5]});

  // One outbound_log is recorded per unit. Aggregate by job / detected product /
  // result / destination to show the actual shipped quantity, not attempt_no.
  if (!get(L"SELECT DATE_FORMAT(MAX(l.created_at),'%m-%d %H:%i'), "
           L"COALESCE(p.name,'미식별'), CAST(COUNT(*) AS CHAR), l.result, "
           L"CASE l.destination WHEN 'NORMAL' THEN '정상 출고' "
           L"WHEN 'ERROR_BIN' THEN '오류 수거함' ELSE l.destination END "
           L"FROM outbound_logs l LEFT JOIN products p ON "
           L"l.detected_product_id=p.product_id "
           L"GROUP BY l.job_id,l.detected_product_id,p.name,l.result,l.destination "
           L"ORDER BY MAX(l.log_id) DESC LIMIT 5"))
    return false;
  for (auto &r : rows)
    if (r.size() >= 5)
      d.outbound.push_back({r[0], r[1], r[2], r[3], r[4]});

  if (!get(L"SELECT color, MIN(stock), MAX(min_stock), COUNT(*), "
           L"MIN(product_id) FROM products GROUP BY color "
           L"ORDER BY FIELD(color,'RED','BLUE','YELLOW','GREEN')"))
    return false;
  for (auto &r : rows)
    if (r.size() >= 5)
      d.stock.push_back({L"", r[0], r[1], r[3], r[2]});

  if (!get(L"SELECT "
           L"DATE_FORMAT(recorded_at,'%H:%i'),temperature,humidity,fan_on "
           L"FROM sensor_logs ORDER BY recorded_at DESC,sensor_id DESC LIMIT "
           L"30"))
    return false;
  if (!rows.empty() && rows[0].size() >= 4) {
    d.hasSensor = true;
    d.temperature = _wtof(rows[0][1]);
    d.humidity = _wtof(rows[0][2]);
    d.fanOn = (_wtoi(rows[0][3]) != 0);
  }
  for (auto &r : rows)
    if (r.size() >= 3)
      d.sensors.push_back({r[0], r[1], r[2], _wtof(r[1]), _wtof(r[2])});

  if (!get(L"SELECT DATE_FORMAT(started_at,'%m-%d %H:%i'),"
           L"COALESCE(DATE_FORMAT(stopped_at,'%H:%i'),'-'),"
           L"CASE WHEN stopped_at IS NULL THEN '동작 중' ELSE "
           L"CONCAT(COALESCE(duration_seconds, "
           L"TIMESTAMPDIFF(SECOND,started_at,stopped_at)),'초') END "
           L"FROM fan_logs ORDER BY started_at DESC,fan_log_id DESC LIMIT 6"))
    return false;
  for (auto &r : rows)
    if (r.size() >= 3)
      d.fans.push_back({r[0], r[1], r[2]});
  d.connected = true;
  d.error.Empty();
  data = std::move(d);
  error.Empty();
  return true;
}

bool Database::Execute(const wchar_t* sql, CString& error) {
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  SQLHSTMT stmt = SQL_NULL_HSTMT;
  if (!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_STMT, dbc_, &stmt))) {
    error = L"요청을 준비하지 못했습니다. 다시 시도해주세요.";
    return false;
  }
  SQLSetStmtAttr(stmt, SQL_ATTR_QUERY_TIMEOUT, reinterpret_cast<SQLPOINTER>(5), 0);
  SQLRETURN r = SQLExecDirectW(stmt, reinterpret_cast<SQLWCHAR*>(const_cast<wchar_t*>(sql)), SQL_NTS);
  if (!SQL_SUCCEEDED(r)) {
    error = Diagnostic(SQL_HANDLE_STMT, stmt);
    SQLFreeHandle(SQL_HANDLE_STMT, stmt);
    return false;
  }
  SQLFreeHandle(SQL_HANDLE_STMT, stmt);
  return true;
}

// Checks affected rows on the SAME statement handle as UPDATE.
// Do not use SELECT ROW_COUNT() on a separate ODBC statement.
bool Database::ExecuteAffected(const wchar_t* sql, SQLLEN& affected, CString& error) {
  affected = -1;
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  SQLHSTMT stmt = SQL_NULL_HSTMT;
  if (!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_STMT, dbc_, &stmt))) {
    error = L"요청을 준비하지 못했습니다. 다시 시도해주세요.";
    return false;
  }
  SQLSetStmtAttr(stmt, SQL_ATTR_QUERY_TIMEOUT, reinterpret_cast<SQLPOINTER>(5), 0);
  SQLRETURN rc = SQLExecDirectW(
      stmt, reinterpret_cast<SQLWCHAR*>(const_cast<wchar_t*>(sql)), SQL_NTS);
  if (!SQL_SUCCEEDED(rc)) {
    error = Diagnostic(SQL_HANDLE_STMT, stmt);
    SQLFreeHandle(SQL_HANDLE_STMT, stmt);
    return false;
  }
  rc = SQLRowCount(stmt, &affected);
  if (!SQL_SUCCEEDED(rc)) {
    error = Diagnostic(SQL_HANDLE_STMT, stmt);
    SQLFreeHandle(SQL_HANDLE_STMT, stmt);
    return false;
  }
  SQLFreeHandle(SQL_HANDLE_STMT, stmt);
  return true;
}

bool Database::CreatePurchaseOrder(int productId, int quantity, CString& error) {
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  if (quantity <= 0) { error = L"발주 수량은 1개 이상이어야 합니다."; return false; }
  CString sql;
  sql.Format(L"INSERT INTO purchase_orders (product_id, quantity, status, created_at) "
             L"VALUES (%d, %d, 'ORDERED', NOW());", productId, quantity);
  return Execute(sql, error);
}

bool Database::GetPendingPurchaseOrderInfo(int productId, int& outQty, INT64& outFirstPoId, CString& error) {
  outQty = 0;
  outFirstPoId = 0;
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  CString sql;
  sql.Format(L"SELECT COALESCE(SUM(quantity), 0), COALESCE(MIN(po_id), 0) "
             L"FROM purchase_orders WHERE product_id = %d AND status = 'ORDERED';", productId);
  std::vector<std::vector<CString>> rows;
  if (!Rows(sql, rows, error)) return false;
  if (!rows.empty() && rows[0].size() >= 2) {
    outQty = _wtoi(rows[0][0]);
    outFirstPoId = _wtoi64(rows[0][1]);
  }
  return true;
}

bool Database::GetPendingOrders(int productId,
                                std::vector<std::vector<CString>>& result,
                                CString& error) {
  if (!IsConnected() || productId <= 0) {
    error = L"서버 연결 상태와 선택한 상품을 확인해주세요.";
    return false;
  }
  CString sql;
  sql.Format(L"SELECT po_id, quantity, DATE_FORMAT(created_at,'%%m-%%d %%H:%%i') "
             L"FROM purchase_orders WHERE product_id=%d AND status='ORDERED' "
             L"ORDER BY po_id", productId);
  result.clear();
  return Rows(sql, result, error);
}

bool Database::ProcessReceiving(INT64 poId, CString& error) {
  if (!IsConnected() || poId <= 0) {
    error = L"서버 연결 상태와 선택한 발주를 확인해주세요.";
    return false;
  }
  SQLRETURN rc = SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
      reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_OFF), SQL_IS_UINTEGER);
  if (!SQL_SUCCEEDED(rc)) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  bool success = false;
  do {
    CString sql;
    sql.Format(L"SELECT product_id, quantity FROM purchase_orders "
               L"WHERE po_id=%lld AND status='ORDERED' FOR UPDATE", poId);
    std::vector<std::vector<CString>> rows;
    if (!Rows(sql, rows, error)) break;
    if (rows.size() != 1 || rows[0].size() < 2) {
      error = L"발주가 없거나 이미 입고 처리된 건입니다.";
      break;
    }
    int productId = _wtoi(rows[0][0]);
    int quantity = _wtoi(rows[0][1]);
    if (productId <= 0 || quantity <= 0) {
      error = L"잘못된 발주 데이터입니다.";
      break;
    }
    sql.Format(L"UPDATE products p JOIN (SELECT color FROM products WHERE product_id=%d) s "
               L"ON p.color=s.color SET p.stock=p.stock+%d",
               productId, quantity);
    if (!Execute(sql, error)) break;
    // Foreign keys and the transaction guarantee these statements succeed together.
    sql.Format(L"INSERT INTO stock_logs "
               L"(product_id, change_qty, reason, po_id, created_at) "
               L"VALUES (%d,%d,'RESTOCK',%lld,NOW())",
               productId, quantity, poId);
    if (!Execute(sql, error)) break;
    sql.Format(L"UPDATE purchase_orders SET status='RECEIVED', "
               L"received_at=NOW() WHERE po_id=%lld AND status='ORDERED'", poId);
    if (!Execute(sql, error)) break;
    rc = SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_COMMIT);
    if (!SQL_SUCCEEDED(rc)) {
      error = Diagnostic(SQL_HANDLE_DBC, dbc_);
      break;
    }
    success = true;
  } while (false);
  if (!success) SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_ROLLBACK);
  SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
      reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_ON), SQL_IS_UINTEGER);
  return success;
}

// Simulates successful physical release of every remaining unit of a PENDING order.
// This must NOT be used as the real conveyor completion handler.
// All changes are transactional. A second click cannot dispatch the same order again.
// Manually restock one color. The twelve products retain a replicated
// stock value per color; only one stock_log entry is written for the event.
bool Database::RestockColor(const CString& color, int quantity, CString& error) {
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  if (color != L"RED" && color != L"BLUE" &&
      color != L"YELLOW" && color != L"GREEN") {
    error = L"유효하지 않은 색상입니다.";
    return false;
  }
  if (quantity <= 0 || quantity > 1000000) {
    error = L"재입고 수량은 1~1,000,000 사이여야 합니다.";
    return false;
  }
  SQLRETURN rc = SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
      reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_OFF), SQL_IS_UINTEGER);
  if (!SQL_SUCCEEDED(rc)) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  bool success = false;
  do {
    CString sql;
    sql.Format(L"SELECT product_id, stock FROM products WHERE color='%s' "
               L"ORDER BY product_id FOR UPDATE", color.GetString());
    std::vector<std::vector<CString>> rows;
    if (!Rows(sql, rows, error)) break;
    if (rows.empty()) {
      error = L"선택한 색상에 등록된 상품이 없습니다.";
      break;
    }
    const int productId = _wtoi(rows.front()[0]);
    const int oldStock = _wtoi(rows.front()[1]);
    bool consistent = productId > 0 && oldStock >= 0;
    for (const auto& row : rows) {
      if (row.size() < 2 || _wtoi(row[1]) != oldStock) {
        consistent = false;
        break;
      }
    }
    if (!consistent) {
      error = L"같은 색상 상품끼리 재고가 서로 달라 재입고를 중단했습니다.";
      break;
    }
    if (oldStock > 2147483647 - quantity) {
      error = L"재고 수량이 허용 범위를 초과합니다.";
      break;
    }
    sql.Format(L"UPDATE products SET stock=stock+%d "
               L"WHERE color='%s' AND stock=%d",
               quantity, color.GetString(), oldStock);
    SQLLEN affected = -1;
    if (!ExecuteAffected(sql, affected, error)) break;
    if (affected != static_cast<SQLLEN>(rows.size())) {
      error = L"일부 색상 상품의 재고 갱신에 실패했습니다.";
      break;
    }
    sql.Format(L"INSERT INTO stock_logs "
               L"(product_id, change_qty, reason, created_at) "
               L"VALUES (%d,%d,'RESTOCK',NOW())",
               productId, quantity);
    if (!Execute(sql, error)) break;
    rc = SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_COMMIT);
    if (!SQL_SUCCEEDED(rc)) {
      error = Diagnostic(SQL_HANDLE_DBC, dbc_);
      break;
    }
    success = true;
  } while (false);
  if (!success) SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_ROLLBACK);
  rc = SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
      reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_ON), SQL_IS_UINTEGER);
  if (!SQL_SUCCEEDED(rc)) {
    if (success)
      error = L"재입고는 완료되었으나 서버 연결에 문제가 발생했습니다. 프로그램을 다시 실행해주세요.";
    else if (error.IsEmpty())
      error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  return success;
}

bool Database::SimulateSuccessfulDispatch(INT64 orderId, int& shipped, CString& error) {
  shipped = 0;
  if (!IsConnected() || orderId <= 0) {
    error = L"서버 연결 상태와 주문번호를 확인해주세요.";
    return false;
  }
  SQLRETURN rc = SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
      reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_OFF), SQL_IS_UINTEGER);
  if (!SQL_SUCCEEDED(rc)) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  bool success = false;
  do {
    CString sql;
    std::vector<std::vector<CString>> rows;
    sql.Format(L"SELECT status FROM orders WHERE order_id=%lld FOR UPDATE", orderId);
    if (!Rows(sql, rows, error)) break;
    if (rows.size() != 1 || rows[0].empty() || rows[0][0] != L"PENDING") {
      error = L"대기 중인 주문만 출고할 수 있습니다.";
      break;
    }
    rows.clear();
    sql.Format(L"SELECT oi.item_id, oi.product_id, oi.quantity, oi.shipped_qty, p.color "
               L"FROM order_items oi JOIN products p ON oi.product_id=p.product_id "
               L"WHERE oi.order_id=%lld ORDER BY oi.item_id FOR UPDATE", orderId);
    if (!Rows(sql, rows, error)) break;
    if (rows.empty()) {
      error = L"주문에 등록된 상품이 없습니다.";
      break;
    }
    struct Item { INT64 id; int product; CString color; int remaining; };
    std::vector<Item> items;
    int count = 0;
    bool valid = true;
    for (const auto& r : rows) {
      if (r.size() < 5) { valid = false; break; }
      const INT64 itemId = _wtoi64(r[0]);
      const int productId = _wtoi(r[1]);
      const int remaining = _wtoi(r[2]) - _wtoi(r[3]);
      const CString color = r[4];
      if (itemId <= 0 || productId <= 0 || color.IsEmpty() || remaining <= 0 || remaining > 10000 || count > 10000 - remaining) {
        valid = false; break;
      }
      items.push_back({itemId, productId, color, remaining});
      count += remaining;
    }
    if (!valid) {
      error = L"주문 수량이 올바르지 않거나 이미 출고된 상품이 있습니다.";
      break;
    }
    // Work per item in ascending item_id order; stock guards prevent negative values.
    for (const auto& item : items) {
      sql.Format(L"UPDATE products SET stock=stock-%d "
                 L"WHERE color='%s' AND stock>=%d",
                 item.remaining, item.color.GetString(), item.remaining);
      SQLLEN affected = -1;
      if (!ExecuteAffected(sql, affected, error)) { valid = false; break; }
      if (affected <= 0) {
        error.Format(L"색상 %s: 공유 재고가 부족하거나 상품이 없습니다.",
                     item.color.GetString());
        valid = false; break;
      }
      sql.Format(L"INSERT INTO outbound_jobs (item_id,status,retry_count,created_at,started_at) "
                 L"VALUES (%lld,'RUNNING',0,NOW(),NOW())", item.id);
      if (!Execute(sql, error)) { valid = false; break; }
      rows.clear();
      if (!Rows(L"SELECT LAST_INSERT_ID()", rows, error) || rows.empty() || rows[0].empty()) {
        valid = false; break;
      }
      const INT64 jobId = _wtoi64(rows[0][0]);
      // Existing schema requires one outbound_log per unit, with unique (job_id, attempt_no).
      for (int attempt = 1; attempt <= item.remaining; ++attempt) {
        sql.Format(L"INSERT INTO outbound_logs "
                   L"(job_id,attempt_no,expected_product_id,detected_product_id,result,destination,created_at) "
                   L"VALUES (%lld,%d,%d,%d,'SUCCESS','NORMAL',NOW())",
                   jobId, attempt, item.product, item.product);
        if (!Execute(sql, error)) { valid = false; break; }
        rows.clear();
        if (!Rows(L"SELECT LAST_INSERT_ID()", rows, error) || rows.empty() || rows[0].empty()) {
          valid = false; break;
        }
        const INT64 logId = _wtoi64(rows[0][0]);
        sql.Format(L"INSERT INTO stock_logs "
                   L"(product_id,change_qty,reason,outbound_log_id,created_at) "
                   L"VALUES (%d,-1,'NORMAL_OUT',%lld,NOW())", item.product, logId);
        if (!Execute(sql, error)) { valid = false; break; }
      }
      if (!valid) break;
      sql.Format(L"UPDATE order_items SET shipped_qty=shipped_qty+%d "
                 L"WHERE item_id=%lld AND shipped_qty+%d<=quantity",
                 item.remaining, item.id, item.remaining);
      if (!Execute(sql, error)) { valid = false; break; }
      sql.Format(L"UPDATE outbound_jobs SET status='DONE',completed_at=NOW() "
                 L"WHERE job_id=%lld", jobId);
      if (!Execute(sql, error)) { valid = false; break; }
    }
    if (!valid) break;
    sql.Format(L"UPDATE orders SET status='COMPLETED', "
               L"approved_at=COALESCE(approved_at,NOW()),completed_at=NOW() "
               L"WHERE order_id=%lld AND status='PENDING'", orderId);
    SQLLEN orderAffected = -1;
    if (!ExecuteAffected(sql, orderAffected, error)) break;
    if (orderAffected != 1) {
      error = L"주문 상태가 변경되어 출고를 취소했습니다.";
      break;
    }
    rc = SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_COMMIT);
    if (!SQL_SUCCEEDED(rc)) {
      error = Diagnostic(SQL_HANDLE_DBC, dbc_);
      break;
    }
    shipped = count;
    success = true;
  } while (false);
  if (!success) SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_ROLLBACK);
  rc = SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
       reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_ON), SQL_IS_UINTEGER);
  if (!SQL_SUCCEEDED(rc)) {
    if (success) error = L"출고 처리는 저장되었으나 서버 연결에 문제가 발생했습니다. 프로그램을 다시 실행해주세요.";
    else if (error.IsEmpty()) error = Diagnostic(SQL_HANDLE_DBC, dbc_);
  }
  return success;
}
