@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

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

.\.venv\Scripts\python.exe -c "import faster_whisper" 2>nul
if errorlevel 1 (
    echo [!] faster-whisper n'a pas pu etre installe : le mode vocal ^(micro^) sera indisponible.
)

:: 5. Compilation de l'interface (evite un "dotnet run" lent a chaque lancement)
echo.
echo [5/5] Compilation de l'interface Alyx (Release)...
dotnet build AlyxDesktop\AlyxDesktop.csproj -c Release --nologo -v q
if errorlevel 1 (
    echo [!] La compilation a echoue : alyx.bat utilisera 'dotnet run' ^(demarrage plus lent^).
)
echo (Apres une modification du code C#, relancez install.bat ou 'dotnet build AlyxDesktop -c Release')

:: 6. Raccourci du menu Demarrer (lance le widget sans fenetre de terminal)
echo.
echo Creation du raccourci Alyx dans le menu Demarrer...
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs') + '\Alyx.lnk'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%~dp0Lancer_Alyx.vbs\"'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0AlyxDesktop\Assets\logo.ico'; $s.Description = 'Alyx - assistant local'; $s.Save()"
if not errorlevel 1 echo [OK] Raccourci Alyx ajoute au menu Demarrer.


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
