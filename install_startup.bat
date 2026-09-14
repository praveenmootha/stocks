@echo off
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0run_flask.bat"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" mkdir "%STARTUP%"
copy /Y "%SCRIPT%" "%STARTUP%\run_flask.bat" >nul
echo Added run_flask.bat to Windows Startup folder.
echo You can remove it by deleting "%STARTUP%\run_flask.bat".
pause
