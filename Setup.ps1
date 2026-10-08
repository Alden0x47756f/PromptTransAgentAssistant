$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$venvPath = Join-Path $projectPath '.venv'
$pythonPath = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv --python 3.11 $venvPath
    } else {
        & python -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python $pythonPath -r (Join-Path $projectPath 'requirements.txt')
} else {
    & $pythonPath -m pip install -r (Join-Path $projectPath 'requirements.txt')
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Double-click Start.cmd to launch.' -ForegroundColor Green
