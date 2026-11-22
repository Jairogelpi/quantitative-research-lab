# Ciclo semanal del radar: revalidar lo que se encontró, volver a correr los estudios y corregir sobre todo.
# El ORDEN importa: primero se revalidan los hallazgos guardados con los datos llegados después de su estudio;
# si los estudios se corrieran antes, cada corrida movería la fecha de corte y nunca habría datos nuevos que probar.
# Al final, el registro corrige por pruebas múltiples sobre todo lo probado y la robustez mira los parámetros vecinos.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ciclo_semanal.ps1 [-Prueba]
# -Prueba: corre todo con --no-guardar (comprueba que funciona sin mover la fecha de corte de ningún estudio).
param([string]$Python = "C:\Python313\python.exe", [switch]$Prueba)

$raiz = Split-Path -Parent $PSScriptRoot
$proyecto = Join-Path $raiz "proyecto"
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$sufijo = if ($Prueba) { "_prueba" } else { "" }
$log = Join-Path $logs ("ciclo_{0:yyyy-MM-dd}{1}.log" -f (Get-Date).ToUniversalTime(), $sufijo)
$env:PYTHONIOENCODING = "utf-8"

$pasos = @(
    @("revalidar"),                         # 1. hallazgos de OFI, lead-lag y señales con datos posteriores
    @("analizar"),                          # 2. imbalance (revalida sus hallazgos antes de guardar el estudio nuevo)
    @("ofi"),
    @("leadlag"),
    @("senales"),
    @("estacionalidad"),
    @("markouts"),
    @("liquidez", "--horas", "168"),        # la semana entera
    @("volatilidad"),
    @("relojes", "--horas", "168"),
    @("hy", "--horas", "2"),                # caro: unos 2 minutos por hora de flujo
    @("ofi-eventos", "--horas", "168"),     # Fase 3: OFI con cada cambio del libro
    @("presion", "--horas", "168"),         # Fase 3: trade imbalance, CVD, intensidad, VWAP, exposición
    @("respuesta", "--horas", "168"),       # Fase 3: función de respuesta de Bouchaud
    @("arbitraje", "--horas", "24"),        # Fase 6: caro (unos 3 min por cada 6 h de flujo)
    @("velas", "--horas", "168"),           # Fase 4: velas propias de la semana
    @("historico-derivados", "--dias", "14"),  # Fase 7: OKX solo guarda 3 meses de funding y 60 días de OI
    @("derivados"),
    @("opciones", "--capturar"),            # Fase 7: una foto semanal de la cadena (~2 min)
    @("opciones"),
    @("historico-kraken"),                  # Fase 4: lo nuevo de Kraken (idempotente)
    @("comparar-velas"),                    # Fase 4: propias frente a oficiales
    @("retornos", "--fuente", "propia"),
    @("retornos", "--fuente", "kraken_historico"),
    @("registro"),                          # 3. corrección global sobre todo lo probado
    @("robustez")                           # 4. parámetros vecinos de cada hallazgo
)

$fallos = 0
Push-Location $proyecto
# Pasos que solo actualizan datos (idempotentes) y no tienen --no-guardar: en modo prueba se saltan.
$soloDatos = @("velas", "historico-kraken", "historico-derivados", "opciones --capturar")
foreach ($paso in $pasos) {
    if ($Prueba -and ($soloDatos -contains $paso[0] -or $soloDatos -contains ($paso -join " "))) {
        "{0:o} --- {1} (se salta en modo prueba: solo actualiza datos)" -f (Get-Date).ToUniversalTime(), $paso[0] | Out-File -Append -Encoding utf8 $log
        continue
    }
    "{0:o} === {1}" -f (Get-Date).ToUniversalTime(), ($paso -join " ") | Out-File -Append -Encoding utf8 $log
    $argumentos = if ($Prueba) { $paso + "--no-guardar" } else { $paso }
    & $Python -m radar @argumentos 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) {
        $fallos++
        "{0:o} FALLO {1} (código {2})" -f (Get-Date).ToUniversalTime(), $paso[0], $LASTEXITCODE | Out-File -Append -Encoding utf8 $log
    }
}
Pop-Location
"{0:o} ciclo terminado: {1} paso(s) con fallo" -f (Get-Date).ToUniversalTime(), $fallos | Out-File -Append -Encoding utf8 $log
exit $fallos
