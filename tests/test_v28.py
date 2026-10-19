"""Tests de la v1.19: pedir() pro, archivos estaticos y comodin /* en web.jp."""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class _ManejadorPrueba(BaseHTTPRequestHandler):
    def _responder(self):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo).decode() if largo else ""
        if self.path == "/eco":
            datos = json.dumps({"eco": cuerpo, "metodo": self.command}).encode()
            self.send_response(200)
        else:
            datos = b"no esta"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    do_GET = _responder
    do_POST = _responder

    def log_message(self, formato, *args):
        pass


class TestPedir(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), _ManejadorPrueba)
        cls.puerto = cls.servidor.server_address[1]
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def test_pedir_json_y_404_sin_lanzar(self):
        codigo = (
            f'variable r = pedir("http://127.0.0.1:{self.puerto}/eco", "POST", {{"a": 1}})\n'
            "muestra(r.estado, r.json.metodo, r.json.eco)\n"
            f'variable r2 = pedir("http://127.0.0.1:{self.puerto}/nada")\n'
            "muestra(r2.estado, r2.cuerpo, r2.json == nulo)\n"
        )
        self.assertEqual(paridad(codigo), '200 POST {"a": 1}\n404 no esta verdadero\n')


class TestComodin(unittest.TestCase):
    def test_emparejar_comodin(self):
        codigo = (
            'importar "biblioteca/web.jp" como web\n'
            'variable p = web.emparejar("/static/*", "/static/css/estilo.css")\n'
            'muestra(p.resto, web.emparejar("/static/*", "/otra/x") == nulo)\n'
        )
        self.assertEqual(paridad(codigo), "css/estilo.css verdadero\n")


class TestEstaticoReal(unittest.TestCase):
    def test_servir_archivos(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        puerto = sock.getsockname()[1]
        sock.close()
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            (raiz / "publica").mkdir()
            (raiz / "publica" / "estilo.css").write_text("body { color: red; }", encoding="utf-8")
            codigo = (
                f'importar "{RAIZ}/biblioteca/web.jp" como web\n'
                "variable app = web.Aplicacion()\n"
                f'app.estatico("/static", "{raiz.as_posix()}/publica")\n'
                f"app.escuchar({puerto})\n"
            )
            ruta = raiz / "sitio.jp"
            ruta.write_text(codigo, encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "jp", str(ruta)],
                cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                base = f"http://127.0.0.1:{puerto}"
                respuesta = None
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + "/static/estilo.css", timeout=2) as r:
                            respuesta = (r.status, r.headers.get_content_type(), r.read().decode())
                        break
                    except Exception:
                        time.sleep(0.2)
                self.assertEqual(respuesta, (200, "text/css", "body { color: red; }"))
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + "/static/no.css", timeout=2)
                self.assertEqual(error.exception.code, 404)
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
