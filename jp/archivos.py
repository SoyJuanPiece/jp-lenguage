"""Archivos para JP: leer, escribir y agregar, con la librería estándar.

Nativas que instala:
    leer_archivo(ruta)              -> texto del archivo (error amigable si no existe)
    escribir_archivo(ruta, texto)   -> verdadero (crea o sobreescribe, UTF-8)
    agregar_archivo(ruta, texto)    -> verdadero (añade al final; crea si no existe)
    existe_archivo(ruta)            -> verdadero / falso
    tamano_archivo(ruta)            -> bytes del archivo (0 si no existe)
    lista_archivos(ruta=".")        -> lista de nombres de la carpeta
"""

from __future__ import annotations

import os

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto


def instalar(entorno: Entorno) -> None:
    def _ruta(v: object) -> str:
        if not isinstance(v, str) or not v:
            raise ErrorEjecucion("se esperaba una ruta de archivo en texto")
        return v

    def leer_archivo(ruta: object) -> str:
        r = _ruta(ruta)
        try:
            with open(r, "r", encoding="utf-8") as archivo:
                return archivo.read()
        except FileNotFoundError:
            raise ErrorEjecucion(f"no existe el archivo: {r}") from None
        except IsADirectoryError:
            raise ErrorEjecucion(f"es una carpeta, no un archivo: {r}") from None
        except OSError as e:
            raise ErrorEjecucion(f"no se pudo leer {r}: {e}") from None
        except UnicodeDecodeError:
            raise ErrorEjecucion(f"el archivo {r} no es texto UTF-8") from None

    def escribir_archivo(ruta: object, contenido: object) -> bool:
        r = _ruta(ruta)
        texto = contenido if isinstance(contenido, str) else jp_a_texto(contenido)
        try:
            with open(r, "w", encoding="utf-8") as archivo:
                archivo.write(texto)
        except OSError as e:
            raise ErrorEjecucion(f"no se pudo escribir {r}: {e}") from None
        return True

    def agregar_archivo(ruta: object, contenido: object) -> bool:
        r = _ruta(ruta)
        texto = contenido if isinstance(contenido, str) else jp_a_texto(contenido)
        try:
            with open(r, "a", encoding="utf-8") as archivo:
                archivo.write(texto)
        except OSError as e:
            raise ErrorEjecucion(f"no se pudo escribir {r}: {e}") from None
        return True

    def existe_archivo(ruta: object) -> bool:
        return os.path.exists(_ruta(ruta))

    def tamano_archivo(ruta: object) -> int:
        r = _ruta(ruta)
        return os.path.getsize(r) if os.path.exists(r) else 0

    def lista_archivos(ruta: object = ".") -> list:
        r = _ruta(ruta) if ruta is not None else "."
        if not os.path.isdir(r):
            raise ErrorEjecucion(f"no es una carpeta: {r}")
        return sorted(os.listdir(r))

    nativas = {
        "leer_archivo": FuncionNativa("leer_archivo", leer_archivo, aridad=1),
        "escribir_archivo": FuncionNativa("escribir_archivo", escribir_archivo, aridad=2),
        "agregar_archivo": FuncionNativa("agregar_archivo", agregar_archivo, aridad=2),
        "existe_archivo": FuncionNativa("existe_archivo", existe_archivo, aridad=1),
        "tamano_archivo": FuncionNativa("tamano_archivo", tamano_archivo, aridad=1),
        "lista_archivos": FuncionNativa("lista_archivos", lista_archivos, aridad=1),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
