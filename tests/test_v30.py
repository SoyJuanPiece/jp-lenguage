"""Tests de la v1.21: paquetes JP (jp/paquetes.py, importar "@x", --instalar).

Sin red: los paquetes de prueba se instalan desde carpetas locales.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from jp import paquetes
from jp.errores import ErrorEjecucion
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM

RAIZ = Path(__file__).resolve().parent.parent


def ejecutar_en(maquina, codigo: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


def crear_paquete(carpeta: Path, nombre: str = "pruebax") -> Path:
    origen = carpeta / nombre
    origen.mkdir(parents=True)
    (origen / "paquete.json").write_text(
        json.dumps({"nombre": nombre, "version": "2.0.0", "principal": "principal.jp"}),
        encoding="utf-8",
    )
    (origen / "principal.jp").write_text(
        'funcion saludar(nombre) { devuelve "hola " + nombre }\n', encoding="utf-8")
    return origen


class TestPaquetes(unittest.TestCase):
    def test_instalar_local_e_importar_con_arroba(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            origen = crear_paquete(raiz)
            destino = raiz / "instalados"
            self.assertEqual(paquetes.instalar(str(origen), destino), "pruebax")
            with mock.patch.dict(os.environ, {"JP_PAQUETES": str(destino)}):
                self.assertEqual(
                    paridad('importar "@pruebax" como p\nmuestra(p.saludar("Luz"))'),
                    "hola Luz\n",
                )
                with self.assertRaises(ErrorEjecucion):
                    ejecutar_en(MaquinaVM(), 'importar "@no_existe" como x')

    def test_repo_trae_el_primer_paquete(self):
        # paquetes/saludos vive en el propio repo: importar sin instalar nada
        # cuando el directorio de trabajo es la raiz del repo.
        self.assertTrue((RAIZ / "paquetes" / "saludos" / "paquete.json").is_file())


class TestCliPaquetes(unittest.TestCase):
    def correr(self, argumentos, cwd):
        entorno = dict(os.environ, PYTHONPATH=str(RAIZ))
        return subprocess.run(
            [sys.executable, "-m", "jp", *argumentos],
            cwd=str(cwd), env=entorno, capture_output=True, text=True, timeout=60,
        )

    def test_instalar_listar_quitar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            origen = crear_paquete(raiz)
            instalado = self.correr(["--instalar", str(origen), "--aqui"], raiz)
            self.assertEqual(instalado.returncode, 0, instalado.stderr)
            self.assertTrue((raiz / "paquetes" / "pruebax" / "principal.jp").is_file())

            lista = self.correr(["--paquetes"], raiz)
            self.assertIn("pruebax 2.0.0", lista.stdout)

            quitado = self.correr(["--quitar-paquete", "pruebax"], raiz)
            self.assertEqual(quitado.returncode, 0, quitado.stderr)
            self.assertFalse((raiz / "paquetes" / "pruebax").exists())

    def test_instalar_dependencias_del_manifiesto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            origen = crear_paquete(raiz)
            (raiz / "paquete.json").write_text(
                json.dumps({"dependencias": {"pruebax": str(origen)}}), encoding="utf-8")
            resultado = self.correr(["--instalar", "--aqui"], raiz)
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertTrue((raiz / "paquetes" / "pruebax").is_dir())


if __name__ == "__main__":
    unittest.main()
