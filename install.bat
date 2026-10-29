@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "POSTINSTALL=0"
if /I "%~1"=="--postinstall" set "POSTINSTALL=1"
set "UI_EXE=%~dp0AlyxDesktop\bin\Release\net8.0-windows10.0.19041.0\AlyxDesktop.exe"

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
    if "!POSTINSTALL!"=="0" pause
    exit /b 1
)
echo [OK] Python est installe.

:: 2. Verification de .NET SDK
echo.
echo [2/5] Verification de .NET 8.0 SDK...
if "!POSTINSTALL!"=="1" if exist "%UI_EXE%" (
    echo [OK] Interface precompilee detectee ^(SDK .NET non requis^).
    dotnet --list-runtimes 2>nul | findstr /C:"Microsoft.NETCore.App 8." >nul 2>&1
    if errorlevel 1 (
        echo [!] Attention : Le Runtime .NET 8 ^(Desktop Runtime^) ne semble pas installe.
        echo     Si l'interface ne s'ouvre pas, installez .NET 8 Desktop Runtime depuis https://dotnet.microsoft.com/download/dotnet/8.0
    ) else (
        echo [OK] Runtime .NET 8 detecte.
    )
    goto :check_ia
)
dotnet --list-sdks | findstr /C:"8.0" >nul 2>&1
if errorlevel 1 (
    echo [X] .NET 8.0 SDK n'est pas installe.
    echo Veuillez installer le SDK .NET 8.0 depuis https://dotnet.microsoft.com/download
    if "!POSTINSTALL!"=="0" pause
    exit /b 1
)
echo [OK] .NET 8.0 SDK est installe.

:check_ia
:: 3. Verification des fournisseurs IA (Ollama / LM Studio)
echo.
echo [3/5] Verification des moteurs d'IA (Ollama ou LM Studio)...
set "IA_DETECTED=0"

ollama --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] Ollama est installe.
    set "IA_DETECTED=1"
) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    echo [OK] Ollama est installe.
    set "IA_DETECTED=1"
)

lms --version >nul 2>&1
if not errorlevel 1 (
    echo [OK] LM Studio est installe.
    set "IA_DETECTED=1"
) else if exist "%USERPROFILE%\.lmstudio\bin\lms.exe" (
    echo [OK] LM Studio est installe.
    set "IA_DETECTED=1"
) else if exist "%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe" (
    echo [OK] LM Studio est installe.
    set "IA_DETECTED=1"
)

if "!IA_DETECTED!"=="0" (
    echo [!] Ni Ollama ni LM Studio n'ont ete detectes.
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
if errorlevel 1 (
    echo [X] Echec de l'installation des dependances Python ^(pip install^).
    if "!POSTINSTALL!"=="0" pause
    exit /b 1
)

.\.venv\Scripts\python.exe -c "import faster_whisper" 2>nul
if errorlevel 1 (
    echo [!] faster-whisper n'a pas pu etre installe : le mode vocal ^(micro^) sera indisponible.
)

:: 5. Compilation de l'interface (evite un "dotnet run" lent a chaque lancement)
echo.
echo [5/5] Compilation de l'interface Alyx (Release)...
if "!POSTINSTALL!"=="1" if exist "%UI_EXE%" (
    echo [OK] Executable AlyxDesktop.exe deja present, compilation ignoree.
    goto :shortcut_step
)
dotnet build AlyxDesktop\AlyxDesktop.csproj -c Release --nologo -v q
if errorlevel 1 (
    echo [!] La compilation a echoue : alyx.bat utilisera 'dotnet run' ^(demarrage plus lent^).
)
echo (Apres une modification du code C#, relancez install.bat ou 'dotnet build AlyxDesktop -c Release')

:shortcut_step
:: 6. Raccourci du menu Demarrer (lance le widget sans fenetre de terminal)
if "!POSTINSTALL!"=="0" (
    echo.
    echo Creation du raccourci Alyx dans le menu Demarrer...
    powershell -NoProfile -Command "$dir = '%~dp0'.TrimEnd('\'); $s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs') + '\Alyx.lnk'); $s.TargetPath = \"$dir\Lancer_Alyx.vbs\"; $s.WorkingDirectory = $dir; $s.IconLocation = \"$dir\AlyxDesktop\Assets\logo.ico\"; $s.Description = 'Alyx - assistant local'; $s.Save()"
    if not errorlevel 1 echo [OK] Raccourci Alyx ajoute au menu Demarrer.
)

echo.
echo ==========================================
echo    Installation terminee avec succes !
echo ==========================================
echo Pour lancer Alyx, cherchez "Alyx" dans le menu Demarrer ou tapez :
echo .\alyx.bat
echo.
if "!POSTINSTALL!"=="0" pause
