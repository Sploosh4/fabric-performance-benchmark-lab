#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$GameProcessId,
    [ValidateRange(1, 3600)]
    [int]$DurationSeconds = 120,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$RunName,
    [Parameter(Mandatory = $true)]
    [string]$ProfileDirectory,
    [string]$PythonExecutable = "python"
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
$labStarted = $labGame.StartTime.ToUniversalTime().ToString('o')
$labProcess = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $GameProcessId)
# Read command arguments only in memory. Never emit or save authentication arguments.
$labGameDirMatch = [regex]::Match($labProcess.CommandLine, '--gameDir\s+(?:"([^"]+)"|(\S+))')
if (-not $labGameDirMatch.Success) { throw 'The process has no verifiable Minecraft game directory.' }
$labActualDirectory = [IO.Path]::GetFullPath($labGameDirMatch.Groups[1].Value + $labGameDirMatch.Groups[2].Value)
$labExpectedDirectory = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProfileDirectory).Path)
if ($labActualDirectory.TrimEnd('\') -ine $labExpectedDirectory.TrimEnd('\')) {
    throw 'The selected process belongs to a different game directory.'
}
if ($labProcess.CommandLine -notmatch 'net\.minecraft\.client\.main\.Main|net\.fabricmc\.loader\.impl\.launch\.knot\.KnotClient') {
    throw 'The process does not identify a supported Minecraft client entry point.'
}
if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'Configured validation Python is unavailable.' }
$labResultDir = Join-Path $labRoot 'raw-results'
New-Item -ItemType Directory -Path $labResultDir -Force | Out-Null
$labCsv = Join-Path $labResultDir ($RunName + '.csv')
if (Test-Path -LiteralPath $labCsv) {
    throw 'A capture with this run name already exists. Use a unique run name.'
}
$labSessionName = 'Modpack_' + [guid]::NewGuid().ToString('N')
$labArguments = @('--process_id', $GameProcessId, '--timed', $DurationSeconds,
    '--terminate_after_timed', '--terminate_on_proc_exit', '--v1_metrics',
    '--output_file', ('"' + $labCsv + '"'), '--no_console_stats', '--session_name', $labSessionName)
$labCapture = Start-Process -FilePath $labPresentMon -ArgumentList $labArguments -WindowStyle Hidden -PassThru
if (-not $labCapture.WaitForExit(($DurationSeconds + 30) * 1000)) {
    Stop-Process -Id $labCapture.Id -ErrorAction SilentlyContinue
    # Touch only this invocation's uniquely named ETW session.
    $labCleanup = Start-Process -FilePath $labPresentMon -ArgumentList @('--terminate_existing_session', '--session_name', $labSessionName) -WindowStyle Hidden -PassThru
    if (-not $labCleanup.WaitForExit(10000)) { Stop-Process -Id $labCleanup.Id -ErrorAction SilentlyContinue }
    throw 'Capture exceeded its bounded deadline; this run is rejected.'
}
if ($labCapture.ExitCode -ne 0) {
    throw ('PresentMon capture failed with exit code ' + $labCapture.ExitCode)
}
if (-not (Test-Path -LiteralPath $labCsv)) {
    throw 'PresentMon exited without creating its CSV.'
}
$labGameAfter = Get-Process -Id $GameProcessId -ErrorAction Stop
if ($labGameAfter.StartTime.ToUniversalTime().ToString('o') -ne $labStarted) {
    throw 'Game process lifetime changed during capture; this run is rejected.'
}
$labIdentity = [ordered]@{ process_id=$GameProcessId; process_start_utc=$labStarted;
    process_lifetime_verified=$true; profile_directory_verified=$true;
    minecraft_entry_point_verified=$true; world_scenario_verified=$false;
    foreground_verified=$false; benchmark_accepted=$false }
$labIdentity | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $labResultDir ($RunName + '.identity.json')) -Encoding utf8
& $PythonExecutable (Join-Path $PSScriptRoot 'validate_capture.py') $labCsv --pid $GameProcessId --application ($labGame.ProcessName + '.exe') --duration $DurationSeconds --report (Join-Path $labResultDir ($RunName + '.quality.json'))
if ($LASTEXITCODE -ne 0) { throw 'CSV quality checks rejected this capture.' }
Write-Output $labCsv
Write-Output 'Capture quality checked; benchmark acceptance still requires world/scenario, foreground and calibration evidence.'
