"""Tests de la v1.17: el depurador paso a paso `jp --depurar`."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

PROGRAMA = "variable x = 41\nvariable z = x + 1\nmuestra(z)\n"


def depurar(entrada: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "prog.jp"
        ruta.write_text(PROGRAMA, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "jp", "--depurar", str(ruta)],
            cwd=str(RAIZ), input=entrada, capture_output=True, text=True, timeout=60,
        )


class TestDepurador(unittest.TestCase):
    def test_paso_ver_y_continuar(self):
        resultado = depurar("s\nv x\nc\n")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("x = 41", resultado.stdout)
        self.assertIn("42", resultado.stdout)

    def test_sin_terminal_no_se_bloquea(self):
        resultado = depurar("")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("42", resultado.stdout)

    def test_punto_de_interrupcion_y_salir(self):
        resultado = depurar("p 3\nc\nq\n")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("punto de interrupcion en la linea 3", resultado.stdout)
        self.assertIn("depuración terminada", resultado.stdout)
        self.assertNotIn("> 42", resultado.stdout)  # salio antes del muestra


if __name__ == "__main__":
    unittest.main()
