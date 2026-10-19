"""Sistema para JP: plataforma, entorno, rutas y ejecutar programas.

El equivalente humilde de os/sys/subprocess de Python, en español.
"""

from __future__ import annotations

import os
import platform
import shlex
import subprocess

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto


def _ruta(v: object, nombre: str) -> str:
    if not isinstance(v, str) or not v:
        raise ErrorEjecucion(f"{nombre} espera una ruta en texto")
    return v


def instalar(entorno: Entorno, invocar=None) -> None:
    def plataforma() -> str:
        return platform.system()  # 'Linux', 'Windows', 'Darwin'...

    def leer_entorno(*args: object) -> str:
        if len(args) not in (1, 2):
            raise ErrorEjecucion("leer_entorno() espera (nombre) o (nombre, valor_si_falta)")
        nombre = args[0]
        if not isinstance(nombre, str):
            raise ErrorEjecucion("leer_entorno() espera el nombre en texto")
        defecto = jp_a_texto(args[1]) if len(args) == 2 else ""
        return os.environ.get(nombre, defecto)

    def carpeta_actual() -> str:
        return os.getcwd()

    def cambiar_carpeta(ruta: object) -> bool:
        r = _ruta(ruta, "cambiar_carpeta()")
        try:
            os.chdir(r)
        except OSError as e:
            raise ErrorEjecucion(f"no pude entrar a la carpeta {r}: {e}") from None
        return True

    def unir_ruta(*args: object) -> str:
        if not args:
            raise ErrorEjecucion("unir_ruta() espera al menos un pedazo de ruta")
        return os.path.join(*[_ruta(a, "unir_ruta()") for a in args])

    def nombre_base(ruta: object) -> str:
        return os.path.basename(_ruta(ruta, "nombre_base()"))

    def carpeta_de(ruta: object) -> str:
        return os.path.dirname(_ruta(ruta, "carpeta_de()"))

    def extension_de(ruta: object) -> str:
        return os.path.splitext(_ruta(ruta, "extension_de()"))[1]

    def existe_ruta(ruta: object) -> bool:
        return os.path.exists(_ruta(ruta, "existe_ruta()"))

    def es_carpeta(ruta: object) -> bool:
        return os.path.isdir(_ruta(ruta, "es_carpeta()"))

    def es_archivo(ruta: object) -> bool:
        return os.path.isfile(_ruta(ruta, "es_archivo()"))

    def crear_carpeta(ruta: object) -> bool:
        r = _ruta(ruta, "crear_carpeta()")
        try:
            os.makedirs(r, exist_ok=True)
        except OSError as e:
            raise ErrorEjecucion(f"no pude crear la carpeta {r}: {e}") from None
        return True

    def ejecutar(comando: object) -> dict:
        """Ejecuta un programa y devuelve {codigo, salida, error}."""
        if not isinstance(comando, str) or not comando.strip():
            raise ErrorEjecucion("ejecutar() espera el comando en texto, ej: ejecutar('jp --version')")
        try:
            partes = shlex.split(comando)
        except ValueError as e:
            raise ErrorEjecucion(f"comando mal formado: {e}") from None
        try:
            proceso = subprocess.run(partes, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            raise ErrorEjecucion(f"no se encontró el programa '{partes[0]}'") from None
        except subprocess.TimeoutExpired:
            raise ErrorEjecucion("el comando tardó más de 30 segundos y se canceló") from None
        return {"codigo": proceso.returncode, "salida": proceso.stdout, "error": proceso.stderr}

    nativas = {
        "plataforma": FuncionNativa("plataforma", plataforma, aridad=0),
        "leer_entorno": FuncionNativa("leer_entorno", leer_entorno),
        "carpeta_actual": FuncionNativa("carpeta_actual", carpeta_actual, aridad=0),
        "cambiar_carpeta": FuncionNativa("cambiar_carpeta", cambiar_carpeta, aridad=1),
        "unir_ruta": FuncionNativa("unir_ruta", unir_ruta),
        "nombre_base": FuncionNativa("nombre_base", nombre_base, aridad=1),
        "carpeta_de": FuncionNativa("carpeta_de", carpeta_de, aridad=1),
        "extension_de": FuncionNativa("extension_de", extension_de, aridad=1),
        "existe_ruta": FuncionNativa("existe_ruta", existe_ruta, aridad=1),
        "es_carpeta": FuncionNativa("es_carpeta", es_carpeta, aridad=1),
        "es_archivo": FuncionNativa("es_archivo", es_archivo, aridad=1),
        "crear_carpeta": FuncionNativa("crear_carpeta", crear_carpeta, aridad=1),
        "ejecutar": FuncionNativa("ejecutar", ejecutar, aridad=1),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
