; Inno Setup script for Hinton — packages the PyInstaller onedir output
; (dist\Hinton) into a single installer: Hinton-Setup.exe
;
; Build it with the Inno Setup compiler (ISCC.exe) FROM THE PROJECT ROOT:
;     ISCC packaging\installer.iss
; or open this file in the Inno Setup IDE and press Build (F9).
;
; Prerequisite: run scripts\build_app.ps1 first so that dist\Hinton exists.

#define MyAppName        "Hinton"
#define MyAppVersion     "0.1.0"
#define MyAppPublisher   "Hinton for SASA"
#define MyAppExeName     "Hinton.exe"
; Path to the PyInstaller output, relative to this .iss file (packaging\ -> ..\dist\Hinton)
#define DistDir          "..\dist\Hinton"

[Setup]
; A stable, unique AppId so upgrades/uninstall are recognised across versions.
AppId={{B7E6F2C1-3A4D-4E5F-9A1B-0C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-machine install under Program Files -> needs admin elevation.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=.
OutputBaseFilename=Hinton-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Recursively pull in the entire PyInstaller onedir output
; (Hinton.exe + _internal\ with frontend\, plugins\, python runtime, .NET bridge).
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut (always) + Start Menu uninstall entry
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
; Optional desktop shortcut (driven by the [Tasks] checkbox)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app at the end of setup.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Messages]
; Post-install note shown on the final wizard page.
FinishedLabel=Setup has installed [name] on your computer.%n%nFIRST RUN: Hinton ships WITHOUT the AI model weights (~12 GB). On first launch it runs in offline "mock" mode. To enable the real local model, run the model download once (see PACKAGING.md / README), then place a SYCL+MTP llama-server.exe on PATH or set OPENLM_LLAMA_SERVER. User data is stored under %LOCALAPPDATA%\OpenLM.

[UninstallDelete]
; Remove anything the app wrote inside its own install folder (logs, caches).
; NOTE: user data lives under %LOCALAPPDATA%\OpenLM and is intentionally left
; in place on uninstall so chats/notebooks survive a reinstall. Delete that
; folder manually for a full wipe.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
