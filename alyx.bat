@echo off
set "LOGDIR=%~dp0logs"
set "RUNDIR=%~dp0run"
mkdir "%LOGDIR%" 2>nul
mkdir "%RUNDIR%" 2>nul

echo [Alyx] Demarrage du Backend (API)...
rem Start API and redirect stdout/stderr to log, capture PID
start "Alyx API" /B "%~dp0.venv\Scripts\python.exe" "%~dp0api.py" >"%LOGDIR%\api.log" 2>&1
rem Save PID using PowerShell
for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe'' AND CommandLine LIKE ''%%api.py%%''').ProcessId"') do echo %%I > "%RUNDIR%\api.pid"

echo [Alyx] Demarrage du Micro-service STT...
start "Alyx STT" /B "%~dp0.venv\Scripts\python.exe" "%~dp0stt_server.py" >"%LOGDIR%\stt.log" 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe'' AND CommandLine LIKE ''%%stt_server.py%%''').ProcessId"') do echo %%I > "%RUNDIR%\stt.pid"

timeout /t 2 /nobreak >nul

echo [Alyx] Demarrage du Frontend (Avalonia)...
cd /d "%~dp0AlyxDesktop"
rem Start UI and redirect logs, capture PID
start "Alyx UI" /B dotnet run >"%LOGDIR%\ui.log" 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''dotnet.exe'' AND CommandLine LIKE ''%%AlyxDesktop%%''').ProcessId"') do echo %%I > "%RUNDIR%\ui.pid"
