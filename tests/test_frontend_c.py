"""El frontend en C (lexer + parser + compilador) debe ser indistinguible del de Python.

Tres niveles, en este orden: mismo AST, mismo bytecode byte a byte, y `jpvm`
ejecutando un `.jp` sin que Python intervenga.

Los tests se saltan si los binarios no están compilados (`make -C motor-c`).
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))

import ast_paridad  # noqa: E402
import jpb_paridad  # noqa: E402


def ejecutable(nombre: str, variable: str) -> Path:
    ruta = os.environ.get(variable)
    if ruta:
        return Path(ruta)
    sufijo = ".exe" if os.name == "nt" else ""
    return RAIZ / "motor-c" / f"{nombre}{sufijo}"


class FrontendCTest(unittest.TestCase):
    def setUp(self) -> None:
        self.jpast = ejecutable("jpast", "JPAST")
        self.jpcompilar = ejecutable("jpcompilar", "JPCOMPILAR")
        self.jpvm = ejecutable("jpvm", "JPVM")
        for ruta in (self.jpast, self.jpcompilar, self.jpvm):
            if not ruta.is_file():
                self.skipTest("faltan los binarios del motor: make -C motor-c")

    def test_mismo_ast_en_todos_los_archivos(self) -> None:
        with redirect_stdout(io.StringIO()) as salida, redirect_stderr(io.StringIO()):
            codigo = ast_paridad.main([])
        self.assertEqual(codigo, 0, salida.getvalue())

    def test_mismo_bytecode_byte_a_byte(self) -> None:
        with redirect_stdout(io.StringIO()) as salida, redirect_stderr(io.StringIO()):
            codigo = jpb_paridad.main([])
        self.assertEqual(codigo, 0, salida.getvalue())

    def test_jpvm_ejecuta_un_jp_sin_python(self) -> None:
        proceso = subprocess.run(
            [str(self.jpvm), str(RAIZ / "ejemplos" / "hola.jp")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        self.assertIn("¡Hola, mundo!", proceso.stdout)
        self.assertIn("10 + 4 = 14", proceso.stdout)

    def test_jpvm_da_lo_mismo_con_jp_y_con_jpb(self) -> None:
        fuente = RAIZ / "ejemplos" / "fibonacci.jp"
        with tempfile.TemporaryDirectory() as carpeta:
            blob = Path(carpeta) / "fibonacci.jpb"
            compilado = subprocess.run(
                [str(self.jpcompilar), str(fuente), str(blob)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(compilado.returncode, 0, compilado.stderr)
            desde_jp = subprocess.run(
                [str(self.jpvm), str(fuente)], capture_output=True, text=True, encoding="utf-8"
            )
            desde_jpb = subprocess.run(
                [str(self.jpvm), str(blob)], capture_output=True, text=True, encoding="utf-8"
            )
        self.assertEqual(desde_jp.returncode, 0, desde_jp.stderr)
        self.assertEqual(desde_jp.stdout, desde_jpb.stdout)
        self.assertIn("fib(10) = 55", desde_jp.stdout)

    def test_error_de_sintaxis_apunta_a_la_misma_linea(self) -> None:
        from jp.errores import ErrorJP
        from jp.lexer import tokenizar
        from jp.parser import parsear

        codigo = "variable x = 1\nsi { }\n"
        try:
            parsear(tokenizar(codigo))
        except ErrorJP as error:
            esperado = f"{error.mensaje}|{error.linea}|{error.columna}"
        else:
            self.fail("el parser de Python debería rechazar este programa")

        with tempfile.TemporaryDirectory() as carpeta:
            roto = Path(carpeta) / "roto.jp"
            roto.write_text(codigo, encoding="utf-8")
            proceso = subprocess.run(
                [str(self.jpvm), str(roto)], capture_output=True, text=True, encoding="utf-8"
            )
        self.assertNotEqual(proceso.returncode, 0)
        self.assertIn(esperado, proceso.stderr)


if __name__ == "__main__":
    unittest.main()
