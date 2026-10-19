"""Fechas y tiempo para JP: ahora, fecha actual, formato y conversión.

Una fecha es un diccionario: {ano, mes, dia, hora, minuto, segundo,
dia_semana} con dia_semana 0=lunes ... 6=domingo (como en Python).
"""

from __future__ import annotations

import time
from datetime import datetime

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa


def _a_dict(momento: datetime) -> dict:
    return {
        "ano": momento.year,
        "mes": momento.month,
        "dia": momento.day,
        "hora": momento.hour,
        "minuto": momento.minute,
        "segundo": momento.second,
        "dia_semana": momento.weekday(),
    }


def instalar(entorno: Entorno, invocar=None) -> None:
    def ahora():
        """Segundos desde 1970 (la 'marca de tiempo' de siempre)."""
        return time.time()

    def fecha_actual() -> dict:
        return _a_dict(datetime.now())

    def fecha_de(marca: object) -> dict:
        if isinstance(marca, bool) or not isinstance(marca, (int, float)):
            raise ErrorEjecucion("fecha_de() espera una marca de tiempo (un número, como ahora())")
        return _a_dict(datetime.fromtimestamp(float(marca)))

    def hoy() -> str:
        return datetime.now().date().isoformat()

    def formatear_fecha(*args: object) -> str:
        if len(args) not in (1, 2):
            raise ErrorEjecucion("formatear_fecha() espera (marca) o (marca, formato)")
        marca = args[0]
        if isinstance(marca, bool) or not isinstance(marca, (int, float)):
            raise ErrorEjecucion("formatear_fecha() espera una marca de tiempo numérica")
        formato = args[1] if len(args) == 2 else "%d/%m/%Y %H:%M"
        if not isinstance(formato, str):
            raise ErrorEjecucion("el formato de formatear_fecha() debe ser texto, ej: '%Y-%m-%d'")
        return datetime.fromtimestamp(float(marca)).strftime(formato)

    def convertir_fecha(*args: object):
        if len(args) not in (1, 2):
            raise ErrorEjecucion("convertir_fecha() espera (texto) o (texto, formato)")
        texto = args[0]
        formato = args[1] if len(args) == 2 else "%Y-%m-%d"
        if not isinstance(texto, str) or not isinstance(formato, str):
            raise ErrorEjecucion("convertir_fecha() espera texto y un formato en texto")
        try:
            return datetime.strptime(texto, formato).timestamp()
        except ValueError:
            raise ErrorEjecucion(f"no pude leer la fecha {texto!r} con el formato {formato!r}") from None

    def sumar_dias(marca: object, dias: object):
        if isinstance(marca, bool) or not isinstance(marca, (int, float)):
            raise ErrorEjecucion("sumar_dias() espera una marca de tiempo numérica")
        if isinstance(dias, bool) or not isinstance(dias, (int, float)):
            raise ErrorEjecucion("sumar_dias() espera el número de días")
        return float(marca) + float(dias) * 86400

    def dias_entre(a: object, b: object) -> int:
        for v in (a, b):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ErrorEjecucion("dias_entre() espera dos marcas de tiempo numéricas")
        return int(abs(float(b) - float(a)) // 86400)

    nativas = {
        "sumar_dias": FuncionNativa("sumar_dias", sumar_dias, aridad=2),
        "dias_entre": FuncionNativa("dias_entre", dias_entre, aridad=2),
        "ahora": FuncionNativa("ahora", ahora, aridad=0),
        "fecha_actual": FuncionNativa("fecha_actual", fecha_actual, aridad=0),
        "fecha_de": FuncionNativa("fecha_de", fecha_de, aridad=1),
        "hoy": FuncionNativa("hoy", hoy, aridad=0),
        "formatear_fecha": FuncionNativa("formatear_fecha", formatear_fecha),
        "convertir_fecha": FuncionNativa("convertir_fecha", convertir_fecha),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
