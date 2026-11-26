# Programa la prueba de disponibilidad en el Programador de tareas de Windows:
# ejecuta `python -m bot_apuestas once` cada 3 horas entre las 12:00 y las 21:00
# (4 veces al día: 12, 15, 18 y 21 h) en los días indicados.
#
# Uso (desde la raíz del repo):
#   powershell -ExecutionPolicy Bypass -File scripts\programar_prueba.ps1 -Desde 2026-11-26 -Hasta 2026-11-27
#   powershell -ExecutionPolicy Bypass -File scripts\programar_prueba.ps1 -Quitar
#
# Cada ejecución gasta 6 peticiones de OddsPapi (4 si BOT_SUREBET_BOOKS está vacío).
# El PC tiene que estar encendido y con la sesión iniciada. Si está apagado o
# suspendido a la hora, la ejecución se hace al volver (máximo 4 al día).
param(
    [datetime]$Desde,
    [datetime]$Hasta,
    [int[]]$Horas = @(12, 15, 18, 21),
    [string]$Nombre = 'bot-apuestas prueba',
    [switch]$Quitar
)

$ErrorActionPreference = 'Stop'

if ($Quitar) {
    Unregister-ScheduledTask -TaskName $Nombre -Confirm:$false
    Write-Output "Tarea '$Nombre' eliminada."
    exit 0
}
if (-not $Desde -or -not $Hasta) { throw 'Indica -Desde y -Hasta (por ejemplo -Desde 2026-11-26 -Hasta 2026-11-27).' }
if ($Horas.Count -gt 4) { throw 'Máximo 4 ejecuciones al día.' }

$wrapper = Join-Path $PSScriptRoot 'prueba_once.ps1'
$repo = Split-Path -Parent $PSScriptRoot

$triggers = @()
$momentos = @()
for ($dia = $Desde.Date; $dia -le $Hasta.Date; $dia = $dia.AddDays(1)) {
    foreach ($h in $Horas) {
        $momento = $dia.AddHours($h)
        if ($momento -gt (Get-Date)) {
            $triggers += New-ScheduledTaskTrigger -Once -At $momento
            $momentos += $momento
        }
    }
}
if ($triggers.Count -eq 0) { throw 'No hay ninguna hora futura en ese intervalo.' }

$accion = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`"" `
    -WorkingDirectory $repo
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $triggers -Settings $ajustes `
    -Description 'Prueba de disponibilidad: python -m bot_apuestas once (scripts/prueba_once.ps1)' `
    -Force | Out-Null

Write-Output "Tarea '$Nombre' programada ($($momentos.Count) ejecuciones, $($momentos.Count * 6) peticiones como máximo):"
$momentos | ForEach-Object { Write-Output ('  ' + $_.ToString('ddd dd/MM HH:mm')) }
Write-Output 'Registro: data\logs\prueba_programada.log'
