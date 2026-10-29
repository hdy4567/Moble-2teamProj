@echo off
setlocal
chcp 65001 >nul
title MOBLE KURLY - Server Manager
cd /d "%~dp0"
if errorlevel 1 goto folder_error
set "MOBLE_PYTHON=.venv\Scripts\python.exe"
if not exist "%MOBLE_PYTHON%" set "MOBLE_PYTHON=..\.venv\Scripts\python.exe"
if not exist "%MOBLE_PYTHON%" goto python_missing
if not exist "tools\server_control.py" goto manager_missing
"%MOBLE_PYTHON%" -X utf8 -u "tools\server_control.py"
set "MOBLE_MANAGER_EXIT=%ERRORLEVEL%"
if "%MOBLE_MANAGER_EXIT%"=="0" exit /b 0
echo.
echo 관리 도구가 중단되었습니다. 위 안내를 확인하세요.
pause
exit /b %MOBLE_MANAGER_EXIT%

:folder_error
echo 프로젝트 폴더를 열 수 없습니다.
goto failed

:python_missing
echo .venv\Scripts\python.exe 파일이 없습니다. 설치가 완료된 서버 PC에서 실행하세요.
goto failed

:manager_missing
echo tools\server_control.py 파일이 없습니다. 담당자에게 확인하세요.

:failed
pause
exit /b 1
