"""Estadística para JP: promedio, mediana, moda, varianza, percentiles...

Las funciones de la librería de Python (statistics) reescritas con mensajes
en español y los tipos de JP. Todo trabaja sobre listas de números (moda y
contar/frecuencias aceptan cualquier valor).
"""

from __future__ import annotations

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, iguales, jp_a_texto


def _numeros(valor: object, nombre: str) -> list:
    if not isinstance(valor, list) or not valor:
        raise ErrorEjecucion(f"{nombre}() espera una lista de números con al menos un valor")
    numeros = []
    for v in valor:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ErrorEjecucion(f"{nombre}() espera solo números, recibió {jp_a_texto(v)!r}")
        numeros.append(v)
    return numeros


def instalar(entorno: Entorno, invocar=None) -> None:
    def promedio(lista: object):
        valores = _numeros(lista, "promedio")
        return sum(valores) / len(valores)

    def mediana(lista: object):
        valores = sorted(_numeros(lista, "mediana"))
        n = len(valores)
        medio = n // 2
        if n % 2:
            return valores[medio]
        return (valores[medio - 1] + valores[medio]) / 2

    def moda(lista: object):
        if not isinstance(lista, list) or not lista:
            raise ErrorEjecucion("moda() espera una lista con al menos un valor")
        mejor, mejor_cuenta = lista[0], 0
        for candidato in lista:
            cuenta = sum(1 for v in lista if iguales(v, candidato))
            if cuenta > mejor_cuenta:
                mejor, mejor_cuenta = candidato, cuenta
        return mejor

    def varianza(lista: object):
        """Varianza de la población (la de statistics.pvariance)."""
        valores = _numeros(lista, "varianza")
        media = sum(valores) / len(valores)
        return sum((v - media) ** 2 for v in valores) / len(valores)

    def desviacion(lista: object):
        return varianza(lista) ** 0.5

    def percentil(lista: object, p: object):
        valores = sorted(_numeros(lista, "percentil"))
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 100:
            raise ErrorEjecucion("percentil() espera un porcentaje entre 0 y 100")
        if len(valores) == 1:
            return valores[0]
        posicion = (float(p) / 100) * (len(valores) - 1)
        bajo = int(posicion)
        alto = min(bajo + 1, len(valores) - 1)
        fraccion = posicion - bajo
        return valores[bajo] + (valores[alto] - valores[bajo]) * fraccion

    def frecuencias(lista: object) -> dict:
        """{valor_en_texto: veces} — las claves de un diccionario JP son texto."""
        if not isinstance(lista, list):
            raise ErrorEjecucion("frecuencias() espera una lista")
        resultado: dict[str, int] = {}
        for v in lista:
            clave = jp_a_texto(v)
            resultado[clave] = resultado.get(clave, 0) + 1
        return resultado

    def contar(contenedor: object, valor: object) -> int:
        if isinstance(contenedor, str):
            if not isinstance(valor, str):
                raise ErrorEjecucion("contar() en un texto espera el pedazo a contar en texto")
            return contenedor.count(valor)
        if isinstance(contenedor, list):
            return sum(1 for v in contenedor if iguales(v, valor))
        raise ErrorEjecucion("contar() espera una lista o un texto")

    def resumen(lista: object) -> dict:
        valores = _numeros(lista, "resumen")
        return {
            "n": len(valores),
            "promedio": sum(valores) / len(valores),
            "mediana": mediana(valores),
            "minimo": min(valores),
            "maximo": max(valores),
            "desviacion": desviacion(valores),
        }

    nativas = {
        "promedio": FuncionNativa("promedio", promedio, aridad=1),
        "media": FuncionNativa("media", promedio, aridad=1),  # alias
        "mediana": FuncionNativa("mediana", mediana, aridad=1),
        "moda": FuncionNativa("moda", moda, aridad=1),
        "varianza": FuncionNativa("varianza", varianza, aridad=1),
        "desviacion": FuncionNativa("desviacion", desviacion, aridad=1),
        "percentil": FuncionNativa("percentil", percentil, aridad=2),
        "frecuencias": FuncionNativa("frecuencias", frecuencias, aridad=1),
        "contar": FuncionNativa("contar", contar, aridad=2),
        "resumen": FuncionNativa("resumen", resumen, aridad=1),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
