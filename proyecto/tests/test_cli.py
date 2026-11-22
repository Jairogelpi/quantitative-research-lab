import pytest

from radar.__main__ import main  # falla si __main__.py no compila


@pytest.mark.parametrize("argumentos", [
    ["analizar", "--horizontes", "0"],
    ["analizar", "--minimo", "1"],
    ["analizar", "--precio", "last"],
    ["capturar", "0"],
    ["costes", "--niveles", "0"],
    ["simular", "--trozos", "0"],
    ["simular", "--impactos", "-1"],
    ["simular", "--exchange", "binance"],
    ["simular", "--urgencias", "-1"],
    ["simular", "--intensidades", "-1"],
    ["ofi", "--niveles", "0"],
    ["leadlag", "--retardos", "0"],
    ["senales", "--horizonte", "0"],
    ["flujo", "0"],
    ["flujo", "--exchanges", "binance"],
    ["ofi", "--horizontes", "0"],
    ["simular", "--urgencia-adaptativa", "-1"],
])
def test_opciones_invalidas_se_rechazan(argumentos):
    with pytest.raises(SystemExit) as salida:
        main(argumentos)
    assert salida.value.code == 2
