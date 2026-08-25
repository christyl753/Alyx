@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    Installation des dependances ALYX
echo ==========================================
echo.

:: 1. Verification de Python
echo [1/6] Verification de Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python n'est pas installe ou n'est pas dans le PATH.
    echo Veuillez installer Python 3.10+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python est installe.
for /f %%v in ('python -c "import sys; print(sys.version_info[1])"') do set "PY_MINOR=%%v"
if %PY_MINOR% LSS 11 (
    echo [!] Python 3.%PY_MINOR% detecte : seules les versions 3.11 et 3.12 sont supportees.
    echo     Le module STT ^(faster-whisper^) sera indisponible.
) else if %PY_MINOR% GEQ 14 (
    echo [!] Python 3.%PY_MINOR% detecte : seules les versions 3.11 et 3.12 sont supportees.
    echo     Au-dela ^(3.14+^), le module STT ^(faster-whisper^) est indisponible ^(dependances C absentes/incompatibles^)
    echo     et sera silencieusement desactive. Installez Python 3.11 ou 3.12 pour beneficier de la reconnaissance vocale.
)

:: 2. Verification de .NET SDK
echo.
echo [2/6] Verification de .NET 8.0 SDK...
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
echo [3/6] Verification des moteurs d'IA (Ollama ou LM Studio)...
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
echo [4/6] Configuration de l'environnement virtuel et des dependances...
if not exist .venv (
    echo Creation de l'environnement virtuel .venv...
    python -m venv .venv
)

echo Installation des librairies Python requises...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

:: 5. Telechargement du modele de voix Piper (une seule fois, ensuite 100% local)
echo.
echo [5/6] Telechargement de la voix francaise Piper (TTS)...
set "PIPER_DIR=%~dp0models\piper"
set "PIPER_MODEL=%PIPER_DIR%\fr_FR-siwis-medium.onnx"
set "PIPER_CONFIG=%PIPER_DIR%\fr_FR-siwis-medium.onnx.json"
set "PIPER_BASE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium"

if not exist "%PIPER_DIR%" mkdir "%PIPER_DIR%"

if exist "%PIPER_MODEL%" if exist "%PIPER_CONFIG%" (
    echo [OK] Voix Piper deja presente.
) else (
    powershell -NoProfile -Command ^
        "try { Invoke-WebRequest -Uri '%PIPER_BASE_URL%/fr_FR-siwis-medium.onnx' -OutFile '%PIPER_MODEL%' -UseBasicParsing; Invoke-WebRequest -Uri '%PIPER_BASE_URL%/fr_FR-siwis-medium.onnx.json' -OutFile '%PIPER_CONFIG%' -UseBasicParsing; Write-Host '[OK] Voix Piper telechargee.' } catch { Write-Host '[!] Echec du telechargement de la voix Piper. Le mode vocal (parole) sera indisponible.' }"
)

:: 6. Creation de la commande globale 'alyx'
echo.
echo [6/6] Creation de la commande globale 'alyx'...
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

powershell -NoProfile -Command ^
    "$dir = '%PROJECT_DIR%'; $p = [Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) { $p = '' }; $parts = @($p -split ';' | Where-Object { $_ -ne '' }); $parts = @($parts | Where-Object { $_ -eq $dir -or -not (Test-Path (Join-Path $_ 'alyx.bat') -PathType Leaf) }); if ($parts -notcontains $dir) { $parts += $dir }; [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User'); Write-Host '[OK] PATH utilisateur mis a jour (toute ancienne installation Alyx retiree du PATH pour eviter un doublon/conflit avec celle-ci).'"

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
