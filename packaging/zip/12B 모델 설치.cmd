@echo off
rem Installs the Gemma 4 12B escalation model into %LOCALAPPDATA%\Hinton\models
rem so Hinton auto-enables escalation. No admin needed (per-user location).
chcp 65001 >nul
setlocal
set "MODEL=gemma-4-12b-it-qat-q4_0.gguf"
set "DST=%LOCALAPPDATA%\Hinton\models"

if not exist "%~dp0%MODEL%" (
  if exist "%DST%\%MODEL%" ( echo 12B 모델이 이미 설치되어 있습니다. & pause & exit /b 0 )
  echo "%MODEL%" 을 찾을 수 없습니다. 이 파일을 압축 해제한 폴더에서 실행하세요.
  pause & exit /b 1
)
if not exist "%DST%" mkdir "%DST%"
echo 12B 모델을 설치하는 중입니다... (약 6.5GB, 잠시 걸립니다)
move /y "%~dp0%MODEL%" "%DST%\%MODEL%" >nul 2>&1
if not exist "%DST%\%MODEL%" copy /y "%~dp0%MODEL%" "%DST%\%MODEL%" >nul
echo.
echo 완료되었습니다. Hinton을 재시작하면 어려운 문제에서 12B로 자동 에스컬레이션됩니다.
pause
endlocal
