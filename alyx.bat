@echo off
set "LOGDIR=%~dp0logs"
set "RUNDIR=%~dp0run"
rem Sortie console/fichier en UTF-8 (evite les UnicodeEncodeError cp1252 dans les logs)
set "PYTHONUTF8=1"
mkdir "%LOGDIR%" 2>nul
mkdir "%RUNDIR%" 2>nul

echo [Alyx] Demarrage du Backend (API)...
rem Start API and redirect stdout/stderr to log, capture PID (processus de CE dossier uniquement)
start "Alyx API" /B "%~dp0.venv\Scripts\python.exe" "%~dp0api.py" >"%LOGDIR%\api.log" 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -and $_.CommandLine.Contains('%~dp0api.py') } | Sort-Object CreationDate | Select-Object -First 1).ProcessId"') do >"%RUNDIR%\api.pid" echo %%I

echo [Alyx] Demarrage du Micro-service STT...
start "Alyx STT" /B "%~dp0.venv\Scripts\python.exe" "%~dp0stt_server.py" >"%LOGDIR%\stt.log" 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -and $_.CommandLine.Contains('%~dp0stt_server.py') } | Sort-Object CreationDate | Select-Object -First 1).ProcessId"') do >"%RUNDIR%\stt.pid" echo %%I

timeout /t 2 /nobreak >nul

echo [Alyx] Demarrage du Frontend (Avalonia)...
rem Executable precompile (install.bat) : demarrage immediat, sans passe de build "dotnet run"
set "UI_EXE=%~dp0AlyxDesktop\bin\Release\net8.0-windows10.0.19041.0\AlyxDesktop.exe"
if exist "%UI_EXE%" (
    start "Alyx UI" /B "%UI_EXE%" >"%LOGDIR%\ui.log" 2>&1
    for /f %%I in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''AlyxDesktop.exe''' | Sort-Object CreationDate -Descending | Select-Object -First 1).ProcessId"') do >"%RUNDIR%\ui.pid" echo %%I
) else (
    echo [Alyx] Executable introuvable, compilation via dotnet run ^(lancez install.bat pour accelerer le demarrage^)...
    cd /d "%~dp0AlyxDesktop"
    start "Alyx UI" /B dotnet run -c Release >"%LOGDIR%\ui.log" 2>&1
)
