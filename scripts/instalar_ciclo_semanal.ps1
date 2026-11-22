# Registra (o quita, con -Desinstalar) la tarea programada "QuantLab ciclo semanal": cada lunes a las 06:00
# (hora local) corre scripts\ciclo_semanal.ps1. Si la PC estaba apagada, corre en cuanto se pueda.
# Ver lo que hizo: data\logs\ciclo_AAAA-MM-DD.log.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\instalar_ciclo_semanal.ps1 [-Desinstalar] [-Ahora]
param([switch]$Desinstalar, [switch]$Ahora)

$nombre = "QuantLab ciclo semanal"
$script = Join-Path $PSScriptRoot "ciclo_semanal.ps1"

if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
    Write-Output "Quitada: $nombre"
}
if ($Desinstalar) { exit 0 }

$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$disparador = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 6am
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $disparador -Settings $ajustes `
    -Description "QuantLab: revalidar, estudios, registro y robustez del radar. Quitar con instalar_ciclo_semanal.ps1 -Desinstalar." | Out-Null
Write-Output "Registrada: $nombre (lunes 06:00)"
if ($Ahora) {
    Start-ScheduledTask -TaskName $nombre
    Write-Output "Arrancada ahora: $nombre"
}
