# Installs the local brain for Clove on Windows: Ollama + qwen3:8b (or LOCAL_MODEL).
$ErrorActionPreference = "Stop"
$Model = if ($env:LOCAL_MODEL) { $env:LOCAL_MODEL } else { "qwen3:8b" }

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "==> installing Ollama via winget"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "Install Ollama manually from https://ollama.com/download/windows" -ForegroundColor Red
        exit 1
    }
}
# ensure service running
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Host "==> pulling $Model"
& ollama pull $Model
Write-Host "==> DONE (Whisper and Kokoro download on first use)"
