@echo off
setlocal

set "RUNDIR=%~dp0run"

echo ==========================================
echo    Arret des processus Alyx
echo ==========================================

:: L'API est arretee en dernier : si stop.bat est lance par l'API, il ne doit pas etre tue avant la fin
call :arreter "%RUNDIR%\ui.pid" "AlyxDesktop" "UI"
call :arreter "%RUNDIR%\stt.pid" "stt_server.py" "STT"
call :arreter "%RUNDIR%\api.pid" "api.py" "Backend API"

:: Filet de securite si le PID pointait vers 'dotnet run' (l'executable final est un enfant)
taskkill /IM AlyxDesktop.exe /T /F >nul 2>&1
if not errorlevel 1 (
    echo [OK] AlyxDesktop ferme de force.
)

echo.
echo Tous les processus connus d'Alyx ont ete termines.
exit /b 0

:: %1 = fichier PID, %2 = motif attendu dans la ligne de commande, %3 = libelle
:arreter
if not exist "%~1" (
    echo [Info] Aucun fichier PID trouve pour : %~3.
    exit /b 0
)
set "PID="
set /p PID=<"%~1"
del "%~1" >nul 2>&1
for /f "tokens=1" %%P in ("%PID%") do set "PID=%%P"
if not defined PID exit /b 0

:: Verification d'identite : un PID perime peut avoir ete reattribue a un autre programme
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%PID%'; if ($p -and $p.CommandLine -like '*%~2*') { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [Info] %~3 ^(PID: %PID%^) n'est plus actif, rien a arreter.
    exit /b 0
)

echo [Alyx] Arret : %~3 (PID: %PID%).
taskkill /PID %PID% /T /F >nul 2>&1
if not errorlevel 1 (
    echo [OK] %~3 arrete.
) else (
    echo [!] Echec de l'arret : %~3.
)
exit /b 0
