"""Comparación de costes entre exchanges: dónde cuesta menos ejecutar una ida y vuelta AHORA (Fases 1 y 2; base de la 8).

Conceptos:
- Coste total de ejecución: spread + slippage + comisiones de las dos patas, barriendo el libro capturado.
- Ejecutable: el libro capturado alcanza para todo el importe en las dos patas. Que no quepa en el MEJOR nivel
  no lo hace inejecutable: solo añade slippage (error de la versión de la Fase 1, que solo veía un nivel).
- Conclusión determinista: hecho derivado SOLO de los números de esta ronda, siempre con la misma regla, que
  se puede volver a comprobar. No es una recomendación de dónde operar.

Reglas:
1. El más barato por comisión es el de menor comisión por pata.
2. El más barato EJECUTABLE es el de menor coste total entre los que tienen la ida y vuelta completa.
3. Cada exchange con el libro capturado insuficiente se dice, con el importe que sí se pudo ejecutar.
"""

from __future__ import annotations

from dataclasses import dataclass

from .costes import CosteIdaVuelta, coste_ida_y_vuelta
from .libro import Libro


def _euros(importe: float) -> str:
    return f"{importe:,.0f}".replace(",", ".")


@dataclass(frozen=True)
class CosteExchange:
    libro: Libro
    comision: float
    coste: CosteIdaVuelta

    @property
    def exchange(self) -> str:
        return self.libro.exchange


@dataclass(frozen=True)
class ComparacionCostes:
    importe_eur: float
    costes: tuple

    @property
    def mas_barato_por_comision(self) -> CosteExchange:
        return min(self.costes, key=lambda c: c.comision)

    @property
    def mas_barato_ejecutable(self) -> CosteExchange | None:
        completos = [c for c in self.costes if c.coste.completa]
        return min(completos, key=lambda c: c.coste.coste_total_eur) if completos else None

    @property
    def incompletos(self) -> list[str]:
        return [c.exchange for c in self.costes if not c.coste.completa]

    def conclusiones(self) -> list[str]:
        """Frases generadas a partir de los números, con las reglas del módulo."""
        importe = _euros(self.importe_eur)
        por_comision = self.mas_barato_por_comision
        frases = [f"Más barato por comisión: {por_comision.exchange} ({por_comision.comision:.2%} por pata)."]
        mejor = self.mas_barato_ejecutable
        if mejor is None:
            frases.append(f"Ningún exchange tiene libro capturado suficiente para una ida y vuelta de {importe} €.")
        else:
            k = mejor.coste
            frases.append(f"Más barato ejecutable con {importe} €: {mejor.exchange}, coste total {k.coste_total_eur:.2f} € "
                          f"(spread {k.coste_spread_eur:.2f} € + slippage {k.slippage_eur:.2f} € + comisiones "
                          f"{k.comisiones_eur:.2f} €; punto de equilibrio {k.punto_equilibrio_pct:.3f} %).")
        for c in self.costes:
            if not c.coste.completa:
                frases.append(f"{c.exchange}: el libro capturado solo alcanza para {c.coste.compra.importe_eur:.2f} € "
                              f"de los {importe} €.")
        return frases

    def a_filas(self) -> list[dict]:
        """Una fila por exchange para el almacén (fuente `comparaciones`)."""
        mejor, por_comision = self.mas_barato_ejecutable, self.mas_barato_por_comision
        return [{"exchange": c.exchange, "recibido_utc": c.libro.recibido_utc, "importe_eur": self.importe_eur,
                 "comision": c.comision, "cantidad_btc": c.coste.cantidad_btc,
                 "coste_spread_eur": c.coste.coste_spread_eur, "slippage_eur": c.coste.slippage_eur,
                 "comisiones_eur": c.coste.comisiones_eur, "coste_total_eur": c.coste.coste_total_eur,
                 "punto_equilibrio_pct": c.coste.punto_equilibrio_pct,
                 "precio_medio_compra": c.coste.compra.precio_medio, "precio_medio_venta": c.coste.venta.precio_medio,
                 "niveles_compra": c.coste.compra.niveles_usados, "niveles_venta": c.coste.venta.niveles_usados,
                 "completa": c.coste.completa,
                 "es_mas_barato_ejecutable": mejor is not None and c.exchange == mejor.exchange,
                 "es_mas_barato_por_comision": c.exchange == por_comision.exchange}
                for c in self.costes]

    def a_conclusion(self) -> dict:
        """Una fila resumen para el almacén (fuente `conclusiones`)."""
        mejor = self.mas_barato_ejecutable
        return {"recibido_utc": max(c.libro.recibido_utc for c in self.costes), "importe_eur": self.importe_eur,
                "exchanges": ",".join(c.exchange for c in self.costes),
                "mas_barato_por_comision": self.mas_barato_por_comision.exchange,
                "mas_barato_ejecutable": mejor.exchange if mejor else None,
                "incompletos": ",".join(self.incompletos), "texto": " ".join(self.conclusiones())}


def comparar_costes(libros, importe_eur: float, comisiones: dict) -> ComparacionCostes:
    """Compara una ida y vuelta de `importe_eur` en cada exchange, barriendo su libro con su comisión taker."""
    if not libros:
        raise ValueError("Hace falta al menos un libro")
    faltan = sorted({l.exchange for l in libros} - set(comisiones))
    if faltan:
        raise ValueError(f"Falta la comisión de: {faltan}")
    costes = tuple(CosteExchange(l, comisiones[l.exchange], coste_ida_y_vuelta(l, importe_eur, comisiones[l.exchange]))
                   for l in libros)
    return ComparacionCostes(importe_eur, costes)
