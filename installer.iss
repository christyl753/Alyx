; Script Inno Setup pour Alyx — installateur Windows
; Compile avec : "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "Alyx"
#define MyAppVersion "2.0"
#define MyAppPublisher "christyl753"
#define MyAppURL "https://github.com/christyl753/Alyx"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF0123456789}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=Alyx-Setup
SetupIconFile=AlyxDesktop\Assets\logo.ico
UninstallDisplayIcon={app}\AlyxDesktop\Assets\logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
LicenseFile=
InfoBeforeFile=

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Backend Python
Source: "api.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "ai.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "stt_server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "pyrightconfig.json"; DestDir: "{app}"; Flags: ignoreversion

; Core modules
Source: "core\__init__.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "core\exceptions.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "core\llm_provider.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "core\logger.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "core\preferences.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "core\system_monitor.py"; DestDir: "{app}\core"; Flags: ignoreversion

; Function modules (outils de l'agent)
Source: "function\__init__.py"; DestDir: "{app}\function"; Flags: ignoreversion
Source: "function\files.py"; DestDir: "{app}\function"; Flags: ignoreversion
Source: "function\scrap.py"; DestDir: "{app}\function"; Flags: ignoreversion
Source: "function\system.py"; DestDir: "{app}\function"; Flags: ignoreversion
Source: "function\tts.py"; DestDir: "{app}\function"; Flags: ignoreversion
Source: "function\voice.py"; DestDir: "{app}\function"; Flags: ignoreversion

; Scripts de lancement / arret
Source: "alyx.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "stop.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "Lancer_Alyx.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "Arreter_Alyx.vbs"; DestDir: "{app}"; Flags: ignoreversion

; Frontend Avalonia (executable precompile)
Source: "AlyxDesktop\bin\Release\net8.0-windows10.0.19041.0\*"; DestDir: "{app}\AlyxDesktop\bin\Release\net8.0-windows10.0.19041.0"; Flags: ignoreversion recursesubdirs createallsubdirs

; Assets (icone, logo, polices)
Source: "AlyxDesktop\Assets\*"; DestDir: "{app}\AlyxDesktop\Assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; Interface XAML et code-behind (necessaire pour dotnet build si l'utilisateur veut recompiler)
Source: "AlyxDesktop\*.axaml"; DestDir: "{app}\AlyxDesktop"; Flags: ignoreversion
Source: "AlyxDesktop\*.axaml.cs"; DestDir: "{app}\AlyxDesktop"; Flags: ignoreversion
Source: "AlyxDesktop\*.cs"; DestDir: "{app}\AlyxDesktop"; Excludes: "*.axaml.cs"; Flags: ignoreversion
Source: "AlyxDesktop\*.csproj"; DestDir: "{app}\AlyxDesktop"; Flags: ignoreversion
Source: "AlyxDesktop\app.manifest"; DestDir: "{app}\AlyxDesktop"; Flags: ignoreversion
Source: "AlyxDesktop\Controls\*"; DestDir: "{app}\AlyxDesktop\Controls"; Flags: ignoreversion recursesubdirs
Source: "AlyxDesktop\Platform\*"; DestDir: "{app}\AlyxDesktop\Platform"; Flags: ignoreversion recursesubdirs
Source: "AlyxDesktop\Services\*"; DestDir: "{app}\AlyxDesktop\Services"; Flags: ignoreversion recursesubdirs
Source: "AlyxDesktop\Models\*"; DestDir: "{app}\AlyxDesktop\Models"; Flags: ignoreversion recursesubdirs

; Tests
Source: "tests\test_prompt.py"; DestDir: "{app}\tests"; Flags: ignoreversion

; README
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"
Name: "{app}\run"

[Icons]
; Raccourcis du menu Demarrer (a la racine Programs et dans le groupe Alyx, cible directe .vbs pour indexation Windows 11)
Name: "{userprograms}\Alyx"; Filename: "{app}\Lancer_Alyx.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\AlyxDesktop\Assets\logo.ico"; Comment: "Alyx - assistant local"
Name: "{group}\Alyx"; Filename: "{app}\Lancer_Alyx.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\AlyxDesktop\Assets\logo.ico"; Comment: "Alyx - assistant local"
Name: "{group}\Arreter Alyx"; Filename: "{app}\Arreter_Alyx.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\AlyxDesktop\Assets\logo.ico"; Comment: "Arreter Alyx"
Name: "{group}\Desinstaller Alyx"; Filename: "{uninstallexe}"
; Raccourci sur le bureau (optionnel)
Name: "{autodesktop}\Alyx"; Filename: "{app}\Lancer_Alyx.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\AlyxDesktop\Assets\logo.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis supplementaires :"; Flags: unchecked

[Run]
; Post-installation : creer le venv et installer les dependances Python (sans pause ni recompilation .NET)
Filename: "{app}\install.bat"; Parameters: "--postinstall"; WorkingDir: "{app}"; Description: "Installer les dependances Python (.venv)"; Flags: runascurrentuser waituntilterminated postinstall shellexec; StatusMsg: "Configuration de l'environnement Python..."
Filename: "{app}\Lancer_Alyx.vbs"; WorkingDir: "{app}"; Description: "Lancer Alyx maintenant"; Flags: nowait postinstall shellexec skipifsilent

[UninstallDelete]
; Nettoyer les fichiers generes au runtime
Type: files; Name: "{userprograms}\Alyx.lnk"
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\function\__pycache__"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\run"

[Registry]
; Nettoyer l'entree de demarrage automatique a la desinstallation (sans la creer a l'installation)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Alyx"; Flags: uninsdeletevalue dontcreatekey

[UninstallRun]
; Arreter proprement les processus Alyx actifs avant suppression des fichiers
Filename: "{app}\stop.bat"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "StopAlyx"
