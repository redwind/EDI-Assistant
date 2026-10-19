<#
 Builds the portable zip (primary) and the Inno Setup installer (secondary).
 Usage: pwsh packaging/build_windows.ps1 [-SkipInstaller] [-SkipFull] [-Version 0.1.0]
 Artifacts in dist\: lite zip (Edge), full zip (+ bundled Chromium), installer, SHA256SUMS.txt
#>
param(
    [switch]$SkipInstaller,
    [switch]$SkipFull,
    [string]$Version = ""
)
$ErrorActionPreference = 'Stop'

$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $Root

function Invoke-Checked([scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}

# 1. venv + dependencies
if (-not (Test-Path '.venv')) { Invoke-Checked { python -m venv .venv } }
$Py = Join-Path $Root '.venv\Scripts\python.exe'
Invoke-Checked { & $Py -m pip install --upgrade pip }
Invoke-Checked { & $Py -m pip install -e ".[dev]" }

# 2. version
if (-not $Version) {
    $Version = (& $Py -c "import edi_assistant; print(edi_assistant.__version__)").Trim()
}
Write-Host "Building EDI Assistant $Version"
$Parts = @(($Version -replace '[^0-9.].*$','').Split('.') | ForEach-Object { [int]$_ })
while ($Parts.Count -lt 4) { $Parts += 0 }
$Tuple = ($Parts[0..3] -join ', ')

# 3. version resource
@"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($Tuple), prodvers=($Tuple), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'SHYFT GLOBAL LLC'),
      StringStruct('FileDescription', 'EDI Assistant'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'EDI Assistant.exe'),
      StringStruct('OriginalFilename', 'EDI Assistant.exe'),
      StringStruct('ProductName', 'EDI Assistant'),
      StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot 'version_info.txt')

# 4. PyInstaller
Invoke-Checked { & $Py -m PyInstaller packaging/edi_assistant.spec --clean --noconfirm }

# 5. assert the Playwright driver is bundled (else the frozen app cannot launch a browser)
$Dist = Join-Path $Root 'dist\EDI Assistant'
foreach ($rel in @('_internal\playwright\driver\node.exe', '_internal\playwright\driver\package\cli.js', '_internal\playwright\driver\package\lib')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Dist $rel))) { throw "Missing in build output: $rel" }
}

# 6. portable zips: staged copy so dist\EDI Assistant stays clean for the installer
function New-PortableZip([string]$ZipPath, [string]$BrowsersSrc) {
    $Stage = Join-Path $Root 'dist\portable_stage'
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    New-Item -ItemType Directory -Path $Stage | Out-Null
    $App = Join-Path $Stage 'EDI Assistant'
    Copy-Item -LiteralPath $Dist -Destination $App -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'portable.flag') -Destination (Join-Path $App 'portable.flag')
    Copy-Item -LiteralPath (Join-Path $Root 'README.md') -Destination (Join-Path $App 'README.md')
    Copy-Item -LiteralPath (Join-Path $Root 'README_VI.md') -Destination (Join-Path $App 'README_VI.md')
    Copy-Item -LiteralPath (Join-Path $Root 'README.md') -Destination (Join-Path $Stage 'README.md')
    Copy-Item -LiteralPath (Join-Path $Root 'README_VI.md') -Destination (Join-Path $Stage 'README_VI.md')
    if ($BrowsersSrc) { Copy-Item -LiteralPath $BrowsersSrc -Destination (Join-Path $App 'browsers') -Recurse }
    if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    Compress-Archive -LiteralPath (Get-ChildItem -LiteralPath $Stage | ForEach-Object FullName) -DestinationPath $ZipPath
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
$Zip = Join-Path $Root "dist\EDI-Assistant-portable-$Version.zip"
New-PortableZip $Zip $null

# 6b. "full" zip: same build + Playwright Chromium in <app>\browsers (no Edge automation, no runtime download)
$ZipFull = $null
if (-not $SkipFull) {
    $BrowsersStage = Join-Path $Root 'dist\browsers_stage'
    if (Test-Path -LiteralPath $BrowsersStage) { Remove-Item -LiteralPath $BrowsersStage -Recurse -Force }
    New-Item -ItemType Directory -Path $BrowsersStage | Out-Null
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersStage
    Invoke-Checked { & $Py -m playwright install chromium }
    Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH
    # ffmpeg is only needed for video recording, which the app never uses
    Get-ChildItem -LiteralPath $BrowsersStage -Directory -Filter 'ffmpeg*' | Remove-Item -Recurse -Force
    if (-not (Get-ChildItem -LiteralPath $BrowsersStage -Directory -Filter 'chromium*')) { throw 'Playwright Chromium was not installed into the staging folder' }
    $ZipFull = Join-Path $Root "dist\EDI-Assistant-portable-full-$Version.zip"
    New-PortableZip $ZipFull $BrowsersStage
    Remove-Item -LiteralPath $BrowsersStage -Recurse -Force
}

# 7. installer
$Setup = $null
if (-not $SkipInstaller) {
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $cand = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($cand) { $iscc = Get-Item $cand }
    }
    if ($iscc) {
        $IssPath = if ($iscc.Source) { $iscc.Source } else { $iscc.FullName }
        Invoke-Checked { & $IssPath "/DMyAppVersion=$Version" (Join-Path $Root 'installer\edi_assistant.iss') }
        $Setup = Join-Path $Root "dist\EDI-Assistant-Setup-$Version.exe"
    } else {
        Write-Warning 'iscc.exe not found; installer skipped.'
    }
}

# 8. SHA256SUMS.txt (give the hashes to IT if AppLocker / antivirus asks)
$Artifacts = @($Zip, $ZipFull, $Setup) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$Sums = $Artifacts | ForEach-Object { $h = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLower(); "$h  $(Split-Path $_ -Leaf)" }
# also the hash of the exe itself (what AppLocker publisher/hash rules see)
$Exe = Join-Path $Dist 'EDI Assistant.exe'
$Sums += "$((Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLower())  EDI Assistant.exe (inside the zips/installer)"
$Sums | Set-Content -Encoding ASCII (Join-Path $Root 'dist\SHA256SUMS.txt')

Write-Host ''
Write-Host "Portable zip (lite, Edge):   $Zip"
if ($ZipFull) { Write-Host "Portable zip (full):         $ZipFull" }
if ($Setup) { Write-Host "Installer:                   $Setup" }
Write-Host "Checksums:                   $(Join-Path $Root 'dist\SHA256SUMS.txt')"
$Sums | ForEach-Object { Write-Host $_ }
