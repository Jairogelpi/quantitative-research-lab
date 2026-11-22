# Corre una captura del radar sin parar, en tramos de una hora. Si un tramo falla, espera 30 s y empieza otro.
# Los tramos cortos limitan lo que se pierde si se cae la PC: como mucho el último lote sin volcar.
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
$comando = if ($Modo -eq "rest") { "capturar" } else { "flujo" }
$env:PYTHONIOENCODING = "utf-8"

while ($true) {
    $log = Join-Path $logs ("{0}_{1:yyyy-MM-dd}.log" -f $Modo, (Get-Date).ToUniversalTime())
    "{0:o} inicio del tramo de {1} s" -f (Get-Date).ToUniversalTime(), $Segundos | Out-File -Append -Encoding utf8 $log
    Push-Location $proyecto
    & $Python -m radar $comando $Segundos 2>&1 | Out-File -Append -Encoding utf8 $log
    $codigo = $LASTEXITCODE
    Pop-Location
    "{0:o} fin del tramo, código {1}" -f (Get-Date).ToUniversalTime(), $codigo | Out-File -Append -Encoding utf8 $log
    if ($codigo -ne 0) { Start-Sleep -Seconds 30 }
}
