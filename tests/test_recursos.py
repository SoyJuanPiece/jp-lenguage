"""Recursos: que `jp` encuentre su biblioteca y su motor esté donde toca.

Estos tests son los que impiden que la versión instalada con pip se rompa:
si `biblioteca/` o `motor-c/` dejan de viajar en el paquete, `jp --proyecto`,
`jp --c` y `jp --binario` fallan en la máquina del usuario y no en el CI.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp import recursos
from jp.cli import _salida_utf8, main


class RecursosTest(unittest.TestCase):
    def test_raiz_tiene_biblioteca_y_motor(self) -> None:
        raiz = recursos.raiz()
        self.assertTrue((raiz / "biblioteca").is_dir(), raiz)
        self.assertTrue((raiz / "motor-c").is_dir(), raiz)

    def test_archivo_resuelve_un_recurso_real(self) -> None:
        self.assertTrue(recursos.archivo("biblioteca", "pruebas.jp").is_file())
        self.assertTrue(recursos.archivo("motor-c", "jpvm.c").is_file())

    def test_binario_motor_es_ejecutable_con_nombre(self) -> None:
        motor = recursos.binario_motor()
        self.assertIn(motor.name, ("jpvm", "jpvm.exe"))

    def test_jp_raiz_manda(self) -> None:
        anterior = recursos.os.environ.get("JP_RAIZ")
        try:
            recursos.os.environ["JP_RAIZ"] = tempfile.gettempdir()
            self.assertEqual(recursos.raiz(), Path(tempfile.gettempdir()))
        finally:
            if anterior is None:
                recursos.os.environ.pop("JP_RAIZ", None)
            else:
                recursos.os.environ["JP_RAIZ"] = anterior


class SalidaTest(unittest.TestCase):
    def test_salida_utf8_no_rompe_con_flujos_falsos(self) -> None:
        # En los tests la salida es un StringIO: no tiene reconfigure y no debe
        # estallar por eso.
        with redirect_stdout(io.StringIO()):
            _salida_utf8()


class ProyectoTest(unittest.TestCase):
    def test_proyecto_nuevo_se_crea_completo(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "demo"
            with redirect_stdout(io.StringIO()):
                codigo = main(["--proyecto", str(destino)])
            self.assertEqual(codigo, 0)
            self.assertTrue((destino / "principal.jp").is_file())
            self.assertTrue((destino / "LEEME.md").is_file())
            self.assertTrue((destino / "pruebas" / "pruebas.jp").is_file())
            self.assertTrue((destino / "pruebas" / "principal_prueba.jp").is_file())


if __name__ == "__main__":
    sys.exit(unittest.main())
