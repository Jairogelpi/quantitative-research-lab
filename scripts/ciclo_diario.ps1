# Ciclo diario de mantenimiento de QuantLab: cada comando se registra y los errores no
# impiden ejecutar el resto. Ejecutar desde Windows Task Scheduler o manualmente.
param([string]$Python = "python", [switch]$Prueba)

$raiz = Split-Path -Parent $PSScriptRoot
$proyecto = Join-Path $raiz "proyecto"
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs ("diario_{0:yyyy-MM-dd}.log" -f (Get-Date).ToUniversalTime())
$env:PYTHONIOENCODING = "utf-8"
$pasos = @(
    @("historico-spot", "--max-paginas", "30"),  # OKX + Bitvavo BTC/EUR
    @("historico-kraken", "--sin-zip"),          # API OHLC reciente, sin releer ZIP largo
    @("historico-derivados", "--dias", "14"),     # Actualizar lo publicado por cada endpoint
    @("velas", "--horas", "48"),                   # Velas propias a partir de trades
    @("opciones", "--capturar"),                  # Cadena Deribit (instantanea diaria)
    @("salud", "--umbral-s", "180")                # Diagnostico independiente
)
$fallos = 0
Push-Location $proyecto
try {
    foreach ($paso in $pasos) {
        if ($Prueba -and $paso[0] -ne "salud") {
            "Omitido en modo prueba: $($paso -join ' ')" | Out-File -Append -Encoding utf8 $log
            continue
        }
        "{0:o} INICIO {1}" -f (Get-Date).ToUniversalTime(), ($paso -join " ") |
            Out-File -Append -Encoding utf8 $log
        & $Python -m radar @paso 2>&1 | Out-File -Append -Encoding utf8 $log
        if ($LASTEXITCODE -ne 0) {
            $fallos++
            "{0:o} ERROR {1} (salida {2})" -f (Get-Date).ToUniversalTime(), $paso[0], $LASTEXITCODE |
                Out-File -Append -Encoding utf8 $log
        }
    }
} finally {
    Pop-Location
}
"Fin ciclo diario: $fallos errores" | Out-File -Append -Encoding utf8 $log
exit $fallos
