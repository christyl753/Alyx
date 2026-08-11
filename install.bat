@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    Installation des dependances ALYX
echo ==========================================
echo.

:: 1. Verification de Python
echo [1/5] Verification de Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python n'est pas installe ou n'est pas dans le PATH.
    echo Veuillez installer Python 3.10+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python est installe.

:: 2. Verification de .NET SDK
echo.
echo [2/5] Verification de .NET 8.0 SDK...
dotnet --list-sdks | findstr /C:"8.0" >nul 2>&1
if errorlevel 1 (
    echo [X] .NET 8.0 SDK n'est pas installe.
    echo Veuillez installer le SDK .NET 8.0 depuis https://dotnet.microsoft.com/download
    pause
    exit /b 1
)
echo [OK] .NET 8.0 SDK est installe.

:: 3. Verification des fournisseurs IA (Ollama / LM Studio)
echo.
echo [3/5] Verification des moteurs d'IA (Ollama ou LM Studio)...
set "IA_DETECTED=0"

ollama --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] Ollama est installe.
    set "IA_DETECTED=1"
)

lms --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] LM Studio est installe.
    set "IA_DETECTED=1"
)

if "!IA_DETECTED!"=="0" (
    echo [!] Ni Ollama ni LM Studio n'ont ete detectes dans le PATH.
    echo L'assistant necessite un moteur d'IA local.
    echo Veuillez installer Ollama ^(https://ollama.com/^) ou LM Studio ^(https://lmstudio.ai/^).
)

:: 4. Installation des dependances Python
echo.
echo [4/5] Configuration de l'environnement virtuel et des dependances...
if not exist .venv (
    echo Creation de l'environnement virtuel .venv...
    python -m venv .venv
)

echo Installation des librairies Python requises...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

:: 5. Creation de la commande globale 'alyx'
echo.
echo [5/5] Creation de la commande globale 'alyx'...
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

powershell -NoProfile -Command ^
    "$dir = '%PROJECT_DIR%'; $p = [Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) { $p = '' }; if (($p -split ';') -notcontains $dir) { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $dir), 'User'); Write-Host '[OK] Dossier ajoute au PATH utilisateur.' } else { Write-Host '[OK] Dossier deja present dans le PATH utilisateur.' }"

echo.
echo ==========================================
echo    Installation terminee avec succes !
echo ==========================================
echo Ouvrez un NOUVEAU terminal, puis lancez Alyx depuis n'importe quel dossier avec :
echo     alyx
echo.
echo (alyx.bat est resolu automatiquement via PATHEXT, aucun alias supplementaire requis).
echo.
pause
