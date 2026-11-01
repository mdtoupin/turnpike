[CmdletBinding()]
param(
    [string] $Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Turnpike\cli'),
    [string] $PythonExecutable = ''
)
$ErrorActionPreference = 'Stop'
if (-not $PythonExecutable) {
    $PythonExecutable = (& python -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Python executable' }
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'Python executable does not exist' }
foreach ($turnpikePathValue in @($Destination, $PythonExecutable)) {
    if ($turnpikePathValue -match '[^\x20-\x7e]|[%!"&|<>^]') {
        throw 'The SSH launcher currently requires ASCII paths without command metacharacters; choose an explicit supported destination and Python executable.'
    }
}
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
foreach ($turnpikeFile in @('turnpike.py', 'turnpike_rpc.py', 'turnpike_notes.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $turnpikeFile) -Destination (Join-Path $Destination $turnpikeFile) -Force
}
New-Item -ItemType Directory -Path (Join-Path $Destination 'tools') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'tools\probe_providers.py') -Destination (Join-Path $Destination 'tools\probe_providers.py') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'tools\turnpike_remote.py') -Destination (Join-Path $Destination 'turnpike_remote.py') -Force
$turnpikeScript = Join-Path $Destination 'turnpike.py'
$turnpikeLauncher = "@echo off`r`n`"$PythonExecutable`" -X utf8 `"$turnpikeScript`" rpc --as `"%~1`"`r`nexit /b %errorlevel%`r`n"
[IO.File]::WriteAllText((Join-Path $Destination 'turnpike-ssh.cmd'), $turnpikeLauncher, [Text.Encoding]::ASCII)
[pscustomobject]@{
    Destination = $Destination
    PythonExecutable = $PythonExecutable
    Entrypoint = (Join-Path $Destination 'turnpike-ssh.cmd')
    ChangesSshConfiguration = $false
    ChangesDatabaseLocation = $false
} | ConvertTo-Json
