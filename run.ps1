param([string[]]$Args)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
  python -m venv .venv
  .\.venv\Scripts\pip install -r requirements.txt
}
& .\.venv\Scripts\python.exe agent.py @Args
