# Install Turnpike Deck for the current user.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1            # install what is built
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Build     # cargo build first
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall # remove app + shortcuts
#
# Installs to %LOCALAPPDATA%\Programs\Turnpike so the app survives `cargo clean`,
# then registers Start Menu + Desktop shortcuts (Start Menu entry makes it
# searchable: press Start, type "turnpike").

param(
    [switch]$Build,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$Repo      = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcExe    = Join-Path $Repo 'deck\src-tauri\target\release\turnpike-deck.exe'
$SrcIcon   = Join-Path $Repo 'deck\src-tauri\icons\icon.ico'
$InstallDir= Join-Path $env:LOCALAPPDATA 'Programs\Turnpike'
$DestExe   = Join-Path $InstallDir 'Turnpike.exe'
$DestIcon  = Join-Path $InstallDir 'turnpike.ico'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Turnpike.lnk'
$DesktopLnk= Join-Path ([Environment]::GetFolderPath('Desktop')) 'Turnpike.lnk'
$LegacyLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Turnpike Deck.lnk'

function Stop-Running {
    Get-Process -Name 'Turnpike', 'turnpike-deck' -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  stopping running instance (pid $($_.Id))"
        $_.CloseMainWindow() | Out-Null
        Start-Sleep -Milliseconds 800
        if (-not $_.HasExited) { $_ | Stop-Process -Force }
    }
    Start-Sleep -Milliseconds 400
}

function New-Shortcut($Path, $Target, $Icon, $WorkDir, $Desc) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($Path)
    $lnk.TargetPath       = $Target
    $lnk.WorkingDirectory = $WorkDir
    $lnk.IconLocation     = $Icon
    $lnk.Description      = $Desc
    $lnk.Save()
}

if ($Uninstall) {
    Write-Host 'Uninstalling Turnpike Deck...'
    Stop-Running
    foreach ($p in @($StartMenu, $DesktopLnk, $LegacyLnk)) {
        if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  removed $p" }
    }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Host "  removed $InstallDir" }
    Write-Host 'Done. (The turnpike repo and your ~/.turnpike database were not touched.)'
    return
}

if ($Build) {
    Write-Host 'Building release binary...'
    Push-Location (Join-Path $Repo 'deck\src-tauri')
    try { cargo build --release; if ($LASTEXITCODE -ne 0) { throw "cargo build failed ($LASTEXITCODE)" } }
    finally { Pop-Location }
}

if (-not (Test-Path $SrcExe)) {
    throw "No built exe at $SrcExe. Re-run with -Build."
}

Write-Host 'Installing Turnpike Deck...'
Stop-Running
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item $SrcExe  $DestExe  -Force
Copy-Item $SrcIcon $DestIcon -Force
# Tell the installed exe which checkout to supervise (read by deck's turnpike_dir()).
Set-Content -Path (Join-Path $InstallDir 'turnpike.dir') -Value $Repo -Encoding ascii -NoNewline
Write-Host "  installed $DestExe (supervising $Repo)"

New-Shortcut $StartMenu $DestExe $DestIcon $InstallDir 'Turnpike: multi-agent project bus and monitor'
Write-Host "  Start Menu entry: $StartMenu"

if (Test-Path $LegacyLnk) { Remove-Item $LegacyLnk -Force }
New-Shortcut $DesktopLnk $DestExe $DestIcon $InstallDir 'Turnpike: multi-agent project bus and monitor'
Write-Host "  Desktop shortcut: $DesktopLnk"

# Nudge Explorer to refresh its icon cache so the new icon shows immediately.
try { & ie4uinit.exe -show } catch { }

Write-Host ''
Write-Host 'Done. Press Start and type "turnpike" to launch it.'
