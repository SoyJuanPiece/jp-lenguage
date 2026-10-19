"""Graficos SVG para JP: dibujar con primitivas y guardar el .svg.

    variable elementos = [svg_circulo(60, 60, 30, "tomato"),
                          svg_texto(20, 120, "Hola")]
    guardar_svg("dibujo.svg", crear_svg(200, 160, elementos))

Las primitivas devuelven texto SVG; crear_svg lo envuelve en <svg> y
guardar_svg lo escribe. Las graficas completas (barras, lineas, pastel)
viven en biblioteca/graficas.jp, escritas en JP puro con estas piezas.
"""

from __future__ import annotations

from pathlib import Path

from .errores import ErrorEjecucion
from .interprete import Entorno, FuncionNativa


def _numero(valor: object, funcion: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorEjecucion(f"{funcion}() espera numeros, ej: {funcion}(10, 20)")
    return float(valor)


def _texto(valor: object, funcion: str, que: str) -> str:
    if not isinstance(valor, str):
        raise ErrorEjecucion(f"{funcion}() espera {que} como texto")
    return valor


def _num(valor: object, funcion: str) -> str:
    f = _numero(valor, funcion)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".")


def _escapar(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def instalar(entorno: Entorno, invocar=None) -> None:
    def svg_linea(x1, y1, x2, y2, color="black", grosor=2):
        color = _texto(color, "svg_linea", "el color")
        return (
            f'<line x1="{_num(x1, "svg_linea")}" y1="{_num(y1, "svg_linea")}" '
            f'x2="{_num(x2, "svg_linea")}" y2="{_num(y2, "svg_linea")}" '
            f'stroke="{_escapar(color)}" stroke-width="{_num(grosor, "svg_linea")}"/>'
        )

    def svg_rectangulo(x, y, ancho, alto, relleno="steelblue"):
        relleno = _texto(relleno, "svg_rectangulo", "el relleno")
        return (
            f'<rect x="{_num(x, "svg_rectangulo")}" y="{_num(y, "svg_rectangulo")}" '
            f'width="{_num(ancho, "svg_rectangulo")}" height="{_num(alto, "svg_rectangulo")}" '
            f'fill="{_escapar(relleno)}"/>'
        )

    def svg_circulo(cx, cy, radio, relleno="tomato"):
        relleno = _texto(relleno, "svg_circulo", "el relleno")
        return (
            f'<circle cx="{_num(cx, "svg_circulo")}" cy="{_num(cy, "svg_circulo")}" '
            f'r="{_num(radio, "svg_circulo")}" fill="{_escapar(relleno)}"/>'
        )

    def svg_texto(x, y, contenido, tamano=14, color="black"):
        if not isinstance(contenido, str):
            contenido = str(contenido)
        color = _texto(color, "svg_texto", "el color")
        return (
            f'<text x="{_num(x, "svg_texto")}" y="{_num(y, "svg_texto")}" '
            f'font-size="{_num(tamano, "svg_texto")}" fill="{_escapar(color)}" '
            f'font-family="sans-serif">{_escapar(contenido)}</text>'
        )

    def svg_lineas(puntos, color="steelblue", grosor=2):
        if not isinstance(puntos, list) or not puntos:
            raise ErrorEjecucion("svg_lineas() espera una lista de puntos [[x, y], ...] con al menos uno")
        color = _texto(color, "svg_lineas", "el color")
        pares = []
        for punto in puntos:
            if not isinstance(punto, (list, tuple)) or len(punto) != 2:
                raise ErrorEjecucion("svg_lineas() espera puntos como [x, y]")
            pares.append(f'{_num(punto[0], "svg_lineas")},{_num(punto[1], "svg_lineas")}')
        return (
            f'<polyline points="{" ".join(pares)}" fill="none" '
            f'stroke="{_escapar(color)}" stroke-width="{_num(grosor, "svg_lineas")}"/>'
        )

    def svg_camino(datos, relleno="steelblue"):
        datos = _texto(datos, "svg_camino", "el camino")
        relleno = _texto(relleno, "svg_camino", "el relleno")
        return f'<path d="{_escapar(datos)}" fill="{_escapar(relleno)}"/>'

    def crear_svg(ancho, alto, elementos, fondo="#ffffff"):
        if not isinstance(elementos, list) or not all(isinstance(e, str) for e in elementos):
            raise ErrorEjecucion("crear_svg() espera la lista de elementos que devuelven las svg_*")
        fondo = _texto(fondo, "crear_svg", "el fondo")
        w, h = _num(ancho, "crear_svg"), _num(alto, "crear_svg")
        partes = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        ]
        if fondo:
            partes.append(f'<rect width="{w}" height="{h}" fill="{_escapar(fondo)}"/>')
        partes.extend(elementos)
        partes.append("</svg>")
        return "\n".join(partes)

    def guardar_svg(ruta, contenido):
        ruta = _texto(ruta, "guardar_svg", "la ruta")
        contenido = _texto(contenido, "guardar_svg", "el contenido")
        try:
            Path(ruta).write_text(contenido, encoding="utf-8")
        except OSError as error:
            raise ErrorEjecucion(f"guardar_svg() no pudo escribir '{ruta}': {error.strerror or error}")
        return True

    for nombre, funcion in {
        "svg_linea": svg_linea,
        "svg_rectangulo": svg_rectangulo,
        "svg_circulo": svg_circulo,
        "svg_texto": svg_texto,
        "svg_lineas": svg_lineas,
        "svg_camino": svg_camino,
        "crear_svg": crear_svg,
        "guardar_svg": guardar_svg,
    }.items():
        entorno.definir(nombre, FuncionNativa(nombre, funcion))
