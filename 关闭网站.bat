@echo off
cd /d "%~dp0"

if not exist "webgui.pid" (
    echo No running website found.
    ping -n 3 127.0.0.1 >nul
    exit /b
)

for /f %%i in (webgui.pid) do set "WEBPID=%%i"

rem /t also kills child processes (a running study task is stopped too)
rem Verify the saved PID really belongs to this webgui.py process before killing it:
rem a recycled PID may now be owned by an unrelated python.exe, so match the
rem process command line (contains "webgui.py") instead of the image name alone.
powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter 'ProcessId=%WEBPID%').CommandLine -like '*webgui.py*') { exit 0 } else { exit 1 }" 2>nul
if errorlevel 1 (
    echo Website process already exited. Cleaning up.
    del "webgui.pid"
    ping -n 3 127.0.0.1 >nul
    exit /b
)

taskkill /pid %WEBPID% /t /f >nul 2>&1
if errorlevel 1 (
    echo Failed to stop it. Please close the "Chaoxing Console" window manually.
    rem Keep webgui.pid so a later run of this script can retry stopping the website
    ping -n 3 127.0.0.1 >nul
    exit /b 1
)
echo Website stopped. Any running study task is also stopped.
del "webgui.pid" 2>nul
ping -n 3 127.0.0.1 >nul
