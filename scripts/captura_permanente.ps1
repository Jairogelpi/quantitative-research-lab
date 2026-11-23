# Servicio de captura: REST por tramos; WebSocket continuo para evitar huecos de reconexion.
# Si el proceso sale con error, espera 30 s antes de reiniciar.
# Nota: si el PC se apaga puede perderse el lote en memoria; esto NO es persistencia garantizada.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\captura_permanente.ps1 -Modo rest|flujo
param(
    [Parameter(Mandatory = $true)][ValidateSet("rest", "flujo")][string]$Modo,
    [string]$Python = "C:\Python313\python.exe",
    [int]$Segundos = 3600
)

$raiz = Split-Path -Parent $PSScriptRoot
$proyecto = Join-Path $raiz "proyecto"
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$argumentos = if ($Modo -eq "rest") { @("capturar", "$Segundos") } else { @("flujo", "--continuo") }
$env:PYTHONIOENCODING = "utf-8"

while ($true) {
    $log = Join-Path $logs ("{0}_{1:yyyy-MM-dd}.log" -f $Modo, (Get-Date).ToUniversalTime())
    "{0:o} inicio {1}" -f (Get-Date).ToUniversalTime(), ($argumentos -join " ") | Out-File -Append -Encoding utf8 $log
    Push-Location $proyecto
    & $Python -m radar @argumentos 2>&1 | Out-File -Append -Encoding utf8 $log
    $codigo = $LASTEXITCODE
    Pop-Location
    "{0:o} fin del tramo, código {1}" -f (Get-Date).ToUniversalTime(), $codigo | Out-File -Append -Encoding utf8 $log
    if ($codigo -ne 0) { Start-Sleep -Seconds 30 }
}
