"""Tests de F3: el bloque `externo` (FFI) del motor en C.

La puerta de F3 son los programas de `pruebas/f3/`: llaman a funciones reales
del runtime de C (abs, strlen, strcmp, malloc, memset, free, getenv, time) con
entero, texto, puntero y nulo de ida y vuelta. Aquí se ejecutan y se compara la
salida, más los casos de error (símbolo que no existe, biblioteca que no existe)
y el aviso del motor de Python, que entiende la sintaxis pero no la ejecuta.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jp.errores import ErrorSintaxis  # noqa: E402
from jp.interprete import ErrorEjecucion, Interprete  # noqa: E402
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

PUERTAS = RAIZ / "pruebas" / "f3"


def _motor_c() -> Path:
    ruta = os.environ.get("JPVM")
    if ruta:
        return Path(ruta)
    sufijo = ".exe" if os.name == "nt" else ""
    return RAIZ / "motor-c" / f"jpvm{sufijo}"


MOTOR = _motor_c()
if not MOTOR.is_file():
    raise unittest.SkipTest("motor en C sin compilar (make -C motor-c)")


def _correr(fuente: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "programa.jp"
        ruta.write_text(fuente, encoding="utf-8", newline="\n")
        return subprocess.run(
            [str(MOTOR), str(ruta)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
        )


def _salida(fuente: str) -> str:
    proceso = _correr(fuente)
    return proceso.stdout.replace("\r\n", "\n"), proceso


# Salida esperada de cada programa-puerta.
ESPERADO = {
    "01-entero.jp": "42\n42\n0\n",
    "02-texto.jp": "4\n0\n8\nverdadero\nverdadero\n",
    "03-puntero.jp": "puntero\nverdadero\nverdadero\nfin\n",
    "04-nulo.jp": "texto\nverdadero\nverdadero\n",
    "05-errores.jp": "atrapado\natrapado\nsigue vivo\n",
    "06-tiempo.jp": "número\nverdadero\nverdadero\n",
    "07-memoria.jp": "hola desde C\n12\nverdadero\nverdadero\nliberado\n",
}


class PuertasF3(unittest.TestCase):
    def test_los_programas_puerta_corren(self) -> None:
        for nombre, esperado in ESPERADO.items():
            with self.subTest(programa=nombre):
                ruta = PUERTAS / nombre
                self.assertTrue(ruta.is_file(), f"falta {ruta}")
                proceso = subprocess.run(
                    [str(MOTOR), str(ruta)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                self.assertEqual(proceso.returncode, 0, proceso.stderr)
                self.assertEqual(proceso.stdout.replace("\r\n", "\n"), esperado)

    def test_puntero_es_un_tipo_mas(self) -> None:
        salida, proceso = _salida(
            'externo "c" {\n'
            "    funcion malloc(n: entero) -> puntero\n"
            "    funcion free(p: puntero)\n"
            "}\n"
            "variable p: puntero = malloc(8)\n"
            'imprime(tipo(p))\n'
            "variable q: puntero = nulo\n"
            'imprime(tipo(q))\n'
            "free(p)\n"
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        self.assertEqual(salida, "puntero\nnulo\n")

    def test_el_entero_no_se_puede_colar_como_puntero(self) -> None:
        _, proceso = _salida(
            'externo "c" {\n'
            "    funcion free(p: puntero)\n"
            "}\n"
            "free(42)\n"
        )
        self.assertNotEqual(proceso.returncode, 0)
        self.assertIn("puntero", proceso.stderr)

    def test_un_simbolo_inexistente_es_error_de_jp(self) -> None:
        _, proceso = _salida(
            'externo "c" {\n'
            "    funcion esto_no_esta(n: entero) -> entero\n"
            "}\n"
            "esto_no_esta(1)\n"
        )
        self.assertNotEqual(proceso.returncode, 0)
        self.assertIn("no exporta", proceso.stderr)


class SintaxisExterno(unittest.TestCase):
    def _parsear(self, fuente: str):
        return parsear(tokenizar(fuente))

    def test_externo_es_azucar_sin_nodos_nuevos(self) -> None:
        programa = self._parsear(
            'externo "c" {\n'
            "    funcion abs(n: entero) -> entero\n"
            "    funcion strlen(s: texto) -> entero\n"
            "}\n"
        )
        nombre = type(programa).__name__
        self.assertEqual(nombre, "NodoPrograma")
        # Dos funciones hermanas, no un bloque: si no, no se ven fuera.
        funciones = [s for s in programa.sentencias if type(s).__name__ == "NodoFuncion"]
        self.assertEqual([f.nombre for f in funciones], ["abs", "strlen"])
        self.assertEqual(funciones[0].tipos, ["entero"])

    def test_bloque_externo_vacio(self) -> None:
        with self.assertRaises(ErrorSintaxis) as caso:
            self._parsear('externo "c" {\n}\n')
        self.assertIn("no declara ninguna función", caso.exception.mensaje)

    def test_solo_funciones_dentro(self) -> None:
        with self.assertRaises(ErrorSintaxis) as caso:
            self._parsear('externo "c" {\n    variable x = 1\n}\n')
        self.assertIn("sólo van funciones", caso.exception.mensaje)

    def test_parametro_sin_tipo(self) -> None:
        with self.assertRaises(ErrorSintaxis) as caso:
            self._parsear('externo "c" {\n    funcion abs(n) -> entero\n}\n')
        self.assertIn("tipo C", caso.exception.mensaje)


class MotorPython(unittest.TestCase):
    def test_avisa_de_que_hace_falta_el_motor_c(self) -> None:
        with self.assertRaises(ErrorEjecucion) as caso:
            programa = parsear(
                tokenizar(
                    'externo "c" {\n'
                    "    funcion abs(n: entero) -> entero\n"
                    "}\n"
                    "imprime(abs(-1))\n"
                )
            )
            Interprete().ejecutar(programa)
        self.assertIn("motor C", caso.exception.mensaje)


if __name__ == "__main__":
    unittest.main()
