"""Tests del modo turbo (jp.turbo): cache total de programas puros.

Ejecutar con:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import jp.turbo as turbo
from jp.turbo import ejecutar_turbo


class TestTurbo(unittest.TestCase):
    def setUp(self):
        turbo._MEMO.clear()
        self.carpeta = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.carpeta.name, "programa.jp")
        self.addCleanup(self.carpeta.cleanup)

    def _escribir(self, fuente: str) -> None:
        with open(self.ruta, "w", encoding="utf-8") as archivo:
            archivo.write(fuente)

    def _correr(self, fuente: str) -> tuple[str, bool, str]:
        """Devuelve (stdout, ok, stderr)."""
        self._escribir(fuente)
        buffer = io.StringIO()
        errores = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(errores):
            ok = ejecutar_turbo(self.ruta, fuente)
        return buffer.getvalue(), ok, errores.getvalue()

    def test_puro_cachea_y_repite(self):
        fuente = 'muestra("hola turbo")\nmuestra(2 + 3)\n'
        salida1, ok1, _ = self._correr(fuente)
        self.assertTrue(ok1)
        self.assertEqual(salida1, "hola turbo\n5\n")
        self.assertTrue(os.path.exists(self.ruta + ".jpc"))
        salida2, ok2, _ = self._correr(fuente)  # desde cache/memo
        self.assertEqual((salida2, ok2), (salida1, True))
        self.addCleanup(lambda: os.path.exists(self.ruta + ".jpc") and os.remove(self.ruta + ".jpc"))

    def test_cambiar_fuente_invalida_cache(self):
        salida1, _, _ = self._correr('muestra(1)\n')
        salida2, _, _ = self._correr('muestra(2)\n')
        self.assertEqual(salida1, "1\n")
        self.assertEqual(salida2, "2\n")
        self.addCleanup(lambda: os.path.exists(self.ruta + ".jpc") and os.remove(self.ruta + ".jpc"))

    def test_impuro_no_cachea(self):
        salida, ok, _ = self._correr('muestra(azar(5))\n')  # usa azar -> impuro
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.ruta + ".jpc"))
        self._correr('muestra(azar(5))\n')
        self.assertFalse(os.path.exists(self.ruta + ".jpc"))

    def test_leer_es_impuro(self):
        # el mock ecoa el prompt sin salto (como el terminal real)
        def input_falso(prompt=""):
            print(prompt, end="")
            return "ana"

        with mock.patch("builtins.input", side_effect=input_falso):
            salida, ok, _ = self._correr('variable n = leer("nombre: ")\nmuestra(n)')
        self.assertEqual(salida, "nombre: ana\n")
        self.assertFalse(os.path.exists(self.ruta + ".jpc"))

    def test_error_se_cachea_con_exit_false(self):
        salida, ok, errores = self._correr('muestra(1 / 0)\n')
        self.assertFalse(ok)
        self.assertIn("división por cero", errores)
        salida2, ok2, errores2 = self._correr('muestra(1 / 0)\n')
        self.assertFalse(ok2)
        self.assertIn("división por cero", errores2)

    def test_memoria_mas_rapida_que_disco(self):
        # sanity: tras calentar, el hit en memoria debe ser de microsegundos
        fuente = 'muestra(1 + 1)\n'
        self._correr(fuente)
        import time

        t0 = time.perf_counter()
        for _ in range(100):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                ejecutar_turbo(self.ruta, fuente)
        transcurrido = time.perf_counter() - t0
        self.assertLess(transcurrido / 100, 0.001)  # < 1 ms por corrida
        self.addCleanup(lambda: os.path.exists(self.ruta + ".jpc") and os.remove(self.ruta + ".jpc"))


if __name__ == "__main__":
    unittest.main()
