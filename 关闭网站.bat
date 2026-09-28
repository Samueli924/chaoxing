@echo off
cd /d "%~dp0"

if not exist "webgui.pid" (
    echo No running website found.
    ping -n 3 127.0.0.1 >nul
    exit /b
)

for /f %%i in (webgui.pid) do set "WEBPID=%%i"

rem /t also kills child processes (a running study task is stopped too)
tasklist /fi "PID eq %WEBPID%" 2>nul | find "%WEBPID%" >nul
if errorlevel 1 (
    echo Website process already exited. Cleaning up.
    del "webgui.pid"
    ping -n 3 127.0.0.1 >nul
    exit /b
)

taskkill /pid %WEBPID% /t /f >nul 2>&1
if errorlevel 1 (
    echo Failed to stop it. Please close the "Chaoxing Console" window manually.
) else (
    echo Website stopped. Any running study task is also stopped.
)
del "webgui.pid" 2>nul
ping -n 3 127.0.0.1 >nul
