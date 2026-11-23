# Instala o desinstala el ciclo diario a las 03:00, hora local de Windows.
# No se ejecuta automáticamente al clonar el repositorio.
param([switch]$Desinstalar, [switch]$Ahora)

$nombre = "QuantLab ciclo diario"
$script = Join-Path $PSScriptRoot "ciclo_diario.ps1"

if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
    Write-Output "Quitada: $nombre"
}
if ($Desinstalar) { exit 0 }

$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$disparador = New-ScheduledTaskTrigger -Daily -At 3am
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $disparador -Settings $ajustes `
    -Description "QuantLab: descargar históricos y verificar salud de la captura cada día." | Out-Null
Write-Output "Registrada: $nombre (03:00 hora local)"
if ($Ahora) {
    Start-ScheduledTask -TaskName $nombre
    Write-Output "Arrancada ahora"
}
