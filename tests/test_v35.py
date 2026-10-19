"""Tests de la v1.26: desestructurar en el motor en C.

`para a, b en` (índice/valor o clave/valor) con ITER_NEXT_PAR (59) y
su variante con celdas (60), y `variable [a, b] = ...` / `[a, b] = ...`
con DESESTRUCTURAR (61). Todo coincide con la VM de Python.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import (  # noqa: E402
    OP_DESESTRUCTURAR,
    OP_ITER_NEXT_PAR,
    compilar_a_bytes,
)
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

PROGRAMA = """
variable lista = ["a", "b", "c"]
variable suma = 0
para i, v en lista {
    suma += i
    muestra(i, v)
}
para k, val en {"uno": 1, "dos": 2} {
    muestra(k, val)
}
variable [x, z] = [10, 20]
muestra(x + z)
[x, z] = [z, x]
muestra(x, z)
variable fns = []
para i, v en [10, 20] {
    fns.agregar(funcion() { devuelve i + v })
}
para f en fns {
    muestra(f())
}
"""


def salida_c(codigo: str) -> subprocess.CompletedProcess:
    blob = compilar_a_bytes(parsear(tokenizar(codigo)))
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta = archivo.name
    return subprocess.run([str(MOTOR), ruta], capture_output=True, timeout=60)


@unittest.skipUnless(MOTOR.exists(), "Motor-c/jpvm sin compilar (make -C motor-c)")
class TestDesestructurarEnC(unittest.TestCase):
    def test_programa_completo(self):
        import io
        from contextlib import redirect_stdout

        from jp.vm import MaquinaVM

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MaquinaVM().ejecutar(parsear(tokenizar(PROGRAMA)), directorio=str(RAIZ))
        resultado = salida_c(PROGRAMA)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode())
        self.assertEqual(resultado.stdout.decode(), buffer.getvalue())

    def test_largo_incorrecto_es_error(self):
        resultado = salida_c("variable [a, b] = [1]\n")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("esperaba 2", resultado.stderr.decode() + resultado.stdout.decode())

    def test_no_lista_es_error(self):
        resultado = salida_c("variable [a, b] = 42\n")
        self.assertNotEqual(resultado.returncode, 0)


class TestOpcodes(unittest.TestCase):
    def test_numeracion(self):
        self.assertEqual((OP_ITER_NEXT_PAR, OP_DESESTRUCTURAR), (59, 61))


if __name__ == "__main__":
    unittest.main()
