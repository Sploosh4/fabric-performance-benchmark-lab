#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$GameProcessId,
    [ValidateRange(1, 3600)]
    [int]$DurationSeconds = 120,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$RunName
)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$labPresentMon = Join-Path $env:ProgramFiles 'Intel\PresentMon\PresentMonConsoleApplication\PresentMon-2.6.0-x64.exe'
if (-not (Test-Path -LiteralPath $labPresentMon)) {
    throw 'The verified PresentMon 2.6.0 CLI is not installed at the expected path.'
}
$labGame = Get-Process -Id $GameProcessId
if ($labGame.ProcessName -notin @('java', 'javaw')) {
    throw 'The selected PID is not a Java process. Select the Minecraft game PID.'
}
$labResultDir = Join-Path $labRoot 'raw-results'
New-Item -ItemType Directory -Path $labResultDir -Force | Out-Null
$labCsv = Join-Path $labResultDir ($RunName + '.csv')
if (Test-Path -LiteralPath $labCsv) {
    throw 'A capture with this run name already exists. Use a unique run name.'
}
$labSessionName = 'Modpack_' + [guid]::NewGuid().ToString('N')
& $labPresentMon --process_id $GameProcessId --timed $DurationSeconds --terminate_after_timed --output_file $labCsv --no_console_stats --session_name $labSessionName
if ($LASTEXITCODE -ne 0) {
    throw ('PresentMon capture failed with exit code ' + $LASTEXITCODE)
}
if (-not (Test-Path -LiteralPath $labCsv)) {
    throw 'PresentMon exited without creating its CSV.'
}
Write-Output $labCsv
