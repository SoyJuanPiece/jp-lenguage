"""Tests de la v1.24: el revisor estatico (jp/revisor.py y --revisar)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jp.lexer import tokenizar
from jp.parser import parsear
from jp.revisor import revisar

RAIZ = Path(__file__).resolve().parent.parent


def avisos_de(codigo: str) -> list[str]:
    return revisar(parsear(tokenizar(codigo)))


class TestRevisor(unittest.TestCase):
    def test_detecta_los_tres_problemas(self):
        avisos = avisos_de(
            "variable olvidada = 2\n"
            "funcion suma(a, b) { devuelve a + b }\n"
            "imprime(suma(1, fantasma))\n"
            "suelta = 5\n"
        )
        texto = "\n".join(avisos)
        self.assertIn("'fantasma' no está declarada", texto)
        self.assertIn("asignas a 'suelta' sin declararla", texto)
        self.assertIn("'olvidada' se declara y nunca se usa", texto)

    def test_programa_limpio_sin_avisos(self):
        self.assertEqual(
            avisos_de("variable x = 1\nfuncion doble(n) { devuelve n * 2 }\nimprime(doble(x))"),
            [],
        )

    def test_guion_bajo_no_acusa(self):
        self.assertEqual(avisos_de("variable _temporal = 1\nimprime(2)"), [])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "sucio.jp"
            ruta.write_text("imprime(fantasma)\n", encoding="utf-8")
            resultado = subprocess.run(
                [sys.executable, "-m", "jp", "--revisar", str(ruta)],
                cwd=str(RAIZ), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(resultado.returncode, 1)
            self.assertIn("fantasma", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
