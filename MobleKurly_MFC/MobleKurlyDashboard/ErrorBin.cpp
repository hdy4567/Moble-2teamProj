#include "Database.h"
#include "ErrorBinSql.h"
#include <climits>
#include <cstdlib>

bool Database::ClearErrorBin(int& clearedCount, CString& error) {
  clearedCount = 0;
  error.Empty();
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  SQLULEN autocommit = SQL_AUTOCOMMIT_ON;
  if (!SQL_SUCCEEDED(SQLGetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
          &autocommit, sizeof(autocommit), nullptr))) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  if (autocommit != SQL_AUTOCOMMIT_ON) {
    error = L"다른 요청을 처리하고 있습니다. 잠시 후 다시 시도해주세요.";
    return false;
  }
  if (!SQL_SUCCEEDED(SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
          reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_OFF), SQL_IS_UINTEGER))) {
    error = Diagnostic(SQL_HANDLE_DBC, dbc_);
    return false;
  }
  bool committed = false;
  int previousCount = 0;
  do {
    std::vector<std::vector<CString>> rows;
    if (!Rows(ErrorBinSql::Current, rows, error)) break;
    if (rows.size() != 1 || rows[0].size() < 2) {
      error = L"오류 수거함 정보가 등록되지 않았습니다.";
      break;
    }
    const INT64 bin = _wtoi64(rows[0][0]);
    const INT64 count = _wtoi64(rows[0][1]);
    if (bin <= 0 || bin > INT_MAX || count < 0 || count > INT_MAX) {
      error = L"오류 수거함의 번호 또는 개수가 올바르지 않습니다.";
      break;
    }
    previousCount = static_cast<int>(count);
    if (previousCount > 0) {
      CString sql;
      SQLLEN affected = -1;
      sql.Format(ErrorBinSql::InsertClear, static_cast<int>(bin), previousCount);
      if (!ExecuteAffected(sql, affected, error)) break;
      if (affected != 1) { error = L"비우기 기록을 저장하지 못했습니다."; break; }
      sql.Format(ErrorBinSql::ResetCount, static_cast<int>(bin), previousCount);
      if (!ExecuteAffected(sql, affected, error)) break;
      if (affected != 1) { error = L"오류 수거함 개수 변경을 확인하지 못했습니다."; break; }
    }
    // A second click on an already-empty bin does not create another audit row.
    if (!SQL_SUCCEEDED(SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_COMMIT))) {
      error = L"비우기 처리 결과를 확인하지 못했습니다. 수거함 상태를 조회한 후 다시 시도해주세요.";
      break;
    }
    committed = true;
    clearedCount = previousCount;
  } while (false);
  if (!committed && !SQL_SUCCEEDED(SQLEndTran(SQL_HANDLE_DBC, dbc_, SQL_ROLLBACK))) {
    // Never enable autocommit after a failed rollback: it could commit pending work.
    Disconnect();
    if (error.IsEmpty()) error = L"처리 결과를 확인할 수 없어 서버 연결을 종료했습니다. 다시 연결한 후 상태를 확인해주세요.";
    return false;
  }
  if (!SQL_SUCCEEDED(SQLSetConnectAttr(dbc_, SQL_ATTR_AUTOCOMMIT,
          reinterpret_cast<SQLPOINTER>(SQL_AUTOCOMMIT_ON), SQL_IS_UINTEGER))) {
    // Commit success is still success, but discard this unusable connection.
    Disconnect();
  }
  return committed;
}

bool Database::LoadErrorHistory(std::vector<std::vector<CString>>& rows, CString& error) {
  rows.clear();
  error.Empty();
  if (!IsConnected()) { error = L"서버에 연결되지 않았습니다."; return false; }
  return Rows(ErrorBinSql::History, rows, error);
}
