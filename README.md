# QuantLab · Entorno de formación

Este paquete es una base opcional; si ya tienes repositorio, copia los cuadernos y combina las dependencias sin sobrescribir tus archivos ni tus recolectores.

## Colab
Abre https://colab.research.google.com/ y sube `notebooks/01_financial_foundations/P01_market_snapshot.ipynb`. Elige CPU. Ejecuta en orden. Guarda los cambios en tu repositorio o descarga el cuaderno actualizado. No subas credenciales ni datos sensibles.

## Windows · Jupyter y VS Code
Desde PowerShell, en la raíz del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m ipykernel install --user --name quantlab --display-name "Python (QuantLab)"
.\.venv\Scripts\python.exe -m jupyterlab
```

En VS Code instala las extensiones Python y Jupyter, selecciona `.venv` como intérprete y el kernel Python (QuantLab) al abrir el cuaderno.

## Flujo
Un solo cuaderno por práctica. Usa Git para sincronizar los cambios entre Colab y local; evita editar simultáneamente dos copias. Los datos grandes quedan fuera de Git. Las funciones probadas se moverán a `src/` y sus pruebas a `tests/` cuando corresponda.

## P02
Abre `notebooks/01_financial_foundations/P02_order_book.ipynb`. Por defecto usa un libro de referencia; `USE_LIVE_DATA = True` consulta el libro público de Kraken y `LIVE_E5 = True` registra un snapshot en `data/raw/p02_snapshots.csv`. Las funciones están en `src/quantlab/p02/`.

## P01
El cuaderno usa por defecto una muestra ficticia determinista para verificar el entorno. Cambia `USE_LIVE_DATA` a `True` para consultar el ticker público de Kraken. La consulta en vivo requiere Internet y no ha sido verificada en este entorno. No envía órdenes. Los ejercicios están intencionadamente pendientes.
