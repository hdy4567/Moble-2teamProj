# MFC Main1 + 오류수거함 기능만 병합

기준: `mfc_main1.zip` (메인 원본). `mfc_오류수거함.zip`에서 **오류수거함 비우기** 및 **오류 발생 이력**만 선택 병합했습니다.

## 기능
- 오류 수거함 비우기: 실제 수거함을 먼저 비웠는지 확인 창 표시 → MySQL `error_bin.item_count` 0으로 변경 및 `error_bin_clear_logs` 비우기 기록 저장 (트랜잭션).
- 오류 수거함 이력: `outbound_logs`의 실제 `ERROR`/`ERROR_BIN` 기록 최신 200건 조회. 비우기 이력과는 별개입니다.
- 기존 화면 버튼 위치 (692,696 / 872,696) 그대로 유지. 기존 UI 배치 변경 없음.

## 변경 파일
- 기존 파일의 *해당 부분만*: `DashboardFrame.cpp`, `DashboardFrame.h`, `Database.h`, `MobleKurlyDashboard.vcxproj`, `MobleKurlyDashboard.vcxproj.filters`
- 새 파일: `ErrorBin.cpp`, `ErrorBinSql.h`, `ErrorHistoryDialog.cpp`, `ErrorHistoryDialog.h`
- 그 밖의 모든 기존 파일: SHA 바이트 기준 메인과 동일. 특히 CCTV, PDF, 로그인, 정지/출고 통신 소스 그대로 유지.

## 검증
ZIP 무결성, 프로젝트 XML 구조, 기존 원본 대비 변경 범위, 함수·파일 등록 확인. Windows Visual Studio MFC 실컴파일 및 DB 연결·실행은 현장 테스트 필요.

## 주의
기존 DB에 `error_bin`, `error_bin_clear_logs`, `outbound_logs` 테이블이 있어야 합니다. 오류 이력은 발생 로그이며 수거함 비우기 이력이 아닙니다. `config.ini` 실제 접속 설정 보존하세요.
