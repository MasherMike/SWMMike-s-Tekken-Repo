@echo off
rem Turns "start the Tekken app when Windows starts" on or off. Double-click again to flip it.
rem It adds or removes one small file in your Startup folder; nothing else changes.
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Tekken App.bat"
if exist "%LINK%" (
  del "%LINK%"
  echo.
  echo   Start with Windows: OFF
  echo   The app will only start when you double-click Start Tekken App.bat.
) else (
  > "%LINK%" echo @echo off
  >>"%LINK%" echo rem Made by "Start with Windows (on-off).bat": starts the Tekken app minimized at login.
  >>"%LINK%" echo set TEKKEN_APP_NO_BROWSER=1
  >>"%LINK%" echo start "Tekken app" /min "%~dp0Start Tekken App.bat"
  echo.
  echo   Start with Windows: ON
  echo   From your next login the app starts by itself, minimized in the taskbar,
  echo   without opening the browser. Double-click this file again to turn it off.
)
echo.
pause
