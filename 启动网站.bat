@echo off
cd /d "%~dp0"

rem If the website is already running, just open the browser (do not start twice)
rem Verify the saved PID really belongs to this webgui.py process (a recycled PID
rem may now be owned by another python.exe) by matching its command line.
if exist "webgui.pid" (
    for /f %%i in (webgui.pid) do (
        powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process -Filter 'ProcessId=%%i').CommandLine -like '*webgui.py*') { exit 0 } else { exit 1 }" 2>nul
        if not errorlevel 1 (
            echo Website is already running. Opening browser...
            ping -n 2 127.0.0.1 >nul
            start "" "http://127.0.0.1:5000"
            exit /b
        )
    )
    del "webgui.pid"
)

echo Starting Chaoxing console...
rem /k keeps the black window open: live logs show here, closing the window stops the website
start "Chaoxing Console - close this window to STOP" cmd /k "python webgui.py"

rem Wait for the website to be ready, then open the browser
ping -n 4 127.0.0.1 >nul
rem webgui.py only writes webgui.pid after the port probe succeeds;
rem if it is missing the port was taken / startup failed, do not open a broken page
if not exist "webgui.pid" (
    echo Website failed to start. Check the console for the cause.
    exit /b 1
)
start "" "http://127.0.0.1:5000"
exit
