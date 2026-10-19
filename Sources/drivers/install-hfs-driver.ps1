$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'iPod Drop - Paragon HFS+ trial'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList ('-NoExit -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
    exit
}

$trialUrl = 'https://dl.paragon-software.com/demo/hfs14_win_trial.msi'
$expectedHash = 'B229A05DAC3E49E36E86ECF8E7C5C4926E5D8ECC76505162EACCE86642E4D3BD'
$msi = Join-Path $env:TEMP 'hfs14_win_trial.msi'
$page = 'https://www.paragon-software.com/home/hfs-windows/'

Write-Host ''
Write-Host 'iPod Drop - Paragon HFS+ trial setup' -ForegroundColor Cyan
Write-Host ''
Write-Host 'This iPod is formatted as HFS+ (Mac OS Extended).' -ForegroundColor Yellow
Write-Host 'Windows cannot read or write HFS+ without a third-party driver.'
Write-Host ''
Write-Host 'This helper downloads the official Paragon HFS+ 10-day trial.'
Write-Host 'The winget/full build may ask for a license immediately; the trial MSI does not.'
Write-Host ''
Write-Host 'If Paragon HFS+ is already installed and asking for activation, uninstall it'
Write-Host 'in Settings > Apps first, then run this helper again.'
Write-Host 'Disconnect the iPod before installing, then reboot Windows after setup.'
Write-Host ''

$existing = @(
    Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue
    Get-ItemProperty 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue
) | Where-Object { $_.DisplayName -match 'Paragon.*HFS' } | Select-Object -First 1
if ($existing) {
    Write-Host ('Existing installation found: ' + $existing.DisplayName) -ForegroundColor Yellow
    Write-Host 'If it is the full build asking for a key, uninstall it before continuing.'
    Write-Host 'Opening Settings > Apps so you can remove it if needed.'
    try { Start-Process 'ms-settings:appsfeatures' } catch {}
    Write-Host ''
}

$answer = Read-Host 'Download and install the official 10-day trial now? Type Y to continue'
if ($answer -notmatch '^[Yy]') {
    Write-Host 'Cancelled. Nothing was installed.'
    Read-Host 'Press Enter to close this window'
    exit 0
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host ''
    Write-Host 'Downloading the official Paragon trial...' -ForegroundColor Cyan
    Invoke-WebRequest -Uri $trialUrl -OutFile $msi -UseBasicParsing -TimeoutSec 180
} catch {
    Write-Host ''
    Write-Host 'Could not download the trial installer.' -ForegroundColor Yellow
    Write-Host 'Opening the official Paragon download page instead.'
    Start-Process $page
    Read-Host 'Press Enter to close this window'
    exit 1
}

$actualHash = (Get-FileHash -Algorithm SHA256 $msi).Hash
if ($actualHash -ne $expectedHash) {
    Write-Host ''
    Write-Host 'The downloaded file did not match the expected SHA-256.' -ForegroundColor Red
    Write-Host 'Nothing was installed. Opening the official Paragon page instead.'
    Start-Process $page
    Read-Host 'Press Enter to close this window'
    exit 1
}

Write-Host 'Installing Paragon HFS+ trial...' -ForegroundColor Cyan
$process = Start-Process msiexec.exe -ArgumentList @('/i', ('"' + $msi + '"'), '/passive', '/norestart') -Wait -PassThru
Write-Host ''
if ($process.ExitCode -in @(0,3010)) {
    Write-Host 'The trial installer finished.' -ForegroundColor Green
    Write-Host 'Restart Windows, reconnect the iPod, then click "重新检测" in iPod Drop.'
} else {
    Write-Host ('The installer returned exit code ' + $process.ExitCode + '.') -ForegroundColor Yellow
    Write-Host 'If it reported an existing version, uninstall Paragon HFS+ in Settings > Apps and retry.'
    Write-Host ('Manual download: ' + $page)
}
Write-Host ''
Write-Host 'Tip: Paragon recommends disabling Windows Fast Startup before using its HFS+ driver.'
Read-Host 'Press Enter to close this window'
