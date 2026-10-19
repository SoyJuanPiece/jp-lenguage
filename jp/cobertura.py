"""Cobertura de ejecución: qué líneas de un programa llegaron a correr.

    jp --cobertura programa.jp

Ejecuta el programa con el intérprete de árbol (el único motor con
gancho por sentencia, como `jp --depurar`) y descuenta cada sentencia
alcanzada de las líneas ejecutables del archivo: al final imprime el
porcentaje y las líneas que nunca se ejecutaron. Sirve para cazar
ramas muertas y ramas sin probar antes de publicar.

La medida es del archivo principal: las líneas de los módulos que
importe no se cuentan (sí se ejecutan, simplemente no se atribuyen).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interprete import Interprete, _NODOS_PASO


def _caminar(raiz):
    pila = [raiz]
    while pila:
        actual = pila.pop()
        yield actual
        for valor in vars(actual).values():
            if hasattr(valor, "__dict__"):
                pila.append(valor)
            elif isinstance(valor, (list, tuple)):
                pila.extend(v for v in valor if hasattr(v, "__dict__"))


def lineas_ejecutables(programa) -> set[int]:
    """Líneas con al menos una sentencia (sobre las que el gancho avisa)."""
    lineas: set[int] = set()
    for nodo in _caminar(programa):
        if type(nodo) in _NODOS_PASO:
            linea = getattr(nodo, "linea", 0)
            if linea:
                lineas.add(linea)
    return lineas


@dataclass
class InformeCobertura:
    ejecutables: set[int] = field(default_factory=set)
    ejecutadas: set[int] = field(default_factory=set)

    @property
    def porcentaje(self) -> float:
        if not self.ejecutables:
            return 100.0
        return 100.0 * len(self.ejecutadas & self.ejecutables) / len(self.ejecutables)

    @property
    def faltantes(self) -> list[int]:
        return sorted(self.ejecutables - self.ejecutadas)

    def texto(self, nombre: str) -> str:
        total = len(self.ejecutables)
        hechas = len(self.ejecutadas & self.ejecutables)
        faltantes = self.faltantes
        partes = [
            f"📊 Cobertura de {nombre}: {self.porcentaje:.0f}% "
            f"({hechas}/{total} líneas ejecutadas)"
        ]
        if faltantes:
            partes.append(f"   Sin ejecutar: líneas {_rangos(faltantes)}")
        else:
            partes.append("   ✔ Todas las líneas se ejecutaron")
        return "\n".join(partes)


def _rangos(lineas: list[int]) -> str:
    """[3, 4, 5, 9] -> '3-5, 9'."""
    grupos: list[str] = []
    inicio = anterior = lineas[0]
    for linea in lineas[1:]:
        if linea == anterior + 1:
            anterior = linea
            continue
        grupos.append(f"{inicio}-{anterior}" if anterior > inicio else f"{inicio}")
        inicio = anterior = linea
    grupos.append(f"{inicio}-{anterior}" if anterior > inicio else f"{inicio}")
    return ", ".join(grupos)


def medir(programa, directorio: str = ".") -> InformeCobertura:
    """Ejecuta el programa y devuelve el informe (la salida sale normal)."""
    informe = InformeCobertura(ejecutables=lineas_ejecutables(programa))
    maquina = Interprete()
    maquina.gancho_paso = lambda nodo, entorno: informe.ejecutadas.add(nodo.linea)
    maquina.ejecutar(programa, directorio=directorio)
    return informe
