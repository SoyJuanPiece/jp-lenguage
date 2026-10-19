"""Tests de la v1.18: el formateador (jp/formateador.py y --formatear)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jp.formateador import formatear
from jp.lexer import tokenizar
from jp.parser import parsear

RAIZ = Path(__file__).resolve().parent.parent


def dar_formato(codigo: str) -> str:
    return formatear(parsear(tokenizar(codigo)))


class TestFormateador(unittest.TestCase):
    def test_estilo_basico(self):
        codigo = 'variable   x=1\nsi x>0{imprime("si")}sino{imprime("no")}'
        self.assertEqual(
            dar_formato(codigo),
            'variable x = 1\nsi x > 0 {\n    imprime("si")\n} sino {\n    imprime("no")\n}\n',
        )

    def test_conserva_operadores_nuevos(self):
        codigo = "variable u = {dir: nulo}\nimprime(u?.dir?.ciudad ?? \"sin\")"
        salida = dar_formato(codigo)
        self.assertIn('u?.dir?.ciudad ?? "sin"', salida)
        self.assertEqual(dar_formato(salida), salida)

    def test_todo_el_corpus_es_idempotente(self):
        archivos = (
            sorted((RAIZ / "ejemplos").glob("*.jp"))
            + sorted((RAIZ / "biblioteca").glob("*.jp"))
            + sorted((RAIZ / "pruebas").glob("*.jp"))
        )
        self.assertGreater(len(archivos), 40)
        for ruta in archivos:
            with self.subTest(archivo=ruta.name):
                una = dar_formato(ruta.read_text(encoding="utf-8"))
                self.assertEqual(dar_formato(una), una)

    def test_cli_formatear_y_en_sitio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "feo.jp"
            ruta.write_text('variable   x=1\nimprime(x)', encoding="utf-8")
            ver = subprocess.run(
                [sys.executable, "-m", "jp", "--formatear", str(ruta)],
                cwd=str(RAIZ), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(ver.returncode, 0, ver.stderr)
            self.assertEqual(ver.stdout, "variable x = 1\nimprime(x)\n")
            self.assertIn("variable   x=1", ruta.read_text(encoding="utf-8"))  # intacto
            grabar = subprocess.run(
                [sys.executable, "-m", "jp", "--formatear", "--en-sitio", str(ruta)],
                cwd=str(RAIZ), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(grabar.returncode, 0, grabar.stderr)
            self.assertEqual(ruta.read_text(encoding="utf-8"), "variable x = 1\nimprime(x)\n")


if __name__ == "__main__":
    unittest.main()
