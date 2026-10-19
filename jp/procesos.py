"""Procesos para JP: concurrencia de verdad, a nivel de sistema.

El motor de JP ejecuta un programa tras otro, pero el sistema operativo
no: con estas funciones lanzas procesos hijos que corren EN PARALELO
(otros programas, otros .jp, lo que sea) y recoges su salida.

    variable p1 = iniciar_proceso(["python3", "-c", "print(1 + 1)"])
    variable p2 = iniciar_proceso(["echo", "hola"])
    imprime(esperar_proceso(p1).salida)   # "2"
    imprime(esperar_proceso(p2).codigo)   # 0

esperar_proceso devuelve {codigo, salida, errores, terminado}; `codigo`
es nulo si el proceso no termino (con limite) o lo terminaron.
"""

from __future__ import annotations

import subprocess

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto

_procesos: dict[int, subprocess.Popen] = {}
_siguiente = [1]


def _proceso(identificador: object) -> subprocess.Popen:
    if isinstance(identificador, bool) or not isinstance(identificador, int) or identificador not in _procesos:
        raise ErrorEjecucion("ese identificador no es un proceso iniciado con iniciar_proceso()")
    return _procesos[identificador]


def instalar(entorno: Entorno, invocar=None) -> None:
    def iniciar_proceso(comando: object) -> int:
        if isinstance(comando, str):
            partes = comando.split()
        elif isinstance(comando, list) and comando and all(isinstance(p, str) for p in comando):
            partes = list(comando)
        else:
            raise ErrorEjecucion(
                'iniciar_proceso() espera un comando como lista, ej: iniciar_proceso(["echo", "hola"])'
            )
        if not partes:
            raise ErrorEjecucion("iniciar_proceso() espera un comando no vacio")
        try:
            proceso = subprocess.Popen(
                partes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError:
            raise ErrorEjecucion(f"no se encontro el programa '{partes[0]}'")
        except OSError as error:
            raise ErrorEjecucion(f"no se pudo iniciar '{partes[0]}': {error}")
        identificador = _siguiente[0]
        _siguiente[0] += 1
        _procesos[identificador] = proceso
        return identificador

    def proceso_en_curso(identificador: object) -> bool:
        return _proceso(identificador).poll() is None

    def esperar_proceso(identificador: object, limite: object = None) -> dict:
        proceso = _proceso(identificador)
        if limite is not None and (isinstance(limite, bool) or not isinstance(limite, (int, float))):
            raise ErrorEjecucion("esperar_proceso() espera el limite en segundos (numero)")
        try:
            salida, errores = proceso.communicate(
                timeout=float(limite) if limite is not None else None
            )
            return {
                "codigo": proceso.returncode,
                "salida": salida,
                "errores": errores,
                "terminado": True,
            }
        except subprocess.TimeoutExpired:
            proceso.kill()
            salida, errores = proceso.communicate()
            return {
                "codigo": None,
                "salida": salida,
                "errores": errores,
                "terminado": False,
            }

    def terminar_proceso(identificador: object) -> bool:
        proceso = _proceso(identificador)
        if proceso.poll() is None:
            proceso.terminate()
        return True

    for nombre, funcion in {
        "iniciar_proceso": iniciar_proceso,
        "proceso_en_curso": proceso_en_curso,
        "esperar_proceso": esperar_proceso,
        "terminar_proceso": terminar_proceso,
    }.items():
        entorno.definir(nombre, FuncionNativa(nombre, funcion))
