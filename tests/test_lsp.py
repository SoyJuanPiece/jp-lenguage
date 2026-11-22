"""Pruebas del servidor LSP de JP (`jp lsp`).

No hace falta editor ni compilador: se habla con el servidor por memoria,
metiendo los mensajes con cabecera Content-Length y leyendo las respuestas.
"""

from __future__ import annotations

import io
import json
import unittest

from jp.lsp import Servidor, diagnosticos


def _mensaje(cuerpo: dict) -> bytes:
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(datos) + datos


def _leer_todos(salida: bytes) -> list[dict]:
    mensajes: list[dict] = []
    posicion = 0
    while posicion < len(salida):
        fin = salida.find(b"\r\n\r\n", posicion)
        if fin < 0:
            break
        cabecera = salida[posicion:fin].decode("ascii")
        largo = int(cabecera.split(":", 1)[1].strip())
        inicio = fin + 4
        mensajes.append(json.loads(salida[inicio:inicio + largo].decode("utf-8")))
        posicion = inicio + largo
    return mensajes


class PruebaDiagnosticos(unittest.TestCase):
    def test_archivo_correcto_no_da_errores(self):
        self.assertEqual(diagnosticos('imprime("hola")\n'), [])

    def test_error_de_sintaxis_apunta_a_la_linea(self):
        lista = diagnosticos('si 1 {\n  imprime("x"\n')
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["range"]["start"]["line"], 1)
        self.assertEqual(lista[0]["severity"], 1)
        self.assertIn("')'", lista[0]["message"])

    def test_error_lexico_tambien_se_informa(self):
        lista = diagnosticos('variable x = "sin cerrar\n')
        self.assertEqual(len(lista), 1)
        self.assertIn("cadena", lista[0]["message"])


class PruebaServidor(unittest.TestCase):
    def _hablar(self, mensajes: list[dict]) -> list[dict]:
        entrada = io.BytesIO(b"".join(_mensaje(m) for m in mensajes))
        salida = io.BytesIO()
        Servidor(entrada=entrada, salida=salida).servir()
        return _leer_todos(salida.getvalue())

    def test_ciclo_completo(self):
        respuestas = self._hablar(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": "file:///a.jp",
                            "languageId": "jp",
                            "version": 1,
                            "text": "imprime(1\n",
                        }
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": "file:///a.jp", "version": 2},
                        "contentChanges": [{"text": "imprime(1)\n"}],
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/completion",
                    "params": {
                        "textDocument": {"uri": "file:///a.jp"},
                        "position": {"line": 0, "character": 3},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "textDocument/hover",
                    "params": {
                        "textDocument": {"uri": "file:///a.jp"},
                        "position": {"line": 0, "character": 3},
                    },
                },
                {"jsonrpc": "2.0", "id": 4, "method": "shutdown"},
                {"jsonrpc": "2.0", "method": "exit"},
            ]
        )
        por_id = {m.get("id"): m for m in respuestas if "id" in m}

        self.assertEqual(por_id[1]["result"]["serverInfo"]["name"], "jp-lsp")
        self.assertIn("textDocumentSync", por_id[1]["result"]["capabilities"])

        diagnosticos_publicados = [
            m["params"]["diagnostics"]
            for m in respuestas
            if m.get("method") == "textDocument/publishDiagnostics"
        ]
        self.assertEqual(len(diagnosticos_publicados), 2)
        self.assertEqual(len(diagnosticos_publicados[0]), 1)
        self.assertEqual(diagnosticos_publicados[1], [])

        etiquetas = {elemento["label"] for elemento in por_id[2]["result"]["items"]}
        self.assertIn("imprime", etiquetas)
        self.assertIn("longitud", etiquetas)
        self.assertIn("si", etiquetas)

        hover = por_id[3]["result"]["contents"]["value"]
        self.assertIn("imprime", hover)

    def test_hover_fuera_de_palabra(self):
        respuestas = self._hablar(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": "file:///b.jp",
                            "languageId": "jp",
                            "version": 1,
                            "text": "variable x = 1\n",
                        }
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/hover",
                    "params": {
                        "textDocument": {"uri": "file:///b.jp"},
                        "position": {"line": 0, "character": 10},
                    },
                },
                {"jsonrpc": "2.0", "method": "exit"},
            ]
        )
        por_id = {m.get("id"): m for m in respuestas if "id" in m}
        self.assertIsNone(por_id[2]["result"])


if __name__ == "__main__":
    unittest.main()
