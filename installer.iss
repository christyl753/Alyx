; Script Inno Setup pour Alyx — Installateur Windows (.exe)
; Génère un Setup autonome installant le runtime Avalonia pré-packagé et le backend Python

#define MyAppName "Alyx"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "christyl753"
#define MyAppURL "https://github.com/christyl753/Alyx"
#define MyAppExeName "AlyxDesktop.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF0123456789}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=Alyx-{#MyAppVersion}-Windows-Setup
SetupIconFile=AlyxDesktop\Assets\logo.ico
UninstallDisplayIcon={app}\bin\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Fichiers Desktop compilés (si présents dans publish\app)
Source: "publish\app\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: DirExists(ExpandConstant('{src}\publish\app'))
; Repli si compilé via dotnet build standard
Source: "AlyxDesktop\bin\Release\net8.0-windows10.0.19041.0\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: not DirExists(ExpandConstant('{src}\publish\app'))

; Backend Python
Source: "api.py"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "ai.py"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "stt_server.py"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "config.yaml"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}\backend"; Flags: ignoreversion

; Modules Core & Function
Source: "core\*"; DestDir: "{app}\backend\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "function\*"; DestDir: "{app}\backend\function"; Flags: ignoreversion recursesubdirs createallsubdirs

; Scripts de lancement / arrêt
Source: "alyx.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "stop.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "Lancer_Alyx.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "Arreter_Alyx.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "AlyxDesktop\Assets\logo.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"
Name: "{app}\run"

[Icons]
Name: "{userprograms}\Alyx"; Filename: "{app}\bin\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\logo.ico"; Comment: "Alyx - Assistant Local Souverain"
Name: "{group}\Alyx"; Filename: "{app}\bin\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\logo.ico"
Name: "{group}\Arrêter Alyx"; Filename: "{app}\Arreter_Alyx.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\assets\logo.ico"
Name: "{group}\Désinstaller Alyx"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Alyx"; Filename: "{app}\bin\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\logo.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Run]
Filename: "{app}\install.bat"; Parameters: "--postinstall"; WorkingDir: "{app}"; Description: "Configurer l'environnement Python local"; Flags: runascurrentuser waituntilterminated postinstall shellexec; StatusMsg: "Préparation de l'environnement Python..."
Filename: "{app}\bin\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Lancer Alyx maintenant"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userprograms}\Alyx.lnk"
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\run"
