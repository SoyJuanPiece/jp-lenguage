"""Tablas (CSV) para JP: el puente hacia los datos, estilo pandas mínimo.

    leer_csv(ruta)            -> lista de diccionarios (la 1ª fila es la cabecera)
    leer_csv_texto(texto)     -> lo mismo, desde un texto
    escribir_csv(ruta, filas) -> verdadero (filas = lista de diccionarios)
    convertir_csv(filas)      -> el texto CSV de unas filas

Los valores se convierten solos: "42" -> 42, "3.5" -> 3.5,
"verdadero"/"falso" -> booleano y "" -> nulo. Al escribir, el camino inverso.
"""

from __future__ import annotations

import csv
import io

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto


def _convertir(texto: str):
    if texto == "":
        return None
    if texto == "verdadero":
        return True
    if texto == "falso":
        return False
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return float(texto)
    except ValueError:
        return texto


def _filas_desde(texto: str, origen: str) -> list:
    lector = csv.reader(io.StringIO(texto))
    filas_crudas = [fila for fila in lector if fila]
    if not filas_crudas:
        raise ErrorEjecucion(f"{origen}: el CSV está vacío")
    cabecera = filas_crudas[0]
    filas = []
    for cruda in filas_crudas[1:]:
        fila = {}
        for i, nombre in enumerate(cabecera):
            fila[nombre] = _convertir(cruda[i]) if i < len(cruda) else None
        filas.append(fila)
    return filas


def _texto_desde(filas: object) -> str:
    if not isinstance(filas, list) or not filas or not all(isinstance(f, dict) for f in filas):
        raise ErrorEjecucion("escribir_csv()/convertir_csv() esperan una lista de diccionarios")
    cabecera: list[str] = []
    for fila in filas:
        for clave in fila:
            if clave not in cabecera:
                cabecera.append(clave)

    def celda(valor: object) -> str:
        if valor is None:
            return ""
        if valor is True:
            return "verdadero"
        if valor is False:
            return "falso"
        return jp_a_texto(valor)

    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(cabecera)
    for fila in filas:
        escritor.writerow([celda(fila.get(clave)) for clave in cabecera])
    return salida.getvalue()


def instalar(entorno: Entorno, invocar=None) -> None:
    def leer_csv(ruta: object) -> list:
        if not isinstance(ruta, str) or not ruta:
            raise ErrorEjecucion("leer_csv() espera la ruta del archivo en texto")
        try:
            with open(ruta, "r", encoding="utf-8", newline="") as archivo:
                texto = archivo.read()
        except FileNotFoundError:
            raise ErrorEjecucion(f"no existe el archivo: {ruta}") from None
        except OSError as e:
            raise ErrorEjecucion(f"no se pudo leer {ruta}: {e}") from None
        return _filas_desde(texto, f"leer_csv({ruta!r})")

    def leer_csv_texto(texto: object) -> list:
        if not isinstance(texto, str):
            raise ErrorEjecucion("leer_csv_texto() espera el CSV en texto")
        return _filas_desde(texto, "leer_csv_texto()")

    def escribir_csv(ruta: object, filas: object) -> bool:
        if not isinstance(ruta, str) or not ruta:
            raise ErrorEjecucion("escribir_csv() espera la ruta en texto")
        texto = _texto_desde(filas)
        try:
            with open(ruta, "w", encoding="utf-8", newline="") as archivo:
                archivo.write(texto)
        except OSError as e:
            raise ErrorEjecucion(f"no se pudo escribir {ruta}: {e}") from None
        return True

    def convertir_csv(filas: object) -> str:
        return _texto_desde(filas)

    def sublista(lista: object, *args: object) -> list:
        """sublista(lista, inicio[, fin]): el trozo, con negativos como en listas."""
        if not isinstance(lista, (list, str)):
            raise ErrorEjecucion("sublista() espera una lista o un texto")
        if len(args) not in (1, 2):
            raise ErrorEjecucion("sublista() espera (lista, inicio) o (lista, inicio, fin)")
        for a in args:
            if isinstance(a, bool) or not isinstance(a, (int, float)):
                raise ErrorEjecucion("sublista() espera posiciones numéricas")
        inicio = int(args[0])
        fin = int(args[1]) if len(args) == 2 else None
        return lista[inicio:fin]

    nativas = {
        "leer_csv": FuncionNativa("leer_csv", leer_csv, aridad=1),
        "leer_csv_texto": FuncionNativa("leer_csv_texto", leer_csv_texto, aridad=1),
        "escribir_csv": FuncionNativa("escribir_csv", escribir_csv, aridad=2),
        "convertir_csv": FuncionNativa("convertir_csv", convertir_csv, aridad=1),
        "sublista": FuncionNativa("sublista", sublista),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
