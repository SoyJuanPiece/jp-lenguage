"""Bases de datos SQLite para JP: guardar datos de verdad, sin servidor.

    variable bd = abrir_bd("notas.db")          # o ":memory:" para pruebas
    bd_ejecutar(bd, "CREATE TABLE IF NOT EXISTS notas (titulo TEXT, puntos INTEGER)")
    bd_ejecutar(bd, "INSERT INTO notas VALUES (?, ?)", ["comprar pan", 3])
    variable filas = bd_consultar(bd, "SELECT * FROM notas WHERE puntos > ?", [1])
    bd_cerrar(bd)

bd_consultar devuelve una lista de diccionarios (columna -> valor), lista
para recorrerla o volcarla a una Tabla. Los parametros van aparte (con ?)
para que un texto con comillas nunca rompa la consulta.
"""

from __future__ import annotations

import sqlite3

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa

_conexiones: dict[int, sqlite3.Connection] = {}
_siguiente = [1]


def _conexion(bd: object) -> sqlite3.Connection:
    if isinstance(bd, bool) or not isinstance(bd, int) or bd not in _conexiones:
        raise ErrorEjecucion("ese identificador no es una base de datos abierta con abrir_bd()")
    return _conexiones[bd]


def _sql_y_params(args: tuple, funcion: str) -> tuple[str, list]:
    if len(args) not in (2, 3):
        raise ErrorEjecucion(f"{funcion}() espera (bd, sql) o (bd, sql, parametros)")
    sql = args[1]
    if not isinstance(sql, str) or not sql.strip():
        raise ErrorEjecucion(f"{funcion}() espera el SQL como texto")
    params = args[2] if len(args) == 3 else []
    if not isinstance(params, list):
        raise ErrorEjecucion(f"{funcion}() espera los parametros como lista, ej: [1, \"Ana\"]")
    return sql, params


def instalar(entorno: Entorno, invocar=None) -> None:
    def abrir_bd(ruta: object) -> int:
        if not isinstance(ruta, str) or not ruta:
            raise ErrorEjecucion('abrir_bd() espera la ruta, ej: abrir_bd("notas.db") o abrir_bd(":memory:")')
        try:
            conexion = sqlite3.connect(ruta)
        except sqlite3.Error as error:
            raise ErrorEjecucion(f"abrir_bd() no pudo abrir '{ruta}': {error}")
        identificador = _siguiente[0]
        _siguiente[0] += 1
        _conexiones[identificador] = conexion
        return identificador

    def bd_ejecutar(*args: object) -> int:
        conexion = _conexion(args[0] if args else None)
        sql, params = _sql_y_params(args, "bd_ejecutar")
        try:
            cursor = conexion.execute(sql, params)
            conexion.commit()
        except sqlite3.Error as error:
            raise ErrorEjecucion(f"error en la base de datos: {error}")
        return cursor.rowcount

    def bd_consultar(*args: object) -> list:
        conexion = _conexion(args[0] if args else None)
        sql, params = _sql_y_params(args, "bd_consultar")
        try:
            cursor = conexion.execute(sql, params)
            columnas = [d[0] for d in cursor.description or []]
            filas = []
            for fila in cursor.fetchall():
                registro = {}
                for nombre, valor in zip(columnas, fila):
                    if isinstance(valor, bytes):
                        valor = valor.decode("utf-8", "replace")
                    registro[nombre] = valor
                filas.append(registro)
        except sqlite3.Error as error:
            raise ErrorEjecucion(f"error en la base de datos: {error}")
        return filas

    def bd_cerrar(bd: object) -> bool:
        conexion = _conexion(bd)
        conexion.close()
        del _conexiones[bd]  # type: ignore[arg-type]
        return True

    for nombre, funcion in {
        "abrir_bd": abrir_bd,
        "bd_ejecutar": bd_ejecutar,
        "bd_consultar": bd_consultar,
        "bd_cerrar": bd_cerrar,
    }.items():
        entorno.definir(nombre, FuncionNativa(nombre, funcion))
