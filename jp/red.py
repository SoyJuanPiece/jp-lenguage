"""Red y datos para JP: HTTP, JSON y bots de Telegram.

Todo usa solo la librería estándar de Python (urllib + json): cero dependencias.

Nativas que instala:
    http_get(url)                  -> texto con la respuesta
    http_post(url, cuerpo, [tipo]) -> texto con la respuesta (dict/lista -> JSON automático)
    json_leer(texto)               -> diccionario / lista / valor JSON
    json_texto(valor)              -> texto JSON
    tiene(contenedor, clave)       -> verdadero / falso
    claves(diccionario)            -> lista de claves
    esperar(segundos)              -> pausa (para no saturar en bucles de bots)
    telegram_leer(token)           -> lista de mensajes {de, texto}
    telegram_responder(token, de, texto) -> verdadero
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa, jp_a_texto


# ---------- capa HTTP cruda (los tests la simulan parcheando esto) ----------

def _http_get(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=15) as respuesta:
            return respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ErrorEjecucion(f"el servidor respondió con error HTTP {e.code}")
    except urllib.error.URLError as e:
        raise ErrorEjecucion(f"no se pudo conectar ({getattr(e, 'reason', e)})")
    except TimeoutError:
        raise ErrorEjecucion("el servidor tardó demasiado en responder (timeout)")


def _http_post(url: str, cuerpo: str, tipo: str) -> str:
    datos = cuerpo.encode("utf-8")
    peticion = urllib.request.Request(
        url,
        data=datos,
        method="POST",
        headers={"Content-Type": tipo, "User-Agent": "jp/0.3"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ErrorEjecucion(f"el servidor respondió con error HTTP {e.code}")
    except urllib.error.URLError as e:
        raise ErrorEjecucion(f"no se pudo conectar ({getattr(e, 'reason', e)})")
    except TimeoutError:
        raise ErrorEjecucion("el servidor tardó demasiado en responder (timeout)")


def _json_o_texto(cuerpo: object) -> tuple[str, str]:
    """Prepara el cuerpo de un POST: dict/lista -> JSON, texto -> tal cual."""
    if isinstance(cuerpo, (dict, list)):
        return json.dumps(cuerpo, ensure_ascii=False), "application/json; charset=utf-8"
    if isinstance(cuerpo, str):
        return cuerpo, "application/json; charset=utf-8"
    if isinstance(cuerpo, (int, float, bool)) or cuerpo is None:
        return json.dumps(cuerpo), "application/json; charset=utf-8"
    raise ErrorEjecucion(f"http_post() no sabe enviar {jp_a_texto(cuerpo)!r}")


# ---------- instalación de las nativas ----------

def instalar(entorno: Entorno) -> None:
    # estado del bot de Telegram (offset para no repetir mensajes)
    estado = {"offset": 0}

    def http_get(url: object) -> str:
        if not isinstance(url, str):
            raise ErrorEjecucion("http_get() espera una dirección en texto")
        try:
            return _http_get(url)
        except ErrorEjecucion:
            raise
        except urllib.error.URLError as e:
            raise ErrorEjecucion(f"no se pudo conectar ({getattr(e, 'reason', e)})")
        except (TimeoutError, OSError) as e:
            raise ErrorEjecucion(f"fallo de red: {e}")

    def http_post(url: object, cuerpo: object, tipo: object = None) -> str:
        if not isinstance(url, str):
            raise ErrorEjecucion("http_post() espera una dirección en texto")
        texto_cuerpo, content_type = _json_o_texto(cuerpo)
        if tipo is not None:
            if not isinstance(tipo, str):
                raise ErrorEjecucion("http_post(): el tipo debe ser texto")
            content_type = tipo
        return _http_post(url, texto_cuerpo, content_type)

    def json_leer(texto: object) -> object:
        if not isinstance(texto, str):
            raise ErrorEjecucion("json_leer() espera una cadena de texto")
        try:
            return json.loads(texto)
        except ValueError as e:
            raise ErrorEjecucion(f"el JSON no es válido ({e})")

    def json_texto(valor: object) -> str:
        try:
            return json.dumps(valor, ensure_ascii=False)
        except (TypeError, ValueError):
            raise ErrorEjecucion(f"json_texto() no sabe serializar {jp_a_texto(valor)!r}")

    def tiene(contenedor: object, clave: object) -> bool:
        if isinstance(contenedor, dict):
            return clave in contenedor
        if isinstance(contenedor, list):
            return clave in contenedor
        if isinstance(contenedor, str):
            return isinstance(clave, str) and clave in contenedor
        raise ErrorEjecucion(f"tiene() espera un diccionario, lista o texto, no {jp_a_texto(contenedor)!r}")

    def claves(diccionario: object) -> list:
        if isinstance(diccionario, dict):
            return list(diccionario.keys())
        raise ErrorEjecucion(f"claves() espera un diccionario, no {jp_a_texto(diccionario)!r}")

    def esperar(segundos: object) -> None:
        if isinstance(segundos, bool) or not isinstance(segundos, (int, float)):
            raise ErrorEjecucion("esperar() espera un número de segundos")
        time.sleep(max(0.0, float(segundos)))

    def telegram_leer(token: object) -> list:
        if not isinstance(token, str) or not token:
            raise ErrorEjecucion("telegram_leer() espera tu token de Telegram")
        url = (
            f"https://api.telegram.org/bot{token}/getUpdates"
            f"?timeout=0&offset={estado['offset']}"
        )
        try:
            crudo = _http_get(url)
        except ErrorEjecucion:
            raise
        except urllib.error.URLError as e:
            raise ErrorEjecucion(f"no se pudo conectar con Telegram ({getattr(e, 'reason', e)})")
        except (TimeoutError, OSError) as e:
            raise ErrorEjecucion(f"fallo de red: {e}")
        try:
            datos = json.loads(crudo)
        except ValueError:
            raise ErrorEjecucion("telegram devolvió algo que no es JSON (¿token correcto?)")
        if not datos.get("ok"):
            raise ErrorEjecucion(f"telegram rechazó la petición: {datos.get('description', 'token inválido')}")
        mensajes: list[object] = []
        for actualizacion in datos.get("result", []):
            mensaje = actualizacion.get("message")
            if isinstance(mensaje, dict) and isinstance(mensaje.get("text"), str):
                estado["offset"] = max(estado["offset"], actualizacion.get("update_id", 0) + 1)
                mensajes.append({"de": mensaje["chat"]["id"], "texto": mensaje["text"]})
        return mensajes

    def telegram_responder(token: object, de: object, texto: object) -> bool:
        if not isinstance(token, str) or not token:
            raise ErrorEjecucion("telegram_responder() espera tu token de Telegram")
        if not isinstance(texto, str):
            texto = jp_a_texto(texto)
        cuerpo, content_type = json.dumps(
            {"chat_id": de, "text": texto}, ensure_ascii=False
        ), "application/json; charset=utf-8"
        crudo = _http_post(
            f"https://api.telegram.org/bot{token}/sendMessage", cuerpo, content_type
        )
        try:
            datos = json.loads(crudo)
        except ValueError:
            raise ErrorEjecucion("telegram devolvió algo que no es JSON")
        if not datos.get("ok"):
            raise ErrorEjecucion(f"no se pudo enviar: {datos.get('description', 'error desconocido')}")
        return True

    nativas = {
        "http_get": FuncionNativa("http_get", http_get, aridad=1),
        "http_post": FuncionNativa("http_post", http_post),
        "json_leer": FuncionNativa("json_leer", json_leer, aridad=1),
        "json_texto": FuncionNativa("json_texto", json_texto, aridad=1),
        "tiene": FuncionNativa("tiene", tiene, aridad=2),
        "claves": FuncionNativa("claves", claves, aridad=1),
        "esperar": FuncionNativa("esperar", esperar, aridad=1),
        "telegram_leer": FuncionNativa("telegram_leer", telegram_leer, aridad=1),
        "telegram_responder": FuncionNativa("telegram_responder", telegram_responder, aridad=3),
    }
    for nombre, funcion in nativas.items():
        entorno.definir(nombre, funcion)
