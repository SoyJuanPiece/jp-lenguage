"""Tests de la v1.14: operadores '??' (si es nulo) y '?.' (acceso seguro)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.compilar_nativo import compilar_a_bytes
from jp.errores import ErrorJP
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


class TestPorDefecto(unittest.TestCase):
    def test_solo_nulo_dispara(self):
        self.assertEqual(
            paridad('muestra(nulo ?? "defecto", 5 ?? 9, falso ?? "no", 0 ?? "no", nulo ?? nulo ?? 3)'),
            "defecto 5 falso 0 3\n",
        )

    def test_cortocircuito_real(self):
        codigo = (
            "variable marcas = 0\n"
            "funcion marcar() { marcas = marcas + 1; devuelve \"m\" }\n"
            "muestra(nulo ?? marcar(), 7 ?? marcar(), marcas)\n"
        )
        self.assertEqual(paridad(codigo), "m 7 1\n")


class TestAccesoSeguro(unittest.TestCase):
    def test_cadenas_con_nulos(self):
        codigo = (
            'variable u = {nombre: "Ana", dir: nulo, tel: {numero: 123}}\n'
            "muestra(u?.nombre, u?.dir?.ciudad, u?.tel?.numero, u?.tel.numero)\n"
            "variable f = nulo\n"
            "muestra(f?.(), f?.metodo(1, 2))\n"
        )
        self.assertEqual(paridad(codigo), "Ana nulo 123 123\nnulo nulo\n")

    def test_sin_interrogacion_sigue_fallando(self):
        for maquina in (MaquinaVM, Interprete):
            with self.assertRaises(ErrorJP):
                ejecutar_en(maquina(), "variable u = {dir: nulo}\nmuestra(u.dir.ciudad)")

    def test_asignar_a_seguro_es_error_de_sintaxis(self):
        with self.assertRaises(ErrorJP):
            parsear(tokenizar("variable u = {a: 1}\nu?.a = 2"))

    def test_motor_c_lo_compila(self):
        # Desde la v1.16 el motor en C tambien sabe ?? y ?.: compila sin
        # rechazar (opcode SALTO_NO_NULO_MANTENER en jpvm.c).
        for codigo in ("variable x = nulo ?? 3", "variable u = {a: nulo}\nvariable z = u?.a"):
            self.assertTrue(compilar_a_bytes(parsear(tokenizar(codigo)), "prueba"))

    @unittest.skipUnless((RAIZ / "motor-c" / "jpvm").exists(), "motor en C sin compilar")
    def test_motor_c_lo_ejecuta_igual(self):
        import subprocess
        import sys
        import tempfile
        codigo = (
            'variable u = {nombre: "Ana", dir: nulo}\n'
            'muestra(nulo ?? "defecto", 5 ?? 9, u?.nombre, u?.dir?.ciudad, u?.dir?.ciudad ?? "sin")\n'
        )
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "seguro.jp"
            ruta.write_text(codigo, encoding="utf-8")
            resultado = subprocess.run(
                [sys.executable, "-m", "jp", "--c", str(ruta)],
                cwd=str(RAIZ), capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(resultado.stdout, "defecto 5 Ana nulo sin\n")


if __name__ == "__main__":
    unittest.main()
