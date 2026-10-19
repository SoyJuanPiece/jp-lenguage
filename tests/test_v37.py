"""Tests de la v1.28: jp --cobertura."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.cobertura import InformeCobertura, lineas_ejecutables, medir  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

RAMAS = """funcion clasificar(n) {
    si (n > 0) {
        devuelve "positivo"
    } sino {
        devuelve "no positivo"
    }
}
muestra(clasificar(5))
"""


class TestCobertura(unittest.TestCase):
    def test_rama_sin_cubrir(self):
        informe = medir(parsear(tokenizar(RAMAS)), directorio=str(RAIZ))
        self.assertIn(3, informe.ejecutadas)
        self.assertIn(5, informe.faltantes)
        self.assertLess(informe.porcentaje, 100.0)

    def test_todo_cubierto(self):
        informe = medir(parsear(tokenizar(RAMAS.replace("clasificar(5)", "clasificar(-1)"))),
                        directorio=str(RAIZ))
        # con -1 se cubre el 'sino' pero no el 'entonces'
        self.assertIn(3, informe.faltantes)

    def test_ejecutables(self):
        ejecutables = lineas_ejecutables(parsear(tokenizar("variable a = 1\nmuestra(a)\n")))
        self.assertEqual(ejecutables, {1, 2})

    def test_informe_texto(self):
        informe = InformeCobertura(ejecutables={1, 2, 3, 4}, ejecutadas={1, 2, 4})
        texto = informe.texto("x.jp")
        self.assertIn("75%", texto)
        self.assertIn("3", texto)

    def test_cli(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jp", delete=False) as archivo:
            archivo.write(RAMAS)
            ruta = archivo.name
        resultado = subprocess.run(
            [sys.executable, "-m", "jp", "--cobertura", ruta],
            capture_output=True, text=True, cwd=str(RAIZ), timeout=60,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("positivo", resultado.stdout)
        self.assertIn("Cobertura", resultado.stdout)
        self.assertIn("Sin ejecutar", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
