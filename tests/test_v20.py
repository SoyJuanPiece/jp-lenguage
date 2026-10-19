"""Tests de la v1.10: servidor web (servir) y seguridad (hash/base64/id).

El servidor se prueba de verdad: un subproceso JP escuchando y peticiones
HTTP reales contra el.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
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
        maquina.ejecutar(parsear(tokenizar(codigo)))
    return buffer.getvalue()


def paridad(codigo: str) -> str:
    vm = ejecutar_en(MaquinaVM(), codigo)
    arbol = ejecutar_en(Interprete(), codigo)
    assert vm == arbol, f"VM y arbol difieren:\nVM: {vm!r}\narbol: {arbol!r}"
    return vm


class TestSeguridad(unittest.TestCase):
    def test_hash_conocido(self):
        esperado = hashlib.sha256("hola".encode()).hexdigest()
        self.assertEqual(paridad('muestra(hash_texto("hola"))'), esperado + "\n")

    def test_base64_ida_y_vuelta(self):
        self.assertEqual(
            paridad('muestra(decodificar64(codificar64("mundo JP")), longitud(id_unico()))'),
            "mundo JP 36\n",
        )


class TestServidor(unittest.TestCase):
    def test_servidor_real(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        puerto = sock.getsockname()[1]
        sock.close()
        codigo = (
            "funcion atender(p) {\n"
            '    si p.ruta == "/hola" { devuelve {cuerpo: "Hola desde JP", estado: 200} }\n'
            '    si p.ruta == "/eco" { devuelve {cuerpo: p.cuerpo} }\n'
            '    devuelve {cuerpo: {ok: verdadero, ruta: p.ruta}, estado: 201}\n'
            "}\n"
            f'servir({puerto}, atender, "127.0.0.1")'
        )
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "servidor.jp"
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
                        with urllib.request.urlopen(base + "/hola", timeout=2) as r:
                            respuesta = (r.status, r.read().decode())
                        break
                    except Exception:
                        time.sleep(0.2)
                self.assertEqual(respuesta, (200, "Hola desde JP"))

                with urllib.request.urlopen(base + "/otra", timeout=2) as r:
                    self.assertEqual(r.status, 201)
                    self.assertEqual(json.loads(r.read().decode()), {"ok": True, "ruta": "/otra"})

                peticion = urllib.request.Request(base + "/eco", data="probando".encode(), method="POST")
                with urllib.request.urlopen(peticion, timeout=2) as r:
                    self.assertEqual(r.read().decode(), "probando")
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
