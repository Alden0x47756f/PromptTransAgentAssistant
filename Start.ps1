param([switch]$Expanded)
$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$executablePath = Join-Path $projectPath 'PromptTransAgentAssistant.exe'
$pythonPath = Join-Path $projectPath '.venv\Scripts\pythonw.exe'
if ((Test-Path -LiteralPath $executablePath)) {
    $appArguments = @()
    if ($Expanded) { $appArguments += '--expanded' }
    if ($appArguments.Count) {
        Start-Process -FilePath $executablePath -ArgumentList $appArguments -WorkingDirectory $projectPath -WindowStyle Hidden
    } else {
        Start-Process -FilePath $executablePath -WorkingDirectory $projectPath -WindowStyle Hidden
    }
    exit 0
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'Run Setup.cmd first to install local dependencies.' -ForegroundColor Yellow
    exit 1
}
$appArguments = @('main.py')
if ($Expanded) { $appArguments += '--expanded' }
Start-Process -FilePath $pythonPath -ArgumentList $appArguments -WorkingDirectory $projectPath -WindowStyle Hidden
