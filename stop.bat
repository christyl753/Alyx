@echo off
setlocal enabledelayedexpansion

set "RUNDIR=%~dp0run"
set "API_PID_FILE=%RUNDIR%\api.pid"
set "UI_PID_FILE=%RUNDIR%\ui.pid"
set "STT_PID_FILE=%RUNDIR%\stt.pid"

echo ==========================================
echo    Arret des processus Alyx
echo ==========================================

:: Arret de l'API (Backend)
if exist "%API_PID_FILE%" (
    set /p API_PID=<"%API_PID_FILE%"
    echo [Alyx] Tentative d'arret du Backend API (PID: !API_PID!)...
    taskkill /PID !API_PID! /T /F >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Backend API arrete.
    ) else (
        echo [!] Impossible d'arreter le Backend (peut-etre deja arrete).
    )
    del "%API_PID_FILE%"
) else (
    echo [Info] Aucun fichier PID trouve pour l'API.
)

:: Arret du STT (Backend)
if exist "%STT_PID_FILE%" (
    set /p STT_PID=<"%STT_PID_FILE%"
    echo [Alyx] Tentative d'arret du STT (PID: !STT_PID!)...
    taskkill /PID !STT_PID! /T /F >nul 2>&1
    if not errorlevel 1 (
        echo [OK] STT arrete.
    ) else (
        echo [!] Impossible d'arreter le STT (peut-etre deja arrete).
    )
    del "%STT_PID_FILE%"
) else (
    echo [Info] Aucun fichier PID trouve pour le STT.
)


:: Arret de l'UI (Frontend)
if exist "%UI_PID_FILE%" (
    set /p UI_PID=<"%UI_PID_FILE%"
    echo [Alyx] Tentative d'arret du Frontend UI (PID: !UI_PID!)...
    taskkill /PID !UI_PID! /T /F >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Frontend UI arrete.
    ) else (
        echo [!] Impossible d'arreter l'UI (peut-etre deja arretee).
    )
    del "%UI_PID_FILE%"
) else (
    echo [Info] Aucun fichier PID trouve pour l'UI.
)

echo.
echo Tous les processus connus d'Alyx ont ete termines.
