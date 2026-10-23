; Tonefer for Windows — Inno Setup script (built by CI: iscc /DAppVersion=x.y.z tonefer.iss)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0F7C1E-3A52-4E7B-9C3D-2F1A9E5B7D41}
AppName=Tonefer
AppVersion={#AppVersion}
AppVerName=Tonefer {#AppVersion}
AppPublisher=Pank
AppPublisherURL=https://github.com/pankqx/tonefer
DefaultDirName={autopf}\Tonefer
DefaultGroupName=Tonefer
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=ToneferSetup
SetupIconFile=..\..\build\tonefer.ico
UninstallDisplayIcon={app}\Tonefer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Tasks]
Name: "startup"; Description: "Start Tonefer when I sign in (keeps receiving in the background)"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\Tonefer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Tonefer"; Filename: "{app}\Tonefer.exe"
Name: "{group}\Tonefer (open in browser)"; Filename: "http://127.0.0.1:8765/desk"
Name: "{autodesktop}\Tonefer"; Filename: "{app}\Tonefer.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Tonefer"; ValueData: """{app}\Tonefer.exe"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
; Let the phone reach this PC on the hotspot (Windows often marks hotspots as Public networks).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Tonefer"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Tonefer"" dir=in action=allow program=""{app}\Tonefer.exe"" enable=yes profile=private,public"; Flags: runhidden
Filename: "{app}\Tonefer.exe"; Description: "Open Tonefer now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Tonefer.exe /F"; Flags: runhidden; RunOnceId: "StopTonefer"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Tonefer"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
