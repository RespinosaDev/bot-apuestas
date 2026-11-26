# Ejecuta una consulta del bot (`once`) para la prueba de disponibilidad.
# Lo lanza el Programador de tareas de Windows (ver scripts/programar_prueba.ps1).
# Deja el resultado en data/logs/prueba_programada.log y nunca pasa de
# $MaxPorDia ejecuciones en el mismo día (por si Windows recupera ejecuciones
# perdidas al encender el PC).
param(
    [int]$MaxPorDia = 4
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$logDir = Join-Path $repo 'data\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'prueba_programada.log'
$hoy = Get-Date -Format 'yyyy-MM-dd'

function Write-Log([string]$texto) {
    Add-Content -Path $log -Value $texto -Encoding UTF8
}

$hechas = 0
if (Test-Path $log) {
    $hechas = @(Select-String -Path $log -Pattern "^=== $hoy .* once ===" -Encoding UTF8).Count
}
if ($hechas -ge $MaxPorDia) {
    Write-Log "--- $(Get-Date -Format 'yyyy-MM-dd HH:mm') omitida: ya van $hechas ejecuciones hoy (máximo $MaxPorDia)"
    exit 0
}

Write-Log "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm') once ==="
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$salida = & $python -m bot_apuestas once 2>&1 | ForEach-Object { "$_" }
$codigo = $LASTEXITCODE
if ($salida) { Write-Log ($salida -join [Environment]::NewLine) }
Write-Log "(código de salida: $codigo)"
exit $codigo
