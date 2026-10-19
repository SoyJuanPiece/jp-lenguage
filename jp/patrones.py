"""Patrones (expresiones regulares) para JP: buscar, validar y partir texto.

El módulo 're' de Python con nombres en español. Un patrón no válido da un
error claro en vez de explotar.
"""

from __future__ import annotations

import re

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa


def _patron(patron: object) -> re.Pattern:
    if not isinstance(patron, str):
        raise ErrorEjecucion("el patrón debe ser texto, ej: '[0-9]+'")
    try:
        return re.compile(patron)
    except re.error as e:
        raise ErrorEjecucion(f"patrón no válido: {e.msg} (en {patron!r})") from None


def _texto(v: object, nombre: str) -> str:
    if not isinstance(v, str):
        raise ErrorEjecucion(f"{nombre} espera texto")
    return v


def instalar(entorno: Entorno, invocar=None) -> None:
    def buscar_patron(patron: object, texto: object):
        """{texto, inicio, fin, grupos} de la primera aparición, o nulo."""
        encontrado = _patron(patron).search(_texto(texto, "buscar_patron()"))
        if encontrado is None:
            return None
        return {
            "texto": encontrado.group(0),
            "inicio": encontrado.start(),
            "fin": encontrado.end(),
            "grupos": list(encontrado.groups()),
        }

    def coincide_patron(patron: object, texto: object) -> bool:
        """¿El texto ENERO coincide con el patrón? (para validar formatos)."""
        return _patron(patron).fullmatch(_texto(texto, "coincide_patron()")) is not None

    def encontrar_patrones(patron: object, texto: object) -> list:
        return [m.group(0) for m in _patron(patron).finditer(_texto(texto, "encontrar_patrones()"))]

    def reemplazar_patron(patron: object, texto: object, reemplazo: object) -> str:
        return _patron(patron).sub(
            _texto(reemplazo, "reemplazar_patron()"), _texto(texto, "reemplazar_patron()")
        )

    def separar_patron(patron: object, texto: object) -> list:
        return _patron(patron).split(_texto(texto, "separar_patron()"))

    nativas = {
        "buscar_patron": FuncionNativa("buscar_patron", buscar_patron, aridad=2),
        "coincide_patron": FuncionNativa("coincide_patron", coincide_patron, aridad=2),
        "encontrar_patrones": FuncionNativa("encontrar_patrones", encontrar_patrones, aridad=2),
        "reemplazar_patron": FuncionNativa("reemplazar_patron", reemplazar_patron, aridad=3),
        "separar_patron": FuncionNativa("separar_patron", separar_patron, aridad=2),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
