"""Tests de la v1.29: módulos en el motor en C.

El compilador nativo resuelve `importar` al compilar: cada archivo
es una función y un espacio de globales del mismo blob (formato v2);
el motor lo ejecuta una vez y congela un diccionario con lo que
exporta (OP_IMPORTAR 65). De paso entran OP_LANZAR (66), sublista,
resumen y todo el paquete de matrices.
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
    OP_IMPORTAR,
    OP_LANZAR,
    NoSoportadoNativo,
    compilar_a_bytes,
)
from jp.lexer import tokenizar  # noqa: E402
from jp.parser import parsear  # noqa: E402

MOTOR = RAIZ / "motor-c" / "jpvm"

FIGURAS = """funcion area(r) {
    devuelve 3 * r * r
}
variable descripcion = "figuras"
clase Rectangulo {
    funcion iniciar(ancho, alto) {
        este.ancho = ancho
        este.alto = alto
    }
    funcion area() {
        devuelve este.ancho * este.alto
    }
}
"""

PRINCIPAL = """importar "figuras.jp" como fig
importar "figuras.jp" como otra
muestra(fig.area(2), otra.descripcion)
variable r = fig.Rectangulo(3, 4)
muestra(r.area())
importar "figuras.jp"
muestra(area(1))
"""

CON_ERRORES = """importar "roto.jp"
"""


def compilar_en(carpeta: Path, principal: str, nombre: str = "principal") -> subprocess.CompletedProcess:
    ast = parsear(tokenizar(principal))
    blob = compilar_a_bytes(ast, f"{nombre}.jp", principal,
                            directorio=str(carpeta))
    blob_ruta = carpeta / f"{nombre}.jpb"
    blob_ruta.write_bytes(blob)
    return subprocess.run([str(MOTOR), str(blob_ruta)], capture_output=True,
                          text=True, timeout=60)


@unittest.skipUnless(MOTOR.exists(), "Motor-c/jpvm sin compilar (make -C motor-c)")
class TestModulosEnC(unittest.TestCase):
    def _entorno(self, carpeta: Path) -> Path:
        (carpeta / "figuras.jp").write_text(FIGURAS, encoding="utf-8")
        return carpeta

    def test_modulo_con_clase_y_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = compilar_en(self._entorno(Path(tmp)), PRINCIPAL)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "12 figuras\n12\n3\n")

    def test_mismo_nombre_en_programa_y_modulo(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "otro.jp").write_text(
                'funcion saludo() { devuelve "del módulo" }\n', encoding="utf-8")
            r = compilar_en(carpeta,
                            'funcion saludo() { devuelve "del programa" }\n'
                            'importar "otro.jp" como otro\n'
                            "muestra(saludo(), otro.saludo())\n")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "del programa del módulo\n")

    def test_importacion_circular_se_rechaza(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "a.jp").write_text('importar "b.jp"\n', encoding="utf-8")
            (carpeta / "b.jp").write_text('importar "a.jp"\n', encoding="utf-8")
            with self.assertRaises(NoSoportadoNativo):
                compilar_a_bytes(parsear(tokenizar('importar "a.jp"\n')),
                                 "ppal.jp", "", directorio=str(carpeta))

    def test_modulo_que_importa(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "base.jp").write_text("funcion doble(x) { devuelve x * 2 }\n",
                                             encoding="utf-8")
            (carpeta / "medio.jp").write_text(
                'importar "base.jp" como b\nfuncion calc(x) { devuelve b.doble(x) + 1 }\n',
                encoding="utf-8")
            r = compilar_en(carpeta, 'importar "medio.jp" como m\nmuestra(m.calc(10))\n')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "21\n")

    def test_falta_el_modulo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NoSoportadoNativo):
                compilar_a_bytes(parsear(tokenizar('importar "nope.jp"\n')),
                                 "ppal.jp", "", directorio=str(Path(tmp)))


class TestSinMotorBinario(unittest.TestCase):
    def test_opcodes(self):
        self.assertEqual((OP_IMPORTAR, OP_LANZAR), (65, 66))

    def test_version_formato(self):
        from jp.compilar_nativo import VERSION_FORMATO

        self.assertEqual(VERSION_FORMATO, 2)


if __name__ == "__main__":
    unittest.main()
