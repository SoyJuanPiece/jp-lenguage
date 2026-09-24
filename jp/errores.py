"""Errores del lenguaje JP con formato amigable (línea y puntero)."""

from __future__ import annotations


class ErrorJP(Exception):
    """Error base del lenguaje JP."""

    titulo = "Error"

    def __init__(self, mensaje: str, linea: int = 0, columna: int = 0):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.linea = linea
        self.columna = columna

    def formatear(self, fuente: str) -> str:
        """Devuelve el error bonito, con la línea culpable y un puntero ^."""
        lineas = fuente.splitlines()
        encabezado = f"{self.titulo}: {self.mensaje}"
        if self.linea <= 0 or self.linea > len(lineas):
            return encabezado
        culpable = lineas[self.linea - 1]
        columna = max(1, self.columna)
        puntero = " " * (columna - 1) + "^"
        return (
            f"{encabezado}\n"
            f"    --> línea {self.linea}, columna {self.columna}\n"
            f" {self.linea:>4} | {culpable}\n"
            f"      | {puntero}"
        )


class ErrorLexico(ErrorJP):
    """Carácter no reconocido, string sin cerrar, etc."""

    titulo = "Error léxico"


class ErrorSintaxis(ErrorJP):
    """Token inesperado durante el parsing."""

    titulo = "Error de sintaxis"


class ErrorEjecucion(ErrorJP):
    """Error en tiempo de ejecución (tipos incorrectos, división por cero...)."""

    titulo = "Error de ejecución"
