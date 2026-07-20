@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    Installation des dependances ALYX
echo ==========================================
echo.

:: 1. Verification de Python
echo [1/4] Verification de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
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
if %errorlevel% neq 0 (
    echo [X] .NET 8.0 SDK n'est pas installe.
    echo Veuillez installer le SDK .NET 8.0 depuis https://dotnet.microsoft.com/download
    pause
    exit /b 1
)
echo [OK] .NET 8.0 SDK est installe.

:: 3. Verification de Ollama
echo.
echo [3/4] Verification de Ollama...
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama n'est pas detecte dans le PATH.
    echo L'assistant necessite Ollama pour l'IA locale.
    echo Telechargez-le depuis https://ollama.com/
    echo Si vous l'avez deja installe, assurez-vous qu'il est lance.
) else (
    echo [OK] Ollama est installe.
)

:: 4. Installation des dependances Python
echo.
echo [4/4] Configuration de l'environnement virtuel et des dependances...
if not exist .venv (
    echo Creation de l'environnement virtuel .venv...
    python -m venv .venv
)

echo Installation des librairies Python requises...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ==========================================
echo    Installation terminee avec succes !
echo ==========================================
echo Pour lancer Alyx, ouvrez deux terminaux :
echo 1. .venv\Scripts\python api.py
echo 2. cd AlyxDesktop ^&^& dotnet run
echo.
pause
