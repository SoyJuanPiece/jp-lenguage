"""Tests de la v1.13: bases de datos SQLite (jp/basedatos.py)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from jp.errores import ErrorEjecucion
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


CRUD = """
variable bd = abrir_bd(":memory:")
bd_ejecutar(bd, "CREATE TABLE notas (titulo TEXT, puntos INTEGER)")
bd_ejecutar(bd, "INSERT INTO notas VALUES (?, ?)", ["pan", 3])
bd_ejecutar(bd, "INSERT INTO notas VALUES (?, ?)", ["o'clock", 10])
variable filas = bd_consultar(bd, "SELECT titulo, puntos FROM notas WHERE puntos > ? ORDER BY puntos", [5])
muestra(filas[0].titulo, filas[0].puntos, bd_ejecutar(bd, "UPDATE notas SET puntos = 4 WHERE titulo = 'pan'"))
bd_cerrar(bd)
"""


class TestBaseDatos(unittest.TestCase):
    def test_crud_con_parametros(self):
        # "o'clock" con comilla entra sin romper nada: van parametros aparte.
        self.assertEqual(paridad(CRUD), "o'clock 10 1\n")

    def test_bd_en_archivo(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = (Path(carpeta) / "x.db").as_posix()
            codigo = (
                f'variable bd = abrir_bd("{ruta}")\n'
                'bd_ejecutar(bd, "CREATE TABLE IF NOT EXISTS t (n INTEGER)")\n'
                'bd_ejecutar(bd, "DELETE FROM t")\n'
                'bd_ejecutar(bd, "INSERT INTO t VALUES (?)", [7])\n'
                "bd_cerrar(bd)\n"
                f'variable bd2 = abrir_bd("{ruta}")\n'
                'muestra(bd_consultar(bd2, "SELECT n FROM t")[0].n)\n'
                "bd_cerrar(bd2)"
            )
            self.assertEqual(paridad(codigo), "7\n")

    def test_errores_amigables(self):
        for maquina in (MaquinaVM, Interprete):
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina(), 'variable bd = abrir_bd(":memory:")\nbd_consultar(bd, "SELECT * FROM no_existe")')
            with self.assertRaises(ErrorEjecucion):
                ejecutar_en(maquina(), "bd_consultar(99, 'SELECT 1')")


if __name__ == "__main__":
    unittest.main()
