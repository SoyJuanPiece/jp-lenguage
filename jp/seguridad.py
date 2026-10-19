"""Seguridad basica para JP: huellas (hash), base64 e identificadores.

El hashlib/base64/uuid de Python con nombres en espanol. Ojo: md5 y sha1
estan solo para compatibilidad; para contrasenas de verdad hace falta algo
con sal y coste (eso aun no vive aqui).
"""

from __future__ import annotations

import base64
import hashlib
import uuid

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa


def instalar(entorno: Entorno, invocar=None) -> None:
    def hash_texto(*args: object) -> str:
        if len(args) not in (1, 2):
            raise ErrorEjecucion("hash_texto() espera (texto) o (texto, algoritmo)")
        texto = args[0]
        algoritmo = args[1] if len(args) == 2 else "sha256"
        if not isinstance(texto, str) or not isinstance(algoritmo, str):
            raise ErrorEjecucion("hash_texto() espera texto y un algoritmo en texto")
        if algoritmo not in ("md5", "sha1", "sha256", "sha512"):
            raise ErrorEjecucion("algoritmo no soportado: usa 'md5', 'sha1', 'sha256' o 'sha512'")
        return hashlib.new(algoritmo, texto.encode("utf-8")).hexdigest()

    def codificar64(texto: object) -> str:
        if not isinstance(texto, str):
            raise ErrorEjecucion("codificar64() espera texto")
        return base64.b64encode(texto.encode("utf-8")).decode("ascii")

    def decodificar64(texto: object) -> str:
        if not isinstance(texto, str):
            raise ErrorEjecucion("decodificar64() espera texto en base64")
        try:
            return base64.b64decode(texto.encode("ascii"), validate=True).decode("utf-8")
        except Exception:
            raise ErrorEjecucion("decodificar64(): eso no es base64 valido") from None

    def id_unico() -> str:
        return str(uuid.uuid4())

    nativas = {
        "hash_texto": FuncionNativa("hash_texto", hash_texto),
        "codificar64": FuncionNativa("codificar64", codificar64, aridad=1),
        "decodificar64": FuncionNativa("decodificar64", decodificar64, aridad=1),
        "id_unico": FuncionNativa("id_unico", id_unico, aridad=0),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
