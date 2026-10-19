"""Tests de la v1.20: `jp --proyecto` crea proyectos que ya funcionan."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def correr(argumentos: list[str], cwd: Path) -> subprocess.CompletedProcess:
    entorno = dict(os.environ, PYTHONPATH=str(RAIZ))
    return subprocess.run(
        [sys.executable, "-m", "jp", *argumentos],
        cwd=str(cwd), env=entorno, capture_output=True, text=True, timeout=60,
    )


class TestProyecto(unittest.TestCase):
    def test_proyecto_nuevo_corre_y_pasa_sus_pruebas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            creado = correr(["--proyecto", "miapp"], raiz)
            self.assertEqual(creado.returncode, 0, creado.stderr)
            self.assertTrue((raiz / "miapp" / "principal.jp").is_file())
            self.assertTrue((raiz / "miapp" / "pruebas" / "principal_prueba.jp").is_file())

            programa = correr(["miapp/principal.jp"], raiz)
            self.assertEqual(programa.returncode, 0, programa.stderr)
            self.assertIn("¡Hola desde miapp!", programa.stdout)

            pruebas = correr(["--probar"], raiz / "miapp")
            self.assertEqual(pruebas.returncode, 0, pruebas.stderr)
            self.assertIn("1/1 archivos de prueba pasan", pruebas.stdout)

    def test_no_sobreescribe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            self.assertEqual(correr(["--proyecto", "miapp"], raiz).returncode, 0)
            self.assertEqual(correr(["--proyecto", "miapp"], raiz).returncode, 66)


if __name__ == "__main__":
    unittest.main()
