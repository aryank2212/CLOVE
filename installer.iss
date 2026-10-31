; Inno Setup script for Clove
[Setup]
AppName=Clove
AppVersion=1.0
DefaultDirName={autopf}\Clove
DefaultGroupName=Clove
OutputDir=Output
OutputBaseFilename=CloveSetup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Components]
Name: "core"; Description: "Clove application (required)"; Types: full compact custom; Flags: fixed
Name: "vcpp"; Description: "Microsoft Visual C++ Redistributable (required for audio/ML)"; Types: full compact custom
Name: "localbrain"; Description: "Local Qwen brain (Ollama) - optional, ~5 GB"; Types: full
Name: "chromeext"; Description: "Chrome extension files (optional)"; Types: full
Name: "autostart"; Description: "Start Clove at login"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Components: core
Name: "startup"; Description: "Start Clove at login"; GroupDescription: "Startup:"; Components: autostart
Name: "firewall"; Description: "Allow Chrome extension bridge (port 8765)"; GroupDescription: "Network:"; Components: core

[Files]
Source: "dist\Clove\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
Source: "chrome_extension\*"; DestDir: "{app}\chrome_extension"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: chromeext

[Icons]
Name: "{group}\Clove"; Filename: "{app}\Clove.exe"; Components: core
Name: "{autodesktop}\Clove"; Filename: "{app}\Clove.exe"; Tasks: desktopicon

[Run]
Filename: "https://aka.ms/vs/17/release/vc_redist.x64.exe"; Description: "Download Visual C++ Redistributable"; Flags: shellexec; Components: vcpp
Filename: "https://ollama.com/download/windows"; Description: "Download Ollama (for local brain)"; Flags: shellexec; Components: localbrain
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Clove Bridge"" dir=in action=allow protocol=TCP localport=8765"; Flags: runhidden; Tasks: firewall
Filename: "{app}\Clove.exe"; Description: "Launch Clove"; Flags: nowait postinstall skipifsilent; Components: core

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Clove"; ValueData: """{app}\Clove.exe"""; Flags: uninsdeletevalue; Tasks: startup

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
