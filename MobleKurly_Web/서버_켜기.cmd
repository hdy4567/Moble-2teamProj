@echo off
setlocal
chcp 65001 >nul
title MOBLE KURLY - Server
cd /d "%~dp0"
if errorlevel 1 goto folder_error

echo ============================================================
echo   모블 컬리 외부 공유 서버
echo ============================================================
echo.
echo 이 창을 열어 둔 동안 서버가 실행됩니다.
echo 팀원에게는 MOBLE KURLY PUBLIC URL 뒤의 https 주소를 보내세요.
echo 다시 실행하면 주소가 바뀔 수 있습니다. 예전 주소는 사용하지 마세요.
echo 종료하려면 이 창에서 Ctrl+C를 누르세요.
echo.

set "MOBLE_PYTHON=.venv\Scripts\python.exe"
if not exist "%MOBLE_PYTHON%" set "MOBLE_PYTHON=..\.venv\Scripts\python.exe"
if not exist "%MOBLE_PYTHON%" goto python_missing
if not exist ".env" goto env_missing
if not exist "tools\cloudflared.exe" goto tunnel_missing
if not exist "share.py" goto source_missing

"%MOBLE_PYTHON%" -X utf8 -u share.py
set "MOBLE_SERVER_EXIT=%ERRORLEVEL%"
echo.
if not "%MOBLE_SERVER_EXIT%"=="0" (
    echo 서버를 시작하지 못했거나 공유가 중단되었습니다. 위 오류를 확인하세요.
    echo 5001 포트가 사용 중이면 기존 서버 창을 먼저 확인하세요.
    echo 이미 실행 중인 서버를 강제로 종료하거나 반복 실행하지 마세요.
    echo DB 오류이면 팀 DB PC와 내부 네트워크 연결을 확인하세요.
    echo 자세한 방법은 README.md 또는 문서\사용안내\서버_실행_가이드.md 파일을 확인하세요.
) else (
    echo 외부 공유 서버가 종료되었습니다.
)
goto finish

:folder_error
echo 프로젝트 폴더를 열 수 없습니다. 실행 파일을 프로젝트 안에 두세요.
goto failed

:python_missing
echo .venv\Scripts\python.exe 파일이 없습니다.
echo 이 파일은 설치가 완료된 서버 PC에서 실행하는 파일입니다.
echo 다른 PC에서는 README.md의 설치 절차를 먼저 진행하세요.
goto failed

:env_missing
echo .env 설정 파일이 없습니다. 담당자에게 DB 연결 설정을 요청하세요.
echo 비밀번호를 화면에 공개하거나 SQL을 다시 실행하지 마세요.
goto failed

:tunnel_missing
echo tools\cloudflared.exe 파일이 없습니다. 담당자에게 확인하세요.
goto failed

:source_missing
echo share.py 파일이 없습니다. 실행 파일을 프로젝트 메인 폴더에 두세요.
goto failed

:failed
set "MOBLE_SERVER_EXIT=1"

:finish
echo.
pause
exit /b %MOBLE_SERVER_EXIT%
