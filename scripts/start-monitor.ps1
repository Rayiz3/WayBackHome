$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw '먼저 python -m venv .venv 및 .venv/Scripts/python.exe -m pip install -r server/requirements.txt 를 실행해 주세요.'
}
& $pythonExecutable -m server.run
