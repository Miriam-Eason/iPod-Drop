$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSCommandPath
$runtime = Join-Path $root 'runtime32'
$exe = Join-Path $runtime 'python.exe'

function Test-Python32([string]$path) {
    if (-not (Test-Path $path)) { return $false }
    try {
        $bytes = [IO.File]::ReadAllBytes($path)
        if ($bytes.Length -lt 0x40) { return $false }
        $pe = [BitConverter]::ToInt32($bytes, 0x3c)
        if ($pe -lt 0 -or $pe + 6 -ge $bytes.Length) { return $false }
        return ([BitConverter]::ToUInt16($bytes, $pe + 4) -eq 0x014c)
    } catch { return $false }
}

if (Test-Python32 $exe) { exit 0 }

Write-Host ''
Write-Host 'iPod Drop - 32-bit runtime setup' -ForegroundColor Cyan
Write-Host ''
Write-Host 'This 32-bit package needs the official 32-bit Python 3.13 runtime.'
Write-Host 'It will be downloaded once from python.org and stored in:'
Write-Host "  $runtime"
Write-Host ''

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

$versions = @(
    '3.13.13','3.13.12','3.13.11','3.13.10','3.13.9','3.13.8','3.13.7',
    '3.12.11','3.12.10','3.12.9','3.12.8','3.12.7'
)
$zip = Join-Path $env:TEMP 'ipod-drop-python-embed-win32.zip'
$found = $false
foreach ($version in $versions) {
    $url = "https://www.python.org/ftp/python/$version/python-$version-embed-win32.zip"
    try {
        Write-Host "Trying $url" -ForegroundColor DarkGray
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 90
        $found = $true
        break
    } catch {
        Write-Host "Version $version is not available." -ForegroundColor DarkYellow
    }
}

if (-not $found) {
    Write-Host ''
    Write-Host 'Could not download the 32-bit runtime.' -ForegroundColor Yellow
    Write-Host 'Install the official "Windows installer (32-bit)" from:'
    Write-Host 'https://www.python.org/downloads/windows/'
    Start-Process 'https://www.python.org/downloads/windows/'
    Read-Host 'Press Enter to close this window'
    exit 1
}

$temp = Join-Path $env:TEMP ('ipod-drop-runtime32-' + [guid]::NewGuid().ToString('N'))
Expand-Archive -Path $zip -DestinationPath $temp -Force

if (-not (Test-Python32 (Join-Path $temp 'python.exe'))) {
    throw 'The downloaded Python runtime is not 32-bit. Nothing was installed.'
}

if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
Move-Item $temp $runtime

$pth = Get-ChildItem $runtime -Filter 'python*._pth' | Select-Object -First 1
if (-not $pth) { throw 'The Python ._pth file is missing from the downloaded runtime.' }
$zipName = [IO.Path]::GetFileNameWithoutExtension($pth.Name) + '.zip'
Set-Content -Path $pth.FullName -Value @(
    $zipName,
    '.',
    '../app',
    '../app/vendor'
) -Encoding ASCII

Write-Host ''
& $exe -c "import sys; print(sys.version); raise SystemExit(0 if sys.maxsize < 2**32 else 1)"
if ($LASTEXITCODE -ne 0) { throw 'The 32-bit Python self-check failed.' }

Write-Host ''
Write-Host 'The 32-bit runtime is ready. Start iPod Drop again.' -ForegroundColor Green
Read-Host 'Press Enter to close this window'
exit 0
