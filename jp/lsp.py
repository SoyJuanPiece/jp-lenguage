"""Servidor LSP de JP: diagnósticos, autocompletado y hover por stdio.

Se lanza con `jp lsp` (o `python -m jp lsp`) y habla JSON-RPC 2.0 con el
formato de cabeceras de Language Server Protocol:

    Content-Length: 123\r\n
    \r\n
    { ... }

Solo usa la biblioteca estándar: el objetivo es que cualquier editor
(VS Code, Neovim, Zed, Emacs) tenga diagnósticos reales del parser de JP
sin instalar nada más.

Qué hace:
    - textDocument/didOpen y didChange → publica diagnósticos del lexer y
      del parser con la posición exacta.
    - textDocument/completion → palabras clave, tipos y las funciones
      nativas de la biblioteca estándar (con su aridad).
    - textDocument/hover → firma y ayuda de una función nativa o de una
      palabra clave.

Qué NO hace (todavía): dar formato al guardar. `jp --formatear` pierde los
comentarios, y un formateador que borra comentarios no puede ir conectado a
"format on save".
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from .errores import ErrorJP
from .lexer import tokenizar
from .parser import parsear

# ---------- vocabulario ----------

_PALABRAS_CLAVE: dict[str, str] = {
    "variable": "Declara una variable. También vale `var`.",
    "var": "Declara una variable. También vale `variable`.",
    "funcion": "Declara una función. También valen `fun` y `función`.",
    "fun": "Declara una función. También valen `funcion` y `función`.",
    "función": "Declara una función. También valen `fun` y `funcion`.",
    "retorna": "Devuelve un valor desde una función. También vale `devuelve`.",
    "devuelve": "Devuelve un valor desde una función. También vale `retorna`.",
    "si": "Condicional: `si condicion { ... } sino { ... }`.",
    "sino": "Rama alternativa del `si`.",
    "mientras": "Bucle mientras la condición sea verdadera.",
    "para": "Bucle: `para i en 1..10 { ... }` o `para i, v en lista`.",
    "en": "Separa la variable del iterable en `para`.",
    "elegir": "Elige entre casos: `elegir n { caso 1 { ... } sino { ... } }`.",
    "caso": "Una opción dentro de `elegir`.",
    "intenta": "Bloque protegido: `intenta { ... } atrapa error { ... }`.",
    "atrapa": "Captura el error de un `intenta`.",
    "finalmente": "Bloque que se ejecuta siempre, con o sin error.",
    "lanzar": "Lanza un error: `lanzar \"algo salió mal\"`.",
    "importar": 'Importa otro archivo: `importar "utilidades.jp" como util`.',
    "como": "Alias del módulo importado.",
    "clase": "Declara una clase: `clase Persona { funcion iniciar() { ... } }`.",
    "hereda": "Herencia: `clase Empleado hereda Persona { ... }`.",
    "romper": "Sale del bucle.",
    "continuar": "Salta a la siguiente vuelta del bucle.",
    "paso": "Paso de un rango: `1..10 paso 2`.",
    "y": "Y lógico.",
    "o": "O lógico.",
    "no": "Negación lógica.",
    "verdadero": "Literal booleano verdadero.",
    "falso": "Literal booleano falso.",
    "nulo": "Literal nulo (ausencia de valor).",
    "numero": "Tipo numérico.",
    "entero": "Tipo entero.",
    "texto": "Tipo texto.",
    "booleano": "Tipo booleano.",
    "lista": "Tipo lista.",
    "diccionario": "Tipo diccionario.",
    "cualquiera": "Tipo comodín en las anotaciones.",
}

_nativas_cache: dict[str, Any] | None = None


def _nativas() -> dict[str, Any]:
    """Nombre → FuncionNativa, tomado del entorno global del intérprete.

    Se construye una sola vez y, si algo falla (por ejemplo un módulo
    opcional sin dependencias), el servidor sigue funcionando con lo básico.
    """
    global _nativas_cache
    if _nativas_cache is not None:
        return _nativas_cache
    tabla: dict[str, Any] = {}
    try:
        from .interprete import FuncionNativa, Interprete

        for nombre, valor in Interprete().global_env.variables.items():
            if isinstance(valor, FuncionNativa):
                tabla[nombre] = valor
    except Exception:  # noqa: BLE001 - el LSP nunca debe morir por esto
        tabla = {}
    _nativas_cache = tabla
    return tabla


def _firma(nombre: str, nativa: Any) -> str:
    aridad = getattr(nativa, "aridad", None)
    if aridad is None:
        return f"{nombre}(...)"
    if aridad == 0:
        return f"{nombre}()"
    return f"{nombre}(" + ", ".join(f"arg{i + 1}" for i in range(aridad)) + ")"


def _ayuda(nombre: str, nativa: Any) -> str:
    firma = _firma(nombre, nativa)
    documento = (getattr(nativa.funcion, "__doc__", None) or "").strip()
    if not documento:
        return firma
    primera = documento.splitlines()[0].strip()
    return f"{firma}\n\n{primera}"


# ---------- transporte ----------


def _leer_mensaje(entrada) -> dict[str, Any] | None:
    """Lee un mensaje LSP. Devuelve None al cerrarse la entrada."""
    largo: int | None = None
    while True:
        linea = entrada.readline()
        if not linea:
            return None
        texto = linea.decode("ascii", "replace").strip()
        if not texto:
            break  # línea en blanco: fin de las cabeceras
        if texto.lower().startswith("content-length:"):
            try:
                largo = int(texto.split(":", 1)[1].strip())
            except ValueError:
                largo = None
    if largo is None:
        return None
    cuerpo = entrada.read(largo)
    if not cuerpo:
        return None
    try:
        return json.loads(cuerpo.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _enviar(salida, mensaje: dict[str, Any]) -> None:
    datos = json.dumps(mensaje, ensure_ascii=False).encode("utf-8")
    salida.write(f"Content-Length: {len(datos)}\r\n\r\n".encode("ascii"))
    salida.write(datos)
    salida.flush()


# ---------- diagnósticos ----------


def diagnosticos(fuente: str) -> list[dict[str, Any]]:
    """Errores de sintaxis del archivo, en el formato de LSP (0-based)."""
    try:
        parsear(tokenizar(fuente))
    except ErrorJP as error:
        linea = max(1, getattr(error, "linea", 1)) - 1
        columna = max(1, getattr(error, "columna", 1)) - 1
        lineas = fuente.splitlines() or [""]
        if linea >= len(lineas):
            # El error puede caer en la línea del EOF (después del último
            # salto de línea): se pega a la última línea real.
            linea = len(lineas) - 1
            columna = len(lineas[linea])
        fin = len(lineas[linea])
        return [
            {
                "range": {
                    "start": {"line": linea, "character": columna},
                    "end": {"line": linea, "character": max(fin, columna + 1)},
                },
                "severity": 1,  # Error
                "source": "jp",
                "message": error.mensaje,
            }
        ]
    except Exception as error:  # noqa: BLE001 - nunca tumbar el servidor
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 1},
                },
                "severity": 1,
                "source": "jp",
                "message": f"fallo interno del analizador: {error}",
            }
        ]
    return []


def _palabra_en(fuente: str, linea: int, caracter: int) -> str:
    """Identificador que hay en (linea, caracter), o cadena vacía."""
    lineas = fuente.splitlines()
    if not (0 <= linea < len(lineas)):
        return ""
    texto = lineas[linea]
    if not texto:
        return ""
    caracter = min(max(caracter, 0), len(texto) - 1)
    if texto[caracter].isalnum() or texto[caracter] == "_":
        inicio = caracter
        while inicio > 0 and (texto[inicio - 1].isalnum() or texto[inicio - 1] == "_"):
            inicio -= 1
        fin = caracter
        while fin < len(texto) and (texto[fin].isalnum() or texto[fin] == "_"):
            fin += 1
        return texto[inicio:fin]
    return ""


# ---------- servidor ----------


class Servidor:
    def __init__(self, entrada=None, salida=None):
        self.entrada = entrada if entrada is not None else sys.stdin.buffer
        self.salida = salida if salida is not None else sys.stdout.buffer
        self.documentos: dict[str, str] = {}
        self.versiones: dict[str, int | None] = {}
        self.apagado = False

    # -- ciclo principal --

    def servir(self) -> int:
        while True:
            mensaje = _leer_mensaje(self.entrada)
            if mensaje is None:
                return 0
            metodo = mensaje.get("method")
            identificador = mensaje.get("id")
            parametros = mensaje.get("params") or {}
            if metodo == "exit":
                return 0
            if metodo == "shutdown":
                self.apagado = True
                self._responder(identificador, None)
                continue
            try:
                resultado = self._manejar(metodo, parametros)
            except Exception as error:  # noqa: BLE001
                if identificador is not None:
                    self._responder(identificador, None, error=str(error))
                continue
            if identificador is not None:
                self._responder(identificador, resultado)

    def _responder(self, identificador, resultado, error: str | None = None) -> None:
        if error is None:
            _enviar(self.salida, {"jsonrpc": "2.0", "id": identificador, "result": resultado})
        else:
            _enviar(
                self.salida,
                {"jsonrpc": "2.0", "id": identificador, "error": {"code": -32603, "message": error}},
            )

    def _manejar(self, metodo: str | None, parametros: dict[str, Any]):
        if metodo == "initialize":
            return {
                "capabilities": {
                    "textDocumentSync": {"openClose": True, "change": 1},
                    "completionProvider": {"resolveProvider": False},
                    "hoverProvider": True,
                },
                "serverInfo": {"name": "jp-lsp", "version": __version__},
            }
        if metodo in ("initialized", "workspace/didChangeConfiguration"):
            return None
        if metodo == "textDocument/didOpen":
            documento = parametros.get("textDocument", {})
            uri = documento.get("uri", "")
            self.documentos[uri] = documento.get("text", "")
            self.versiones[uri] = documento.get("version")
            self._publicar(uri)
            return None
        if metodo == "textDocument/didChange":
            documento = parametros.get("textDocument", {})
            uri = documento.get("uri", "")
            cambios = parametros.get("contentChanges") or []
            if cambios:
                self.documentos[uri] = cambios[-1].get("text", "")
            self.versiones[uri] = documento.get("version")
            self._publicar(uri)
            return None
        if metodo == "textDocument/didClose":
            uri = parametros.get("textDocument", {}).get("uri", "")
            self.documentos.pop(uri, None)
            _enviar(
                self.salida,
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {"uri": uri, "diagnostics": []},
                },
            )
            return None
        if metodo == "textDocument/completion":
            return self._completar(parametros)
        if metodo == "textDocument/hover":
            return self._hover(parametros)
        return None

    def _publicar(self, uri: str) -> None:
        fuente = self.documentos.get(uri, "")
        _enviar(
            self.salida,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": uri,
                    "diagnostics": diagnosticos(fuente),
                    **({"version": self.versiones[uri]} if self.versiones.get(uri) is not None else {}),
                },
            },
        )

    # -- funciones --

    def _completar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        elementos: list[dict[str, Any]] = []
        vistos: set[str] = set()
        for nombre, nativa in sorted(_nativas().items()):
            vistos.add(nombre)
            elementos.append(
                {
                    "label": nombre,
                    "kind": 3,  # Function
                    "detail": _firma(nombre, nativa),
                    "documentation": _ayuda(nombre, nativa),
                }
            )
        for palabra, ayuda in _PALABRAS_CLAVE.items():
            if palabra in vistos:
                continue
            vistos.add(palabra)
            elementos.append(
                {"label": palabra, "kind": 14, "detail": "palabra clave de JP", "documentation": ayuda}
            )
        return {"isIncomplete": False, "items": elementos}

    def _hover(self, parametros: dict[str, Any]) -> dict[str, Any] | None:
        documento = parametros.get("textDocument", {})
        posicion = parametros.get("position", {})
        uri = documento.get("uri", "")
        fuente = self.documentos.get(uri)
        if fuente is None:
            return None
        palabra = _palabra_en(
            fuente, int(posicion.get("line", 0)), int(posicion.get("character", 0))
        )
        if not palabra:
            return None
        nativa = _nativas().get(palabra)
        if nativa is not None:
            texto = _ayuda(palabra, nativa)
        elif palabra in _PALABRAS_CLAVE:
            texto = _PALABRAS_CLAVE[palabra]
        else:
            return None
        return {"contents": {"kind": "markdown", "value": f"```jp\n{texto}\n```" if "\n" not in texto else texto}}


def servir() -> int:
    """Punto de entrada de `jp lsp`."""
    try:
        return Servidor().servir()
    except KeyboardInterrupt:
        return 0
