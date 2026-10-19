"""Tests de la v1.9: CSV y la clase Tabla (biblioteca/tabla.jp), fechas con
dias, y las primeras nativas de la biblioteca dentro del motor en C.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jp.compilar_nativo import compilar_a_bytes
from jp.errores import ErrorEjecucion
from jp.interprete import Interprete
from jp.lexer import tokenizar
from jp.parser import parsear
from jp.vm import MaquinaVM

RAIZ = Path(__file__).resolve().parent.parent
MOTOR = RAIZ / "motor-c" / "jpvm"


def ejecutar_en(maquina, codigo: str, directorio=None) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        maquina.ejecutar(parsear(tokenizar(codigo)), directorio=directorio)
    return buffer.getvalue()


def paridad(codigo: str, directorio=None) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo, directorio)
    arbol = ejecutar_en(Interprete(), codigo, directorio)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


class TestCSV(unittest.TestCase):
    def test_leer_csv_texto_convierte_tipos(self):
        salida = paridad(
            'variable f = leer_csv_texto("nombre,edad,activo\\nAna,30,verdadero\\nLuis,25,falso")\n'
            'muestra(f[0].nombre, f[0].edad + 1, f[1].activo, tipo(f[0].edad))'
        )
        self.assertEqual(salida, "Ana 31 falso número\n")

    def test_ida_y_vuelta(self):
        salida = paridad(
            'variable f = leer_csv_texto("a,b\\n1,x\\n2,y")\nmuestra(convertir_csv(f))'
        )
        self.assertEqual(salida, "a,b\n1,x\n2,y\n\n")  # convertir termina en \n

    def test_leer_csv_archivo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "datos.csv"
            ruta.write_text("n\n5\n7\n", encoding="utf-8")
            codigo = f'variable f = leer_csv("{ruta}")\nmuestra(f[0].n + f[1].n)'
            self.assertEqual(paridad(codigo), "12\n")

    def test_sublista(self):
        self.assertEqual(
            paridad('muestra(sublista([1, 2, 3, 4], 1, 3), sublista("hola", 1))'),
            "[2, 3] ola\n",
        )

    def test_fechas_con_dias(self):
        salida = paridad(
            'variable a = convertir_fecha("2026-10-19")\n'
            'muestra(dias_entre(a, sumar_dias(a, 10)), formatear_fecha(sumar_dias(a, 1), "%d"))'
        )
        self.assertEqual(salida, "10 20\n")


class TestTabla(unittest.TestCase):
    CODIGO_BASE = (
        'importar "biblioteca/tabla.jp" como datos\n'
        'variable t = datos.tabla_de_texto("producto,total\\npan,120\\nqueso,300\\npan,80")\n'
    )

    def test_operaciones(self):
        salida = paridad(
            self.CODIGO_BASE
            + 'muestra(t.contar(), t.promedio_columna("total"))\n'
            'muestra(t.filtrar_con(funcion(f) { devuelve f.total > 100 }).contar())\n'
            'muestra(t.agrupar_por("producto")["pan"].suma_columna("total"))\n'
            'muestra(t.ordenar_por("total", verdadero).cabeza(1).columna("producto"))',
            RAIZ,
        )
        self.assertEqual(salida, '3 166.66666666666666\n2\n200\n["queso"]\n')

    def test_agregar_columna_encadenado(self):
        salida = paridad(
            self.CODIGO_BASE
            + 'muestra(t.agregar_columna("doble", funcion(f) { devuelve f.total * 2 }).cabeza(1).a_texto())',
            RAIZ,
        )
        self.assertEqual(salida, "producto | total | doble\npan | 120 | 240\n")


@unittest.skipUnless(MOTOR.exists(), "el motor nativo no esta compilado (make -C motor-c)")
class TestNativasEnC(unittest.TestCase):
    """sigmoide/producto_punto/promedio/mediana/norma/distancia/softmax ya
    viven en jpvm.c: el binario en C da la misma salida que Python."""

    def test_salida_identica_en_c(self):
        codigo = (
            'muestra(sigmoide(0), producto_punto([1, 2, 3], [4, 5, 6]))\n'
            'muestra(promedio([1, 2, 3, 4]), mediana([3, 1, 2]), norma([3, 4]), distancia([0, 0], [3, 4]))\n'
            'muestra(softmax([1, 1]))'
        )
        esperado = ejecutar_en(MaquinaVM(), codigo)
        blob = compilar_a_bytes(parsear(tokenizar(codigo)), "prueba", codigo)
        with tempfile.NamedTemporaryFile(suffix=".jpb", delete=False) as archivo:
            archivo.write(blob)
            ruta = archivo.name
        proceso = subprocess.run([str(MOTOR), ruta], capture_output=True, text=True, timeout=60)
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        self.assertEqual(proceso.stdout, esperado)


if __name__ == "__main__":
    unittest.main()
