"""Coste real de una ida y vuelta barriendo el libro (Fases 1 y 2; anticipa la lección 1.19 Costes operativos).

Conceptos:
- Orden de mercado (market order): la compra barre los asks y la venta barre los bids (`libro.py`).
- Taker / maker: quien toma liquidez paga la comisión taker; quien la da (orden limitada) suele pagar menos.
- Comisión por pata (fee per leg): porcentaje del importe en cada compra y en cada venta.
- Ida y vuelta (round trip): comprar y después vender la misma cantidad.
- Descomposición del coste (lo pagado − lo cobrado + comisiones), en tres piezas:
  · Spread: cantidad × (mejor ask − mejor bid). Lo que se pierde aunque todo cupiera en el mejor nivel.
  · Slippage: lo pagado de más al comprar + lo cobrado de menos al vender, por barrer niveles peores.
  · Comisiones: las dos patas, cada una sobre su importe.
- Punto de equilibrio (break-even): subida mínima para que la ida y vuelta, con costes, deje 0. Con varios
  niveles se usan los PRECIOS MEDIOS de ejecución; con un solo nivel coincide con ask/bid (Fase 1).
- Ejecución incompleta: el libro capturado no alcanza para el importe. No se inventa liquidez: el coste se
  calcula con lo que se pudo ejecutar y la ida y vuelta se marca como incompleta.
"""

from __future__ import annotations

from dataclasses import dataclass

from .libro import Ejecucion, Libro, barrer_compra, barrer_venta


@dataclass(frozen=True)
class CosteIdaVuelta:
    compra: Ejecucion
    venta: Ejecucion
    comision: float

    @property
    def cantidad_btc(self) -> float:
        return self.compra.cantidad_btc

    @property
    def coste_spread_eur(self) -> float:
        return self.cantidad_btc * (self.compra.mejor_precio - self.venta.mejor_precio)

    @property
    def slippage_eur(self) -> float:
        return self.compra.slippage_eur + self.venta.slippage_eur

    @property
    def comisiones_eur(self) -> float:
        return (self.compra.importe_eur + self.venta.importe_eur) * self.comision

    @property
    def coste_total_eur(self) -> float:
        return self.compra.importe_eur - self.venta.importe_eur + self.comisiones_eur

    @property
    def completa(self) -> bool:
        return self.compra.completa and self.venta.completa

    @property
    def punto_equilibrio_pct(self) -> float:
        """Subida (%) de los precios a los que se vende para que la ida y vuelta, con comisiones, deje 0.

        Pagas precio_medio_compra · (1 + c) por BTC y recibes precio_medio_venta · (1 − c): empatar exige que el
        precio de venta suba hasta precio_medio_compra · (1 + c) / (1 − c). La suma 2 · c es una aproximación algo
        menor: la comisión de venta se cobra sobre un importe que ya subió.
        """
        c = self.comision
        return (self.compra.precio_medio * (1 + c) / (1 - c) / self.venta.precio_medio - 1) * 100


def coste_ida_y_vuelta(libro: Libro, importe_eur: float, comision: float) -> CosteIdaVuelta:
    """Compra `importe_eur` barriendo los asks y vende al instante esa cantidad barriendo los bids."""
    if importe_eur <= 0 or not 0 <= comision < 1:
        raise ValueError("Importe positivo y comisión entre 0 y 1")
    compra = barrer_compra(libro, importe_eur)
    return CosteIdaVuelta(compra, barrer_venta(libro, compra.cantidad_btc), comision)
