"""Tests de la v1.15: biblioteca/pruebas.jp y el comando `jp --probar`."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM

RAIZ = Path(__file__).resolve().parent.parent


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=str(RAIZ))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


def correr_cli(argumentos: list[str], cwd: Path) -> subprocess.CompletedProcess:
    entorno = dict(os.environ, PYTHONPATH=str(RAIZ))
    return subprocess.run(
        [sys.executable, "-m", "jp", *argumentos],
        cwd=str(cwd), env=entorno, capture_output=True, text=True, timeout=60,
    )


class TestPruebasJP(unittest.TestCase):
    def test_afirmaciones_con_paridad(self):
        codigo = (
            'importar "biblioteca/pruebas.jp" como p\n'
            "p.afirmar_igual(4, 2 + 2)\n"
            "p.afirmar_casi(0.3, 0.1 + 0.2)\n"
            "p.afirmar_error(funcion() { lanzar \"boom\" })\n"
            "p.resumen()\n"
        )
        self.assertEqual(paridad(codigo), "3/3 afirmaciones bien\n")


class TestCliProbar(unittest.TestCase):
    def test_probar_el_demo_del_repo(self):
        resultado = correr_cli(["--probar", "pruebas/mates_prueba.jp"], RAIZ)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("1/1 archivos de prueba pasan", resultado.stdout)

    def test_descubre_y_detecta_fallos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            (raiz / "pruebas").mkdir()
            (raiz / "pruebas" / "bien_prueba.jp").write_text(
                'importar "' + (RAIZ / "biblioteca" / "pruebas.jp").as_posix() + '" como p\n'
                "p.afirmar_igual(2, 1 + 1)\np.resumen()\n",
                encoding="utf-8",
            )
            (raiz / "pruebas" / "mal_prueba.jp").write_text(
                'importar "' + (RAIZ / "biblioteca" / "pruebas.jp").as_posix() + '" como p\n'
                "p.afirmar_igual(3, 1 + 1)\np.resumen()\n",
                encoding="utf-8",
            )
            resultado = correr_cli(["--probar"], raiz)
            self.assertEqual(resultado.returncode, 1)
            self.assertIn("1/2 archivos de prueba pasan", resultado.stdout)
            self.assertIn("se esperaba 3 pero se obtuvo 2", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
