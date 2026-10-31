# Build Clove.exe and the installer on Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\pip install -r requirements.txt pyinstaller

# Optional icon
if (-not (Test-Path ui\clove.ico)) { Write-Host "No ui\\clove.ico; building without icon" }

.\.venv\Scripts\pyinstaller --clean --noconfirm Clove.spec
Write-Host "Built dist\\Clove\\Clove.exe"

# Build installer if Inno Setup is available
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc installer.iss
    Write-Host "Installer built in Output\\"
} else {
    Write-Host "Inno Setup not found; skipping installer. Install from https://jrsoftware.org/isinfo.php"
}
