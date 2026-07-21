@echo off
set "LOGDIR=%~dp0logs"
set "RUNDIR=%~dp0run"
mkdir "%LOGDIR%" 2>nul
mkdir "%RUNDIR%" 2>nul

echo [Alyx] Demarrage du Backend (API)...
rem Start API and redirect stdout/stderr to log, capture PID
start "Alyx API" /B "%~dp0.venv\Scripts\python.exe" "%~dp0api.py" >"%LOGDIR%\api.log" 2>&1
rem Save PID (Windows does not provide direct PID from start, use tasklist trick)
for /f "tokens=2" %%I in ('tasklist /FI "IMAGENAME eq python.exe" /NH ^| findstr /I "api.py"') do echo %%I > "%RUNDIR%\api.pid"

timeout /t 2 /nobreak >nul

echo [Alyx] Demarrage du Frontend (Avalonia)...
cd /d "%~dp0AlyxDesktop"
rem Start UI and redirect logs, capture PID
start "Alyx UI" /B dotnet run >"%LOGDIR%\ui.log" 2>&1
for /f "tokens=2" %%I in ('tasklist /FI "IMAGENAME eq dotnet.exe" /NH ^| findstr /I "AlyxDesktop"') do echo %%I > "%RUNDIR%\ui.pid"
