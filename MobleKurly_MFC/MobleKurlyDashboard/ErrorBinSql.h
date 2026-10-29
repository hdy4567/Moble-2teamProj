#pragma once

namespace ErrorBinSql {
inline constexpr wchar_t Current[] =
    L"SELECT bin_id,item_count FROM error_bin ORDER BY bin_id LIMIT 1 FOR UPDATE";
inline constexpr wchar_t InsertClear[] =
    L"INSERT INTO error_bin_clear_logs (bin_id,cleared_count,cleared_at) "
    L"VALUES (%d,%d,CURRENT_TIMESTAMP)";
inline constexpr wchar_t ResetCount[] =
    L"UPDATE error_bin SET item_count=0,updated_at=CURRENT_TIMESTAMP "
    L"WHERE bin_id=%d AND item_count=%d";
// This is incident history, NOT the bin-emptying audit trail.
inline constexpr wchar_t History[] =
    L"SELECT DATE_FORMAT(l.created_at,'%Y-%m-%d %H:%i:%s'),"
    L"l.log_id,COALESCE(CAST(oi.order_id AS CHAR),'-'),"
    L"COALESCE(expected.name,'미등록 상품'),COALESCE(detected.name,'미검출'),"
    L"CASE l.result WHEN 'ERROR' THEN '오류' WHEN 'UNKNOWN' THEN '미확인' ELSE '정상' END,"
    L"CASE l.destination WHEN 'ERROR_BIN' THEN '오류 수거함' ELSE '정상 출고' END "
    L"FROM outbound_logs l "
    L"LEFT JOIN outbound_jobs j ON j.job_id=l.job_id "
    L"LEFT JOIN order_items oi ON oi.item_id=j.item_id "
    L"LEFT JOIN products expected ON expected.product_id=l.expected_product_id "
    L"LEFT JOIN products detected ON detected.product_id=l.detected_product_id "
    L"WHERE l.result='ERROR' OR l.destination='ERROR_BIN' "
    L"ORDER BY l.created_at DESC,l.log_id DESC LIMIT 200";
}
