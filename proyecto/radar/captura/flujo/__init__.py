"""Captura por websocket del flujo del libro (cambios con secuencia y checksum) y de los trades de cada exchange."""

from .captura import capturar_flujo, crear_protocolos

__all__ = ["capturar_flujo", "crear_protocolos"]
