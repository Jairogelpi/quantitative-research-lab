"""Sincronización del libro con el flujo: cuándo aplicar, guardar o descartar cada evento (sin red).

Conceptos:
- Esperando snapshot: tras conectar o tras una desincronización no hay libro. Los cambios que llegan entonces no se
  pueden aplicar: se descartan (Kraken, OKX: el snapshot nuevo ya los incluye) o se guardan en un buffer para
  aplicarlos después (Bitvavo, que pide el snapshot aparte con `getBook`).
- Buffer de Bitvavo: al llegar el snapshot se descartan los cambios con `nonce` ≤ el suyo y se aplican los demás en
  orden; si entre el snapshot y el primero falta un `nonce`, es un hueco.
- Desincronización devuelta, no lanzada: el llamador la registra y pide un snapshot nuevo; el sincronizador ya
  vuelve a esperar uno.
"""

from __future__ import annotations

from collections import deque

from radar.mercado.reconstruccion import HUECO, Desincronizacion, LibroIncremental

from .eventos import SNAPSHOT, EventoLibro
from .parametros import MAX_BUFFER_BITVAVO


class Sincronizador:
    def __init__(self, libro: LibroIncremental, con_buffer: bool = False, max_buffer: int = MAX_BUFFER_BITVAVO):
        self.libro, self.con_buffer = libro, con_buffer
        self.buffer: deque[EventoLibro] = deque(maxlen=max_buffer)
        self.ignorados = 0

    @property
    def esperando_snapshot(self) -> bool:
        return not self.libro.sincronizado

    def aplicar(self, evento: EventoLibro) -> Desincronizacion | None:
        """Aplica un evento del libro. Devuelve la desincronización si la hubo (el libro ya está descartado)."""
        try:
            if evento.tipo == SNAPSHOT:
                self._snapshot(evento)
            elif self.esperando_snapshot:
                if self.con_buffer:
                    self.buffer.append(evento)
                else:
                    self.ignorados += 1
            else:
                self._actualizar(evento)
        except Desincronizacion as d:
            self.libro.invalidar()
            self.buffer.clear()
            return d
        return None

    def _actualizar(self, e: EventoLibro):
        self.libro.aplicar_actualizacion(e.bids, e.asks, e.secuencia, e.secuencia_previa, e.checksum,
                                         e.hora_exchange_utc)

    def _snapshot(self, e: EventoLibro):
        self.libro.aplicar_snapshot(e.bids, e.asks, e.secuencia, e.checksum, e.hora_exchange_utc)
        pendientes = sorted((b for b in self.buffer if e.secuencia is None or b.secuencia > e.secuencia),
                            key=lambda b: b.secuencia)
        self.buffer.clear()
        if pendientes and e.secuencia is not None and pendientes[0].secuencia != e.secuencia + 1:
            raise Desincronizacion(self.libro.exchange, HUECO,
                                   f"snapshot {e.secuencia}, primer cambio guardado {pendientes[0].secuencia}")
        for b in pendientes:
            self._actualizar(b)
