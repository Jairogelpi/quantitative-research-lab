"""Reconstrucción incremental del libro de órdenes a partir del flujo de cambios (Fase 2 · captura profesional).

Conceptos:
- Snapshot + actualizaciones (incremental feed): el exchange manda una vez el libro entero y después solo los
  niveles que cambian. Aplicándolos en orden se tiene el libro en cada instante, sin perder eventos entre fotos.
- Cantidad 0 = borrar el nivel: así anuncian los tres exchanges que un precio ya no tiene órdenes.
- Precio como `Decimal`: el nivel se identifica por su precio exacto; "55719" y "55719.00" son el mismo nivel
  (Bitvavo usa los dos textos) y la coma flotante no debe partir un nivel en dos.
- Número de secuencia: cada mensaje lleva su número y el anterior (OKX: `seqId`/`prevSeqId`) o un contador que
  sube de uno en uno (Bitvavo: `nonce`). Si falta un número, se perdió un mensaje y el libro ya no es fiable.
- Checksum: el exchange manda un resumen (CRC32) de sus mejores niveles; si no coincide con el calculado sobre el
  libro local, el libro local está mal (Kraken).
- Desincronización: hueco de secuencia o checksum distinto. El libro se DESCARTA y se avisa al llamador (que lo
  registra y vuelve a pedir el snapshot); nunca se sigue en silencio con un libro dudoso.
- Rango del snapshot: si el snapshot trae solo N niveles pero los cambios llegan de todo el libro (Bitvavo), lo que
  queda más allá del peor nivel del snapshot no se conoce entero y no se publica.

Reglas verificadas en la documentación oficial (22-11-2026):
- Kraken WS v2, checksum: https://docs.kraken.com/api/docs/guides/spot-ws-book-v2 — CRC32 (sin signo) de los 10
  mejores asks (de menor a mayor) seguidos de los 10 mejores bids (de mayor a menor), cada nivel como precio y
  cantidad sin el punto decimal y sin ceros a la izquierda; se calcula tras aplicar TODOS los niveles del mensaje y
  truncar el libro a la profundidad suscrita (Kraken no manda cantidad 0 de los niveles que salen de ella).
- OKX v5, canal `books`: https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-order-book-channel —
  cada actualización trae `prevSeqId` = `seqId` del mensaje anterior; sin cambios llega `prevSeqId` = `seqId`; tras
  un mantenimiento la secuencia puede reiniciarse (`seqId` < `prevSeqId`) y sigue la regla normal. El `checksum`
  está obsoleto (vale siempre 0) y no se usa.
- Bitvavo v2, canal `book`: https://docs.bitvavo.com/docs/manage-order-book/ — el `nonce` sube exactamente de 1 en
  1; si no, el libro local está desincronizado y hay que reconstruirlo. No hay checksum.
"""

from __future__ import annotations

import zlib
from decimal import Decimal
from typing import Callable

import pandas as pd

from .libro import Libro, Nivel

BID, ASK = "bid", "ask"
HUECO, CHECKSUM = "hueco_secuencia", "checksum"
NIVELES_CHECKSUM_KRAKEN = 10


class Desincronizacion(Exception):
    """El libro local dejó de ser fiable (`motivo`: HUECO o CHECKSUM). El libro ya está descartado."""

    def __init__(self, exchange: str, motivo: str, detalle: str):
        super().__init__(f"{exchange}: {motivo}: {detalle}")
        self.exchange, self.motivo, self.detalle = exchange, motivo, detalle


def a_decimal(valor) -> Decimal:
    """Texto, entero o Decimal a Decimal exacto (los float se pasan por texto para no arrastrar binario)."""
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def continua_okx(local, secuencia, previa) -> bool:
    """OKX: el mensaje enlaza con el último aplicado si su `prevSeqId` es el `seqId` local."""
    return previa is not None and int(previa) == int(local)


def continua_bitvavo(local, secuencia, previa=None) -> bool:
    """Bitvavo: el `nonce` debe ser exactamente el local + 1."""
    return int(secuencia) == int(local) + 1


class LibroIncremental:
    """Libro de un exchange mantenido con snapshot + cambios. Mutable (cambia con cada mensaje); produce `Libro`s
    inmutables bajo demanda.

    - `profundidad`: si se da, tras cada mensaje se conservan solo esos niveles por lado (Kraken).
    - `regla_secuencia(local, secuencia, previa) -> bool`: continuidad de la secuencia; None si no hay (Kraken).
    - `checksum(libro) -> int`: cálculo del checksum, comparado con el de cada mensaje que lo traiga; None si no hay.
    - `solo_rango_snapshot`: publicar solo niveles dentro del rango de precios del último snapshot (Bitvavo).
    """

    def __init__(self, exchange: str, profundidad: int | None = None,
                 regla_secuencia: Callable | None = None, checksum: Callable | None = None,
                 solo_rango_snapshot: bool = False):
        self.exchange, self.profundidad = exchange, profundidad
        self.regla_secuencia, self.calcular_checksum = regla_secuencia, checksum
        self.solo_rango_snapshot = solo_rango_snapshot
        self.invalidar()

    def invalidar(self):
        """Descarta el libro: hasta el próximo snapshot no hay libro."""
        self._lados: dict[str, dict[Decimal, Decimal]] = {BID: {}, ASK: {}}
        self._frontera: dict[str, Decimal | None] = {BID: None, ASK: None}
        self.sincronizado = False
        self.secuencia = None
        self.hora_exchange_utc: pd.Timestamp | None = None

    # --- aplicar mensajes -------------------------------------------------------------------------------------

    def aplicar_snapshot(self, bids, asks, secuencia=None, checksum=None, hora=None):
        """Sustituye el libro entero. Con checksum, lo verifica (y si falla, lanza `Desincronizacion`)."""
        self.invalidar()
        self._aplicar_niveles(bids, asks)
        if self.solo_rango_snapshot:
            self._frontera = {BID: min(self._lados[BID], default=None), ASK: max(self._lados[ASK], default=None)}
        self.sincronizado, self.secuencia, self.hora_exchange_utc = True, secuencia, hora
        self._comprobar_checksum(checksum)

    def aplicar_actualizacion(self, bids, asks, secuencia=None, secuencia_previa=None, checksum=None, hora=None):
        """Aplica los cambios de un mensaje: comprueba antes la secuencia y después el checksum."""
        if not self.sincronizado:
            raise ValueError(f"{self.exchange}: actualización sin snapshot previo")
        if self.regla_secuencia is not None and not self.regla_secuencia(self.secuencia, secuencia, secuencia_previa):
            local = self.secuencia
            self.invalidar()
            raise Desincronizacion(self.exchange, HUECO,
                                   f"secuencia local {local}, recibida {secuencia} (previa {secuencia_previa})")
        self._aplicar_niveles(bids, asks)
        if secuencia is not None:
            self.secuencia = secuencia
        if hora is not None:
            self.hora_exchange_utc = hora
        self._comprobar_checksum(checksum)

    def _aplicar_niveles(self, bids, asks):
        for lado, cambios in ((BID, bids), (ASK, asks)):
            niveles = self._lados[lado]
            for precio, cantidad in cambios:
                precio, cantidad = a_decimal(precio), a_decimal(cantidad)
                if cantidad == 0:
                    niveles.pop(precio, None)
                else:
                    niveles[precio] = cantidad
        if self.profundidad is not None:
            for lado in (BID, ASK):
                conservar = dict(self._ordenados(lado)[:self.profundidad])
                self._lados[lado] = conservar

    def _comprobar_checksum(self, esperado):
        if esperado is None or self.calcular_checksum is None:
            return
        calculado = self.calcular_checksum(self)
        if calculado != int(esperado):
            self.invalidar()
            raise Desincronizacion(self.exchange, CHECKSUM, f"esperado {esperado}, calculado {calculado}")

    # --- leer el libro ----------------------------------------------------------------------------------------

    def _ordenados(self, lado: str) -> list[tuple[Decimal, Decimal]]:
        return sorted(self._lados[lado].items(), reverse=(lado == BID))

    def mejores(self, lado: str, n: int) -> tuple[tuple[Decimal, Decimal], ...]:
        """Los `n` mejores niveles de un lado (bids de mayor a menor, asks de menor a mayor), dentro del rango fiable."""
        frontera = self._frontera[lado]
        niveles = self._ordenados(lado)
        if frontera is not None:
            niveles = [nv for nv in niveles if (nv[0] >= frontera if lado == BID else nv[0] <= frontera)]
        return tuple(niveles[:n])

    def libro(self, niveles: int, instante: pd.Timestamp, par: str) -> Libro:
        """Foto inmutable (`Libro`) de los mejores `niveles` en `instante` (hora de la foto, UTC). Valida como
        cualquier libro: si estuviera cruzado, lanza `CotizacionInvalida`."""
        if not self.sincronizado:
            raise ValueError(f"{self.exchange}: no hay libro sincronizado")
        bids = tuple(Nivel(float(p), float(c)) for p, c in self.mejores(BID, niveles))
        asks = tuple(Nivel(float(p), float(c)) for p, c in self.mejores(ASK, niveles))
        return Libro(self.exchange, par, bids, asks, instante, instante, self.hora_exchange_utc)


# --- checksum de Kraken -------------------------------------------------------------------------------------------

def _texto_kraken(valor: Decimal, decimales: int | None) -> str:
    if decimales is not None:
        valor = valor.quantize(Decimal(1).scaleb(-decimales))
    return format(valor, "f").replace(".", "").lstrip("0")


def cadena_checksum_kraken(libro: LibroIncremental, decimales_precio: int | None = None,
                           decimales_cantidad: int | None = None) -> str:
    """Texto sobre el que Kraken calcula el CRC32: 10 asks y luego 10 bids, precio+cantidad sin punto ni ceros a la
    izquierda. Sin `decimales_*` se usa el texto tal como llegó (Kraken manda los ceros de su precisión)."""
    partes = []
    for lado in (ASK, BID):
        for precio, cantidad in libro.mejores(lado, NIVELES_CHECKSUM_KRAKEN):
            partes.append(_texto_kraken(precio, decimales_precio) + _texto_kraken(cantidad, decimales_cantidad))
    return "".join(partes)


def checksum_kraken(libro: LibroIncremental, decimales_precio: int | None = None,
                    decimales_cantidad: int | None = None) -> int:
    """CRC32 sin signo (32 bits) del libro según la regla de Kraken."""
    return zlib.crc32(cadena_checksum_kraken(libro, decimales_precio, decimales_cantidad).encode()) & 0xFFFFFFFF
