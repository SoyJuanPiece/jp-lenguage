"""El lexer en C (`motor-c/lexer.c`) debe ser indistinguible del de Python.

Mismo orden de tokens, mismos lexemas, mismas líneas y columnas, mismos
errores. Es el primer trozo del frontend nativo: hasta que esta paridad no
esté verde, `jpvm` no puede leer un `.jp` sin Python.

Los tests se saltan si el binario no está compilado (`make -C motor-c jptokens`).
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))

import lexer_paridad as lp  # noqa: E402


class LexerCTest(unittest.TestCase):
    def setUp(self) -> None:
        self.binario = lp.binario()
        if not self.binario.is_file():
            self.skipTest("falta motor-c/jptokens: make -C motor-c jptokens")

    def _comparar_fuente(self, codigo: str):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "prueba.jp"
            ruta.write_text(codigo, encoding="utf-8")
            python_tokens, error_python = lp.tokens_python(ruta)
            c_tokens, error_c = lp.tokens_c(self.binario, ruta)
        return (python_tokens, error_python), (c_tokens, error_c)

    def test_todos_los_archivos_del_repositorio(self) -> None:
        with redirect_stdout(io.StringIO()) as salida, redirect_stderr(io.StringIO()):
            codigo = lp.main([])
        self.assertEqual(codigo, 0, salida.getvalue())

    def test_interpolacion_anidada(self) -> None:
        fuente = (
            'variable n = 2\n'
            'imprime("hola {n + 1}, tienes {n * 2} vidas y {"otra {n}"}")\n'
        )
        (python_tokens, error_python), (c_tokens, error_c) = self._comparar_fuente(fuente)
        self.assertIsNone(error_python)
        self.assertIsNone(error_c)
        self.assertIsNone(lp.comparar(python_tokens, c_tokens))

    def test_acentos_y_rangos(self) -> None:
        fuente = "variable año = 2026\npara i en 1..año paso 3 { imprime(i) }\n"
        (python_tokens, error_python), (c_tokens, error_c) = self._comparar_fuente(fuente)
        self.assertIsNone(error_python)
        self.assertIsNone(error_c)
        self.assertIsNone(lp.comparar(python_tokens, c_tokens))

    def test_mismo_error_en_misma_posicion(self) -> None:
        fuente = "variable x = 1\ny luego ! 2\n"
        (_, error_python), (_, error_c) = self._comparar_fuente(fuente)
        self.assertIsNotNone(error_python)
        self.assertIsNotNone(error_c)
        self.assertEqual(error_python[1:], error_c[1:])

    def test_cadena_sin_cerrar(self) -> None:
        fuente = 'imprime("sin cerrar)\n'
        (_, error_python), (_, error_c) = self._comparar_fuente(fuente)
        self.assertIsNotNone(error_python)
        self.assertIsNotNone(error_c)
        self.assertEqual(error_python[1:], error_c[1:])


if __name__ == "__main__":
    unittest.main()
