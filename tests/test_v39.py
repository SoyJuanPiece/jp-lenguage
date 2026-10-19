"""Tests de la v1.29 (segunda parte): finalmente en el motor en C.

El compilador nativo duplica el bloque 'finalmente' en cada camino
de salida (normal, atrapa, error sin atrapa con OP_RELANZAR 67, y
los devuelve/romper/continuar que lo cruzan), como el _intentar()
de la VM de Python, incluido el segundo centinela que protege al
propio atrapa.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.compilar_nativo import OP_RELANZAR, compilar_a_bytes  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

PROGRAMA = """funcion revisar(n) {
    intenta {
        si (n < 0) {
            lanzar "negativo"
        }
        devuelve "ok"
    } atrapa e {
        devuelve "atrapado: " + texto(e)
    } finalmente {
        muestra("limpieza")
    }
}
muestra(revisar(1))
muestra(revisar(-1))
variable pasos = ""
intenta {
    intenta {
        lanzar "adentro"
    } finalmente {
        pasos = pasos + "F"
    }
} atrapa e {
    pasos = pasos + "A"
}
muestra(pasos)
variable log = []
para i en 1..3 {
    intenta {
        log.agregar(i)
    } finalmente {
        log.agregar(i * 10)
    }
}
muestra(log)
"""


def salida_c(codigo: str) -> subprocess.CompletedProcess:
    blob = compilar_a_bytes(parsear(tokenizar(codigo)))
    with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
        archivo.write(blob)
        ruta = archivo.name
    return subprocess.run([str(MOTOR), ruta], capture_output=True, text=True, timeout=60)


@unittest.skipUnless(MOTOR.exists(), "Motor-c/jpvm sin compilar (make -C motor-c)")
class TestFinalmenteEnC(unittest.TestCase):
    def test_programa(self):
        r = salida_c(PROGRAMA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout,
            "limpieza\nok\nlimpieza\natrapado: negativo\nFA\n[1, 10, 2, 20, 3, 30]\n",
        )

    def test_error_atraviesa_finalmente(self):
        r = salida_c('intenta {\n lanzar "boom"\n} finalmente {\n muestra("fin")\n}\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "fin\n")
        self.assertIn("boom", r.stderr)


class TestSinMotorBinario(unittest.TestCase):
    def test_opcode(self):
        self.assertEqual(OP_RELANZAR, 67)


if __name__ == "__main__":
    unittest.main()
