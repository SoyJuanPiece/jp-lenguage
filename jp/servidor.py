"""Servidor web para JP: servir paginas y APIs desde el propio lenguaje.

    funcion atender(peticion) {
        si peticion.ruta == "/hola" { devuelve {cuerpo: "Hola"} }
        devuelve {cuerpo: {ok: verdadero}, estado: 201}
    }
    servir(8080, atender)            # se queda escuchando

La peticion es un diccionario {metodo, ruta, consulta, cuerpo, cabeceras}
mas `json` con el cuerpo ya leido si venia en JSON. La respuesta puede ser
texto (200) o un diccionario {cuerpo, estado, tipo, cabeceras}; si el cuerpo
es diccionario/lista sale como JSON automaticamente.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .errores import ErrorEjecucion
from .interprete import (
    Cierre,
    ClaseJP,
    Entorno,
    FuncionJP,
    FuncionNativa,
    MetodoLigado,
    jp_a_texto,
)


def _es_llamable(valor: object) -> bool:
    return isinstance(valor, (FuncionNativa, FuncionJP, Cierre, MetodoLigado, ClaseJP))


def instalar(entorno: Entorno, invocar=None) -> None:
    def servir(*args: object):
        """servir(puerto, manejador[, anfitrion]): escucha para siempre."""
        if invocar is None:
            raise ErrorEjecucion("servir() necesita un motor que sepa llamar funciones")
        if len(args) not in (2, 3):
            raise ErrorEjecucion("servir() espera (puerto, manejador) o (puerto, manejador, anfitrion)")
        puerto, manejador = args[0], args[1]
        anfitrion = args[2] if len(args) == 3 else "127.0.0.1"
        if isinstance(puerto, bool) or not isinstance(puerto, (int, float)) or not 0 <= int(puerto) <= 65535:
            raise ErrorEjecucion("servir() espera un puerto entre 0 y 65535")
        if not _es_llamable(manejador):
            raise ErrorEjecucion("servir() espera una funcion manejadora: servir(8080, atender)")
        if not isinstance(anfitrion, str):
            raise ErrorEjecucion("el anfitrion de servir() debe ser texto, ej: '0.0.0.0'")
        candado = threading.Lock()

        class Manejador(BaseHTTPRequestHandler):
            def _atender(self, metodo: str) -> None:
                partes = urlparse(self.path)
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(largo).decode("utf-8", "replace") if largo else ""
                try:
                    datos_json = json.loads(cuerpo) if cuerpo else None
                except ValueError:
                    datos_json = None
                peticion = {
                    "metodo": metodo,
                    "ruta": partes.path,
                    "consulta": {k: v[0] for k, v in parse_qs(partes.query).items()},
                    "cuerpo": cuerpo,
                    "json": datos_json,
                    "cabeceras": {k.lower(): v for k, v in self.headers.items()},
                }
                try:
                    with candado:  # el motor de JP no es multi-hilo: de uno en uno
                        respuesta = invocar(manejador, [peticion], 0)
                except ErrorEjecucion as error:
                    return self._responder(500, f"Error en el manejador: {error.mensaje}", "text/plain; charset=utf-8")
                except Exception as error:  # el servidor no se cae por una peticion
                    return self._responder(500, f"Error en el manejador: {error}", "text/plain; charset=utf-8")
                estado, datos, tipo = 200, "", "text/plain; charset=utf-8"
                cabeceras_extra: dict = {}
                if isinstance(respuesta, dict):
                    estado = int(respuesta.get("estado", 200))
                    crudo = respuesta.get("cuerpo", "")
                    tipo = respuesta.get("tipo", tipo)
                    extra = respuesta.get("cabeceras")
                    if isinstance(extra, dict):
                        cabeceras_extra = {str(k): jp_a_texto(v) for k, v in extra.items()}
                    if isinstance(crudo, (dict, list)):
                        datos = json.dumps(crudo, ensure_ascii=False)
                        tipo = "application/json; charset=utf-8"
                    else:
                        datos = jp_a_texto(crudo)
                elif respuesta is not None:
                    datos = jp_a_texto(respuesta)
                self._responder(estado, datos, tipo, cabeceras_extra)

            def _responder(self, estado: int, datos: str, tipo: str, extra: dict | None = None) -> None:
                crudo = datos.encode("utf-8")
                self.send_response(estado)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(crudo)))
                for nombre, valor in (extra or {}).items():
                    self.send_header(nombre, valor)
                self.end_headers()
                self.wfile.write(crudo)

            def do_GET(self): self._atender("GET")
            def do_POST(self): self._atender("POST")
            def do_PUT(self): self._atender("PUT")
            def do_DELETE(self): self._atender("DELETE")

            def log_message(self, formato, *args):  # silencio en la consola
                pass

        servidor_http = ThreadingHTTPServer((anfitrion, int(puerto)), Manejador)
        print(f"Servidor JP escuchando en http://{anfitrion}:{int(puerto)} (Ctrl+C para parar)", flush=True)
        try:
            servidor_http.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            servidor_http.server_close()
        return True

    entorno.definir("servir", FuncionNativa("servir", servir))
