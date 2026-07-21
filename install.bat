@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    Installation des dependances ALYX
echo ==========================================
echo.

:: 1. Verification de Python
echo [1/4] Verification de Python...
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
echo [2/4] Verification de .NET 8.0 SDK...
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
echo [3/4] Verification des moteurs d'IA (Ollama ou LM Studio)...
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
echo [4/4] Configuration de l'environnement virtuel et des dependances...
if not exist .venv (
    echo Creation de l'environnement virtuel .venv...
    python -m venv .venv
)

echo Installation des librairies Python requises...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo ==========================================
echo    Configuration du lancement Alyx...
echo ==========================================
echo Le script 'alyx.bat' est deja configure pour lancer l'API et l'UI en arriere-plan.


echo.
echo ==========================================
echo    Installation terminee avec succes !
echo ==========================================
echo Pour lancer Alyx, tapez simplement la commande suivante dans ce dossier :
echo .\alyx
echo.
echo (Vous pouvez aussi ajouter ce dossier a votre variable PATH Windows pour l'utiliser partout).
echo.
pause
