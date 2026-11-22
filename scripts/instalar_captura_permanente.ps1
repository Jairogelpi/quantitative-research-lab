# Registra (o quita, con -Desinstalar) dos tareas programadas de Windows que capturan sin parar desde que el
# usuario inicia sesión: "QuantLab captura REST" (fotos del libro cada segundo) y "QuantLab captura flujo"
# (websocket: cambios del libro y trades). Corren ocultas, sin límite de tiempo, y Windows las reinicia si fallan.
# Ver lo que hacen: data\logs\rest_AAAA-MM-DD.log y data\logs\flujo_AAAA-MM-DD.log.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\instalar_captura_permanente.ps1 [-Desinstalar]
param([switch]$Desinstalar)

$tareas = @{ "QuantLab captura REST" = "rest"; "QuantLab captura flujo" = "flujo" }
$script = Join-Path $PSScriptRoot "captura_permanente.ps1"

foreach ($nombre in $tareas.Keys) {
    if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
        Write-Output "Quitada: $nombre"
    }
    if ($Desinstalar) { continue }
    $accion = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Modo $($tareas[$nombre])"
    $disparador = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $disparador -Settings $ajustes `
        -Description "QuantLab: captura permanente del radar ($($tareas[$nombre])). Quitar con instalar_captura_permanente.ps1 -Desinstalar." | Out-Null
    Start-ScheduledTask -TaskName $nombre
    Write-Output "Registrada y arrancada: $nombre"
}
