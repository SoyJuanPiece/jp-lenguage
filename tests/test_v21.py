"""Tests de la v1.11: mini-framework web (biblioteca/web.jp) y servidor pro.

El enrutador se prueba sin red (app.atender es lo que el servidor llama), y
el servidor se prueba de verdad con un subproceso JP y HTTP real: cuerpo
JSON ya leido (peticion.json), cabeceras de respuesta y redirecciones.
"""

from __future__ import annotations

import http.client
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
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


CODIGO_WEB = """
importar "biblioteca/web.jp" como web
variable app = web.Aplicacion()
app.get("/saludar/:nombre", funcion(p) { devuelve "Hola " + p.parametros.nombre })
app.post("/api/suma", funcion(p) { devuelve web.json({total: p.json.a + p.json.b}, 201) })
variable r1 = app.atender({metodo: "GET", ruta: "/saludar/Luz", consulta: {}, cuerpo: "", cabeceras: {}})
variable r2 = app.atender({metodo: "POST", ruta: "/api/suma", consulta: {}, cuerpo: "", json: {a: 4, b: 5}, cabeceras: {}})
variable r3 = app.atender({metodo: "GET", ruta: "/api/suma", consulta: {}, cuerpo: "", cabeceras: {}})
variable r4 = app.atender({metodo: "GET", ruta: "/nada", consulta: {}, cuerpo: "", cabeceras: {}})
muestra(r1.estado, r1.cuerpo)
muestra(r2.estado, r2.cuerpo.total)
muestra(r3.estado, r4.estado, r4.cuerpo.error)
"""


class TestFrameworkWeb(unittest.TestCase):
    def test_rutas_parametros_y_metodos(self):
        self.assertEqual(
            paridad(CODIGO_WEB),
            "200 Hola Luz\n201 9\n404 404 ruta no encontrada\n",
        )

    def test_emparejar_patrones(self):
        codigo = (
            'importar "biblioteca/web.jp" como web\n'
            'variable p = web.emparejar("/u/:id/notas/:n", "/u/7/notas/3")\n'
            'muestra(p.id, p.n, web.emparejar("/u/:id", "/u") == nulo)\n'
        )
        self.assertEqual(paridad(codigo), "7 3 verdadero\n")


class TestServidorPro(unittest.TestCase):
    def test_json_cabeceras_y_redireccion(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        puerto = sock.getsockname()[1]
        sock.close()
        codigo = (
            f'importar "{RAIZ}/biblioteca/web.jp" como web\n'
            "variable app = web.Aplicacion()\n"
            'app.post("/api/suma", funcion(p) {\n'
            '    devuelve {cuerpo: {total: p.json.a + p.json.b}, estado: 201, cabeceras: {"X-App": "JP"}}\n'
            "})\n"
            'app.get("/vieja", funcion(p) { devuelve web.redirigir("/api/suma") })\n'
            f"app.escuchar({puerto})\n"
        )
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "sitio.jp"
            ruta.write_text(codigo, encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "jp", str(ruta)],
                cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                def pedir(metodo, ruta_, cuerpo=None):
                    for _ in range(50):
                        try:
                            conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=2)
                            conn.request(metodo, ruta_, body=cuerpo,
                                         headers={"Content-Type": "application/json"})
                            resp = conn.getresponse()
                            datos = resp.read().decode()
                            cabeceras = dict(resp.getheaders())
                            conn.close()
                            return resp.status, datos, cabeceras
                        except OSError:
                            time.sleep(0.2)
                    raise AssertionError("el servidor no arranco")

                estado, datos, cabeceras = pedir("POST", "/api/suma", json.dumps({"a": 2, "b": 40}))
                self.assertEqual(estado, 201)
                self.assertEqual(json.loads(datos), {"total": 42})
                self.assertEqual(cabeceras.get("X-App"), "JP")

                estado, _, cabeceras = pedir("GET", "/vieja")
                self.assertEqual(estado, 302)
                self.assertEqual(cabeceras.get("Location"), "/api/suma")
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
