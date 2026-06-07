@echo off
rem Creates Desktop + Start Menu shortcuts to the extracted Hinton.exe.
chcp 65001 >nul
set "APPDIR=%~dp0Hinton"
if not exist "%APPDIR%\Hinton.exe" (
  echo Hinton 폴더를 찾을 수 없습니다. 이 파일을 압축 해제한 폴더에서 실행하세요.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($p in @([Environment]::GetFolderPath('Desktop')+'\Hinton.lnk',[Environment]::GetFolderPath('StartMenu')+'\Programs\Hinton.lnk')){ $s=$w.CreateShortcut($p); $s.TargetPath=(Join-Path $env:APPDIR 'Hinton.exe'); $s.WorkingDirectory=$env:APPDIR; $s.Save() }"
echo.
echo 바로가기를 생성했습니다 (바탕화면 + 시작메뉴).
pause
