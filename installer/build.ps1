<#
  Builds dist\Xotira-Setup-<version>.exe and dist\SHA256SUMS.txt.

  1. Downloads the official embeddable Python from python.org and refuses to continue unless
     python.exe / pythonw.exe carry a valid Authenticode signature from the Python Software Foundation.
  2. Stages Xotira's readable source next to it (no packers, no compiled bootloaders).
  3. Compiles the per-user Inno Setup installer and writes SHA-256 checksums.

  Usage:  powershell -ExecutionPolicy Bypass -File installer\build.ps1 [-Version 1.0.0] [-PythonVersion 3.14.5]
#>
param(
    [string]$Version = '',
    [string]$PythonVersion = '3.14.5',
    [string]$RepoUrl = 'https://github.com/humoyun200108/xotira'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Version) {
    $Version = (Select-String -Path "$Root\app\server.py" -Pattern "APP_VERSION = '([^']+)'").Matches[0].Groups[1].Value
}
$Build = Join-Path $Root 'build'
$Stage = Join-Path $Build 'stage'
$Cache = Join-Path $Build 'cache'
$Dist = Join-Path $Root 'dist'
Write-Host "Xotira $Version  (Python $PythonVersion)"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage, $Cache, $Dist | Out-Null

# ---- 1. official, signed Python runtime
$zip = Join-Path $Cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip -UseBasicParsing
}
Expand-Archive $zip (Join-Path $Stage 'runtime') -Force
foreach ($exe in 'python.exe', 'pythonw.exe') {
    $sig = Get-AuthenticodeSignature (Join-Path $Stage "runtime\$exe")
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Python Software Foundation') {
        throw "$exe is not signed by the Python Software Foundation ($($sig.Status)) - refusing to build."
    }
}
Write-Host "  runtime ok: signed by Python Software Foundation"

# ---- 2. Xotira source (demo files are only for the website)
$app = Join-Path $Stage 'app'
New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item "$Root\app\server.py", "$Root\app\launcher.pyw", "$Root\app\index.html" $app
Copy-Item "$Root\app\assets" $app -Recurse
Copy-Item "$Root\LICENSE" $Stage

# ---- 3. installer
$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php' }
& $iscc /Q "/DAppVersion=$Version" "/DRepoUrl=$RepoUrl" (Join-Path $PSScriptRoot 'xotira.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }

# ---- 4. checksums
$setup = Join-Path $Dist "Xotira-Setup-$Version.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $setup -Leaf)" | Set-Content (Join-Path $Dist 'SHA256SUMS.txt') -Encoding ascii
Write-Host "  built: $setup"
Write-Host "  sha256: $hash"
