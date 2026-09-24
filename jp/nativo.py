"""JP nativo: compila funciones JP a código de máquina x86-64 y las ejecuta.

Esto es un JIT de verdad (como LuaJIT o PyPy, en miniatura): un ensamblador
que emite bytes, mmap RWX y ejecución directa por la CPU. Sin intérprete.

Alcance:
    - Modo ENTERO: + - * % y comparaciones, enteros de 64 bits (desborde C).
    - Modo FLOTANTE (SSE2): + - * / y comparaciones en double, con constantes
      en un pool por función (referenciado RIP-relativo). El modo se decide
      POR LOTE: si cualquier función usa '/' o literales decimales, todo el
      lote compila en double (ABI uniforme: args por xmm0-2 según SysV).
      Diferencia documentada con la VM: los enteros de 64 bits no crecen sin
      límite, y una comparación usada como valor devuelve 0/1 en vez de
      falso/verdadero.
    - Sentencias: var, si/sino, mientras, para..en (rangos), devuelve.
    - Hasta 3 parámetros y 16 slots de 8 bytes. Recursión nativa entre
      funciones del lote.

Cada temporal tiene SU propio slot (sin reuso). Lo que no califica se queda
en la VM normal, que es siempre correcta.
"""

from __future__ import annotations

import ctypes
import struct

from .arbol import (
    Nodo,
    NodoAsignacion,
    NodoBinario,
    NodoBloque,
    NodoDeclaracionVar,
    NodoExpresion,
    NodoFuncion,
    NodoLlamada,
    NodoMientras,
    NodoNumero,
    NodoPara,
    NodoRango,
    NodoRetorna,
    NodoSi,
    NodoUnario,
    NodoVariable,
)
from .errores import ErrorEjecucion

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
XMM0, XMM1, XMM2 = 0, 1, 2

_REGS_ARG = [RDI, RSI, RDX]      # 1º, 2º, 3er parámetro (SysV entero)
_XMM_ARG = [XMM0, XMM1, XMM2]    # parámetros flotantes (SysV double)
_MAX_PARAMS = 3
_BYTES_LOCALES = 128             # 16 slots de 8 bytes
_LIMITE_SLOTS = 16

_OPS_INT = ("+", "-", "*", "%")
_OPS_FLOAT = ("+", "-", "*", "/")


def _rex(w: bool, r: bool, x: bool, b: bool) -> bytes:
    valor = 0x40 | (int(w) << 3) | (int(r) << 2) | (int(x) << 1) | int(b)
    return b"" if valor == 0x40 else bytes([valor])


def _modrm(mod: int, reg: int, rm: int) -> bytes:
    return bytes([(mod << 6) | ((reg & 7) << 3) | (rm & 7)])


def _i32(valor: int) -> bytes:
    return (valor & 0xFFFFFFFF).to_bytes(4, "little")


def _i64(valor: int) -> bytes:
    return (valor & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")


class FalloCompilacion(Exception):
    """El código no califica para el JIT (se ejecuta en la VM, sin drama)."""


def _necesita_flotante(programa) -> bool:
    """¿Algún uso de '/' o literal con punto (aunque sea 1.0) en las funciones?"""

    def recorre(nodo: Nodo) -> bool:
        if isinstance(nodo, NodoBinario) and nodo.operador == "/":
            return True
        if isinstance(nodo, NodoNumero) and isinstance(nodo.valor, float):
            return True
        for hijo in getattr(nodo, "cuerpo", None) and [nodo.cuerpo] or []:
            if recorre(hijo):
                return True
        for nombre in ("izquierda", "derecha", "operando", "expresion",
                       "condicion", "iterable", "valor", "inicializador"):
            hijo = getattr(nodo, nombre, None)
            if isinstance(hijo, Nodo) and recorre(hijo):
                return True
        for hijo in getattr(nodo, "sentencias", []) or []:
            if recorre(hijo):
                return True
        for hijo in getattr(nodo, "argumentos", []) or []:
            if recorre(hijo):
                return True
        return False

    return any(recorre(nodo) for nodo in programa.sentencias if isinstance(nodo, NodoFuncion))


# ---------------- ensamblador ----------------

class Ensamblador:
    """Emite bytes x86-64 con etiquetas rel32 (se resuelven al enlazar)."""

    def __init__(self) -> None:
        self.codigo = bytearray()
        self.etiquetas: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []

    def emitir(self, *bytes_) -> None:
        for trozo in bytes_:
            self.codigo.extend(trozo)

    def aqui(self) -> int:
        return len(self.codigo)

    def etiqueta(self, nombre: str) -> None:
        self.etiquetas[nombre] = self.aqui()

    def _hueco_rel32(self, etiqueta: str) -> None:
        self.fixups.append((self.aqui(), etiqueta))
        self.emitir(_i32(0))

    def resolver(self, bases: dict[str, int]) -> None:
        for posicion, etiqueta in self.fixups:
            rel = bases[etiqueta] - (posicion + 4)
            self.codigo[posicion:posicion + 4] = _i32(rel)

    # ---------- movimiento (enteros) ----------

    def mov_reg_imm(self, reg: int, valor: int) -> None:
        if -0x80000000 <= valor < 0x80000000:
            self.emitir(_rex(True, False, False, reg >= 8), b"\xC7", _modrm(3, 0, reg), _i32(valor))
        else:
            self.emitir(_rex(True, False, False, reg >= 8), bytes([0xB8 | (reg & 7)]), _i64(valor))

    def mov_reg_reg(self, dst: int, src: int) -> None:
        self.emitir(_rex(True, src >= 8, False, dst >= 8), b"\x89", _modrm(3, src, dst))

    def mov_reg_mem(self, reg: int, disp: int) -> None:
        self.emitir(_rex(True, reg >= 8, False, False), b"\x8B", _modrm(1, reg, RBP), bytes([disp & 0xFF]))

    def mov_mem_reg(self, disp: int, reg: int) -> None:
        self.emitir(_rex(True, reg >= 8, False, False), b"\x89", _modrm(1, reg, RBP), bytes([disp & 0xFF]))

    # ---------- aritmética (enteros) ----------

    def arit_ri(self, op: str, dst: int, valor: int) -> None:
        if not -0x80000000 <= valor < 0x80000000:
            raise FalloCompilacion("constante fuera de 32 bits")
        if op == "+":
            self.emitir(_rex(True, False, False, dst >= 8), b"\x81", _modrm(3, 0, dst), _i32(valor))
        elif op == "-":
            self.emitir(_rex(True, False, False, dst >= 8), b"\x81", _modrm(3, 5, dst), _i32(valor))
        elif op == "*":
            self.emitir(_rex(True, False, False, dst >= 8), b"\x69", _modrm(3, dst, dst), _i32(valor))
        else:
            raise FalloCompilacion(f"operador {op} ri")

    def arit_rm(self, op: str, dst: int, disp: int) -> None:
        codigo = {"+": b"\x03", "-": b"\x2B"}.get(op)
        if codigo is not None:
            self.emitir(_rex(True, dst >= 8, False, False), codigo, _modrm(1, dst, RBP), bytes([disp & 0xFF]))
        elif op == "*":
            self.emitir(_rex(True, dst >= 8, False, False), b"\x0F\xAF", _modrm(1, dst, RBP), bytes([disp & 0xFF]))
        else:
            raise FalloCompilacion(f"operador {op} rm")

    def neg_reg(self, reg: int) -> None:
        self.emitir(_rex(True, False, False, reg >= 8), b"\xF7", _modrm(3, 3, reg))

    def modulo(self, dst: int, divisor: int) -> None:
        """dst = RAX % divisor (constante != 0). El dividendo llega en RAX."""
        if divisor == 0:
            raise FalloCompilacion("módulo por cero")
        self.emitir(b"\x48\x99")                     # cqo
        self.mov_reg_imm(RBX, divisor)
        self.emitir(_rex(True, False, False, RBX >= 8), b"\xF7", _modrm(3, 7, RBX))  # idiv rbx
        self.mov_reg_reg(RAX, RDX)                   # resto -> RAX
        if dst != RAX:
            self.mov_mem_reg(dst, RAX)

    # ---------- comparaciones (enteros) ----------

    _SETCC = {"<": 0x9C, ">": 0x9F, "<=": 0x9E, ">=": 0x9D, "==": 0x94, "!=": 0x95}
    _JCC = {"<": 0x8C, ">": 0x8F, "<=": 0x8E, ">=": 0x8D, "==": 0x84, "!=": 0x85}

    def comparar(self, op: str, a: int, b: int = 0, imm: int | None = None, disp: int | None = None) -> None:
        """RAX = (a OP X) ? 1 : 0."""
        if imm is not None:
            self.emitir(_rex(True, False, False, a >= 8), b"\x81", _modrm(3, 7, a), _i32(imm))
        elif disp is not None:
            self.emitir(_rex(True, False, False, a >= 8), b"\x3B", _modrm(1, a, RBP), bytes([disp & 0xFF]))
        else:
            self.emitir(_rex(True, False, False, b >= 8), b"\x3B", _modrm(3, a, b))
        self.emitir(b"\x0F", bytes([self._SETCC[op]]), b"\xC0")
        self.emitir(b"\x0F\xB6\xC0")  # movzx eax, al

    def jmp(self, etiqueta: str, condicion: str | None = None, a: int = 0,
            b: int = 0, imm: int | None = None, disp: int | None = None) -> None:
        if condicion is not None:
            if imm is not None:
                self.emitir(_rex(True, False, False, a >= 8), b"\x81", _modrm(3, 7, a), _i32(imm))
            elif disp is not None:
                self.emitir(_rex(True, False, False, a >= 8), b"\x3B", _modrm(1, a, RBP), bytes([disp & 0xFF]))
            else:
                self.emitir(_rex(True, False, False, b >= 8), b"\x3B", _modrm(3, a, b))
            self.emitir(b"\x0F", bytes([self._JCC[condicion]]))
        else:
            self.emitir(b"\xE9")
        self._hueco_rel32(etiqueta)

    def llamar(self, etiqueta: str) -> None:
        self.emitir(b"\xE8")
        self._hueco_rel32(etiqueta)

    # ---------- SSE2 (flotantes double) ----------

    def movsd_xmm_mem(self, xmm: int, disp: int) -> None:
        self.emitir(b"\xF2\x0F\x10", _modrm(1, xmm, RBP), bytes([disp & 0xFF]))

    def movsd_mem_xmm(self, disp: int, xmm: int) -> None:
        self.emitir(b"\xF2\x0F\x11", _modrm(1, xmm, RBP), bytes([disp & 0xFF]))

    def movsd_xmm_xmm(self, dst: int, src: int) -> None:
        self.emitir(b"\xF2\x0F\x11", _modrm(3, src, dst))

    def movsd_xmm_rip(self, xmm: int, etiqueta: str) -> None:
        # xmm <- [rip+etiqueta]: el DESTINO va en el campo reg del ModRM
        # (mod=0, rm=101 = RIP-relativo). Hardcodear \x05 cargaba siempre xmm0.
        self.emitir(b"\xF2\x0F\x10", _modrm(0, xmm, 5))
        self._hueco_rel32(etiqueta)

    _ARIT_XMM = {"+": 0x58, "-": 0x5C, "*": 0x59, "/": 0x5E}

    def arit_xmm_xmm(self, op: str, dst: int, src: int) -> None:
        self.emitir(b"\xF2\x0F", bytes([self._ARIT_XMM[op]]), _modrm(3, dst, src))

    def arit_xmm_rip(self, op: str, dst: int, etiqueta: str) -> None:
        # dst op= [rip+etiqueta] (mismo cuidado con el campo reg)
        self.emitir(b"\xF2\x0F", bytes([self._ARIT_XMM[op]]), _modrm(0, dst, 5))
        self._hueco_rel32(etiqueta)

    def arit_xmm_mem(self, op: str, xmm: int, disp: int) -> None:  # xmm op= [rbp+disp]
        self.emitir(b"\xF2\x0F", bytes([self._ARIT_XMM[op]]), _modrm(1, xmm, RBP), bytes([disp & 0xFF]))

    _SETCC_F = {"<": 0x92, ">": 0x97, "<=": 0x96, ">=": 0x93, "==": 0x94, "!=": 0x95}
    _JCC_F = {"<": 0x82, ">": 0x87, "<=": 0x86, ">=": 0x83, "==": 0x84, "!=": 0x85}

    def comparar_flotante(self, op: str, a: int, b: int) -> None:
        """Tras ucomisd a,b: setcc + resultado 0.0/1.0 en el registro `a`."""
        self.ucomisd(a, b)
        self.emitir(b"\x0F", bytes([self._SETCC_F[op]]), b"\xC0")  # setcc al
        self.emitir(b"\x0F\xB6\xC0")                               # movzx eax, al
        self.cvt_si2sd(a, RAX)                                     # a = (double)eax

    def ucomisd(self, a: int, b: int) -> None:
        self.emitir(b"\x66\x0F\x2E", _modrm(3, a, b))

    def jmp_flotante(self, etiqueta: str, condicion: str, a: int, b: int) -> None:
        self.ucomisd(a, b)
        self.emitir(b"\x0F", bytes([self._JCC_F[condicion]]))
        self._hueco_rel32(etiqueta)

    def cvt_si2sd(self, xmm: int, reg: int) -> None:
        self.emitir(_rex(True, xmm >= 8, False, reg >= 8), b"\xF2\x0F\x2A", _modrm(3, xmm, reg))

    # ---------- marco ----------

    def prologo(self, vuelco: list[tuple[int, int]], flotante: bool) -> None:
        """push salvados; sub rsp; vuelca argumentos a sus slots."""
        self.emitir(b"\x55")                        # push rbp
        self.emitir(b"\x48\x89\xE5")                # mov rbp, rsp
        self.emitir(b"\x53")                        # push rbx
        self.emitir(b"\x41\x54\x41\x55\x41\x56")    # push r12, r13, r14
        self.emitir(_rex(True, False, False, False), b"\x81", _modrm(3, 5, RSP), _i32(_BYTES_LOCALES))
        for registro, disp in vuelco:
            if flotante:
                self.movsd_mem_xmm(disp, registro)
            else:
                self.mov_mem_reg(disp, registro)

    def epilogo(self) -> None:
        self.emitir(_rex(True, False, False, False), b"\x81", _modrm(3, 0, RSP), _i32(_BYTES_LOCALES))
        self.emitir(b"\x41\x5E\x41\x5D\x41\x5C")    # pop r14, r13, r12
        self.emitir(b"\x5B\x5D\xC3")                # pop rbx; pop rbp; ret


# ---------------- compilador JP -> nativo ----------------

class _Fun:
    def __init__(self, nombre: str, aridad: int):
        self.nombre = nombre
        self.aridad = aridad
        self.asm = Ensamblador()
        self.slots: dict[str, int] = {}
        self._proxima = -8
        self._temporal = 0
        self.constantes: dict[float, str] = {}  # valor -> etiqueta del pool

    def slot_de(self, nombre: str) -> int:
        if nombre in self.slots:
            return self.slots[nombre]
        if len(self.slots) >= _LIMITE_SLOTS:
            raise FalloCompilacion("demasiadas variables/temporales")
        self.slots[nombre] = self._proxima
        self._proxima -= 8
        return self.slots[nombre]

    def slot_temporal(self) -> int:
        self._temporal += 1
        return self.slot_de(f"%t{self._temporal}")

    def etiqueta_constante(self, valor: float) -> str:
        if valor not in self.constantes:
            self.constantes[valor] = f"c{len(self.constantes)}"
        return self.constantes[valor]


class _Comp:
    """Compila un lote en UN modo (entero o flotante) para ABI uniforme.

    `prim` es el registro de resultado: RAX (entero) o XMM0 (flotante,
    representado por el centinela -1 porque los disp de memoria son negativos).
    """

    def __init__(self, nombres: set[str], flotante: bool):
        self.funciones: dict[str, _Fun] = {}
        self.actual: _Fun = None  # type: ignore[assignment]
        self.nombres = nombres
        self.flotante = flotante
        self.prim = -1 if flotante else RAX

    # ---------- función ----------

    def compilar(self, nodo: NodoFuncion) -> None:
        if len(nodo.parametros) > _MAX_PARAMS:
            raise FalloCompilacion("máximo 3 parámetros")
        fun = _Fun(nodo.nombre, len(nodo.parametros))
        self.funciones[nodo.nombre] = fun
        self.actual = fun
        registros = _XMM_ARG if self.flotante else _REGS_ARG
        vuelco = []
        for registro, parametro in zip(registros, nodo.parametros):
            disp = fun.slot_de(parametro)
            vuelco.append((registro, disp))
        fun.asm.prologo(vuelco, self.flotante)
        for sentencia in nodo.cuerpo.sentencias:
            self._sentencia(sentencia)
        self._cero_en_prim()
        fun.asm.etiqueta(".epi")
        fun.asm.epilogo()
        self._agregar_pool(fun)

    def _cero_en_prim(self) -> None:
        if self.flotante:
            self.actual.asm.movsd_xmm_rip(XMM0, self.actual.etiqueta_constante(0.0))
        else:
            self.actual.asm.mov_reg_imm(RAX, 0)

    def _agregar_pool(self, fun: _Fun) -> None:
        """Constantes double al final del código (alineadas a 8) para RIP-rel.

        Deja 16 bytes de colchón tras el epílogo: el epilogo() emite ~19 bytes
        y sin colchón el pool pisaría el 'ret' del código (bug real)."""
        asm = fun.asm
        asm.emitir(b"\x90" * 16)          # colchón post-epílogo
        while asm.aqui() % 8:
            asm.emitir(b"\x90")
        for valor, etiqueta in sorted(fun.constantes.items(), key=lambda par: par[1]):
            asm.etiqueta(etiqueta)
            asm.emitir(struct.pack("<d", float(valor)))

    # ---------- primitivas según modo ----------

    def _carga_constante(self, valor: float) -> None:
        """prim = valor (como entero o como double)."""
        asm = self.actual.asm
        if self.flotante:
            asm.movsd_xmm_rip(XMM0, self.actual.etiqueta_constante(float(valor)))
        else:
            entero = int(valor)
            if entero != valor or not -0x80000000 <= entero < 0x80000000:
                raise FalloCompilacion("literal no cabe en modo entero")
            asm.mov_reg_imm(RAX, entero)

    def _guarda_prim(self, disp: int) -> None:
        asm = self.actual.asm
        if disp == self.prim:
            return
        if self.flotante:
            asm.movsd_mem_xmm(disp, XMM0)
        else:
            asm.mov_mem_reg(disp, RAX)

    def _carga_desde_mem(self, disp: int) -> None:
        asm = self.actual.asm
        if self.flotante:
            asm.movsd_xmm_mem(XMM0, disp)
        else:
            asm.mov_reg_mem(RAX, disp)

    def _carga_variable(self, nombre: str) -> None:
        if nombre not in self.actual.slots:
            raise FalloCompilacion(f"variable no declarada: {nombre}")
        self._carga_desde_mem(self.actual.slots[nombre])

    def _temporal_hacia(self, nodo: Nodo) -> int:
        """Evalúa `nodo` a un slot temporal fresco y devuelve su disp."""
        disp = self.actual.slot_temporal()
        self._expresion(nodo, disp)
        return disp

    # ---------- sentencias ----------

    def _sentencia(self, nodo: Nodo) -> None:
        tipo = type(nodo)

        if tipo is NodoDeclaracionVar:
            disp = self.actual.slot_de(nodo.nombre)
            if nodo.inicializador is not None:
                self._expresion(nodo.inicializador, disp)
            else:
                self._cero_en_prim()
                self._guarda_prim(disp)
            return

        if tipo is NodoAsignacion:
            if nodo.nombre not in self.actual.slots:
                raise FalloCompilacion(f"asignación a no declarada: {nodo.nombre}")
            self._expresion(nodo.valor, self.actual.slots[nodo.nombre])
            return

        if tipo is NodoExpresion:
            self._expresion(nodo.expresion, None)
            return

        if tipo is NodoRetorna:
            if nodo.valor is not None:
                self._expresion(nodo.valor, self.prim)
            else:
                self._cero_en_prim()
            self.actual.asm.jmp(".epi")
            return

        if tipo is NodoSi:
            self._si(nodo)
            return
        if tipo is NodoMientras:
            self._mientras(nodo)
            return
        if tipo is NodoPara:
            self._para(nodo)
            return
        if tipo is NodoBloque:
            for sentencia in nodo.sentencias:
                self._sentencia(sentencia)
            return

        raise FalloCompilacion(f"sentencia no soportada: {tipo.__name__}")

    # ---------- control de flujo ----------

    def _si(self, nodo: NodoSi) -> None:
        asm = self.actual.asm
        if nodo.sino is not None:
            self._condicion_salto(nodo.condicion, ".sino", invertir=True)
            for s in nodo.entonces.sentencias:
                self._sentencia(s)
            asm.jmp(".fin")
            asm.etiqueta(".sino")
            for s in nodo.sino.sentencias:
                self._sentencia(s)
            asm.etiqueta(".fin")
        else:
            self._condicion_salto(nodo.condicion, ".fin", invertir=True)
            for s in nodo.entonces.sentencias:
                self._sentencia(s)
            asm.etiqueta(".fin")

    def _mientras(self, nodo: NodoMientras) -> None:
        asm = self.actual.asm
        asm.etiqueta(".vuelta")
        self._condicion_salto(nodo.condicion, ".fin", invertir=True)
        for s in nodo.cuerpo.sentencias:
            self._sentencia(s)
        asm.jmp(".vuelta")
        asm.etiqueta(".fin")

    def _para(self, nodo: NodoPara) -> None:
        if not isinstance(nodo.iterable, NodoRango):
            raise FalloCompilacion("para requiere rango a..b en nativo")
        asm = self.actual.asm
        sufijo = f"{id(nodo) & 0xFFFF:x}"
        i_disp = self.actual.slot_de(nodo.variable)
        d_ini = self.actual.slot_de(f"%ini{sufijo}")
        d_fin = self.actual.slot_de(f"%fin{sufijo}")
        self._expresion(nodo.iterable.izquierda, d_ini)
        self._expresion(nodo.iterable.derecha, d_fin)
        paso = 1
        izq, der = nodo.iterable.izquierda, nodo.iterable.derecha
        if isinstance(izq, NodoNumero) and isinstance(der, NodoNumero) and int(izq.valor) > int(der.valor):
            paso = -1
        self._carga_desde_mem(d_ini)
        self._guarda_prim(i_disp)
        # condición de SALIDA: asciende -> i > fin; desciende -> i < fin
        cond_salida = "<" if paso == -1 else ">"
        asm.etiqueta(".vuelta")
        self._carga_desde_mem(i_disp)
        if self.flotante:
            asm.movsd_xmm_mem(XMM1, d_fin)
            asm.jmp_flotante(".fin", cond_salida, XMM0, XMM1)
        else:
            asm.jmp(".fin", cond_salida, RAX, disp=d_fin)
        for s in nodo.cuerpo.sentencias:
            self._sentencia(s)
        self._carga_desde_mem(i_disp)
        if self.flotante:
            asm.arit_xmm_rip("+" if paso == 1 else "-", XMM0, self.actual.etiqueta_constante(1.0))
        else:
            asm.arit_ri("+" if paso == 1 else "-", RAX, 1)
        self._guarda_prim(i_disp)
        asm.jmp(".vuelta")
        asm.etiqueta(".fin")

    def _condicion_salto(self, cond: Nodo, etiqueta: str, invertir: bool) -> None:
        if not isinstance(cond, NodoBinario) or cond.operador not in ("<", ">", "<=", ">=", "==", "!="):
            raise FalloCompilacion("condición debe ser una comparación numérica")
        op = cond.operador
        if invertir:
            op = {"<": ">=", ">": "<=", "<=": ">", ">=": "<", "==": "!=", "!=": "=="}[op]
        asm = self.actual.asm
        self._expresion(cond.izquierda, self.prim)
        if isinstance(cond.derecha, NodoNumero) and not self.flotante:
            asm.jmp(etiqueta, op, RAX, imm=int(cond.derecha.valor))
        elif self.flotante:
            if isinstance(cond.derecha, NodoNumero):
                asm.movsd_xmm_rip(XMM1, self.actual.etiqueta_constante(float(cond.derecha.valor)))
            else:
                # evaluar la derecha PISA xmm0 (toda carga pasa por prim):
                # respaldar el izquierdo y restaurarlo antes de comparar
                disp_izq = self.actual.slot_temporal()
                asm.movsd_mem_xmm(disp_izq, XMM0)
                disp = self._temporal_hacia(cond.derecha)
                asm.movsd_xmm_mem(XMM1, disp)
                asm.movsd_xmm_mem(XMM0, disp_izq)
            asm.jmp_flotante(etiqueta, op, XMM0, XMM1)
        else:
            disp_izq = self.actual.slot_temporal()
            asm.mov_mem_reg(disp_izq, RAX)
            disp = self._temporal_hacia(cond.derecha)
            asm.mov_reg_mem(RAX, disp_izq)
            asm.jmp(etiqueta, op, RAX, disp=disp)

    # ---------- expresiones ----------

    def _expresion(self, nodo: Nodo, destino: int | None) -> None:
        """Evalúa `nodo` al registro prim y, si `destino` (un disp) difiere,
        guarda ahí. destino None = solo prim."""
        asm = self.actual.asm
        tipo = type(nodo)

        if tipo is NodoNumero:
            self._carga_constante(nodo.valor)
            self._guarda_prim(destino) if destino is not None else None
            return

        if tipo is NodoVariable:
            self._carga_variable(nodo.nombre)
            self._guarda_prim(destino) if destino is not None else None
            return

        if tipo is NodoAsignacion:
            if nodo.nombre not in self.actual.slots:
                raise FalloCompilacion(f"variable no declarada: {nodo.nombre}")
            disp = self.actual.slots[nodo.nombre]
            self._expresion(nodo.valor, disp)
            self._carga_desde_mem(disp)
            self._guarda_prim(destino) if destino is not None else None
            return

        if tipo is NodoUnario and nodo.operador == "-":
            self._expresion(nodo.operando, self.prim)
            if self.flotante:
                # -x = x * (-1.0), con la constante en el pool
                asm.arit_xmm_rip("*", XMM0, self.actual.etiqueta_constante(-1.0))
            else:
                asm.neg_reg(RAX)
            self._guarda_prim(destino) if destino is not None else None
            return

        if tipo is NodoBinario:
            self._binario(nodo, destino)
            return

        if tipo is NodoLlamada:
            self._llamada(nodo, destino)
            return

        raise FalloCompilacion(f"expresión no soportada: {tipo.__name__}")

    def _binario(self, nodo: NodoBinario, destino: int | None) -> None:
        op = nodo.operador
        asm = self.actual.asm
        ops = _OPS_FLOAT if self.flotante else _OPS_INT

        if op in ("<", ">", "<=", ">=", "==", "!="):
            self._expresion(nodo.izquierda, self.prim)
            if self.flotante:
                if isinstance(nodo.derecha, NodoNumero):
                    asm.movsd_xmm_rip(XMM1, self.actual.etiqueta_constante(float(nodo.derecha.valor)))
                else:
                    disp = self._temporal_hacia(nodo.derecha)
                    asm.movsd_xmm_mem(XMM1, disp)
                asm.comparar_flotante(op, XMM0, XMM1)   # resultado 0.0/1.0 en xmm0
            else:
                if isinstance(nodo.derecha, NodoNumero):
                    asm.comparar(op, RAX, imm=int(nodo.derecha.valor))
                else:
                    disp_izq = self.actual.slot_temporal()
                    asm.mov_mem_reg(disp_izq, RAX)
                    disp = self._temporal_hacia(nodo.derecha)
                    asm.mov_reg_mem(RAX, disp_izq)
                    asm.comparar(op, RAX, disp=disp)
            self._guarda_prim(destino) if destino is not None else None
            return

        if op not in ops:
            raise FalloCompilacion(f"operador {op} en modo {'flotante' if self.flotante else 'entero'}")

        if op == "%":
            if not (isinstance(nodo.derecha, NodoNumero) and int(nodo.derecha.valor) != 0):
                raise FalloCompilacion("módulo requiere divisor constante != 0")
            self._expresion(nodo.izquierda, self.prim)
            asm.modulo(self.prim, int(nodo.derecha.valor))
            self._guarda_prim(destino) if destino is not None else None
            return

        # izquierda -> prim; derecha -> constante o temporal; combinar.
        # En flotante, respaldar SIEMPRE prim antes de evaluar la derecha
        # (una llamada anidada tumba xmm0).
        self._expresion(nodo.izquierda, self.prim)
        if isinstance(nodo.derecha, NodoNumero) and not self.flotante:
            asm.arit_ri(op, RAX, int(nodo.derecha.valor))
        elif self.flotante:
            if isinstance(nodo.derecha, NodoNumero):
                asm.arit_xmm_rip(op, XMM0, self.actual.etiqueta_constante(float(nodo.derecha.valor)))
            else:
                disp_izq = self.actual.slot_temporal()
                asm.movsd_mem_xmm(disp_izq, XMM0)      # respaldo del izquierdo
                disp = self._temporal_hacia(nodo.derecha)
                asm.movsd_xmm_mem(XMM0, disp_izq)      # restaurar
                asm.arit_xmm_mem(op, XMM0, disp)
        else:
            disp_izq = self.actual.slot_temporal()
            asm.mov_mem_reg(disp_izq, RAX)
            disp = self._temporal_hacia(nodo.derecha)
            asm.mov_reg_mem(RAX, disp_izq)
            asm.arit_rm(op, RAX, disp)
        self._guarda_prim(destino) if destino is not None else None

    def _llamada(self, nodo: NodoLlamada, destino: int | None) -> None:
        asm = self.actual.asm
        if not (isinstance(nodo.callee, NodoVariable) and nodo.callee.nombre in self.nombres):
            raise FalloCompilacion("solo se llaman funciones del lote nativo")
        if len(nodo.argumentos) > _MAX_PARAMS:
            raise FalloCompilacion("demasiados argumentos")
        registros = _XMM_ARG if self.flotante else _REGS_ARG
        disp_args = []
        for argumento in nodo.argumentos:
            disp = self.actual.slot_temporal()
            self._expresion(argumento, disp)
            disp_args.append(disp)
        for registro, disp in zip(registros, disp_args):
            if self.flotante:
                asm.movsd_xmm_mem(registro, disp)
            else:
                asm.mov_reg_mem(registro, disp)
        asm.llamar("fn:" + nodo.callee.nombre)
        self._guarda_prim(destino) if destino is not None else None


# ---------------- memoria ejecutable ----------------

class _Pagina:
    def __init__(self, codigo: bytes):
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mmap.restype = ctypes.c_void_p
        libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
        libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        tamano = (len(codigo) + 4095) // 4096 * 4096
        self.libc = libc
        self.tamano = tamano
        self.direccion = libc.mmap(None, tamano, 7, 0x22, -1, 0)
        if self.direccion in (-1, None):
            raise MemoryError("mmap RWX no disponible (¿SELinux/cage?)")
        ctypes.memmove(self.direccion, codigo, len(codigo))

    def en(self, offset: int):
        return self.direccion + offset

    def liberar(self) -> None:
        if getattr(self, "direccion", None) not in (-1, None):
            self.libc.munmap(self.direccion, self.tamano)
        self.direccion = None


# ---------------- API pública ----------------

class GrupoNativo:
    def __init__(self) -> None:
        self.pagina: _Pagina | None = None
        self.funciones: dict[str, object] = {}

    def liberar(self) -> None:
        if self.pagina is not None:
            self.pagina.liberar()


def compilar_lote(programa) -> GrupoNativo:
    grupo = GrupoNativo()
    candidatos = [n for n in programa.sentencias if isinstance(n, NodoFuncion)]
    if not candidatos:
        return grupo

    flotante = _necesita_flotante(programa)
    comp = _Comp({nodo.nombre for nodo in candidatos}, flotante)
    funs: list[_Fun] = []
    for nodo in candidatos:
        try:
            comp.compilar(nodo)
            funs.append(comp.funciones[nodo.nombre])
        except FalloCompilacion:
            continue

    if not funs:
        return grupo

    bases: dict[str, int] = {}
    offset = 0
    for fun in funs:
        bases[fun.nombre] = offset
        offset += len(fun.asm.codigo)
        offset += (8 - offset % 8) % 8
    for fun in funs:
        # los fixups son rel32 en coordenadas LOCALES: etiquetas internas tal
        # cual; referencias a otras funciones, traducidas al sistema local
        ambito = dict(fun.asm.etiquetas)
        base = bases[fun.nombre]
        for otra, base_otra in bases.items():
            ambito.setdefault(f"fn:{otra}", base_otra - base)
        fun.asm.resolver(ambito)

    codigo = bytearray()
    for fun in funs:
        codigo.extend(fun.asm.codigo)
        codigo.extend(b"\x90" * ((8 - len(codigo) % 8) % 8))

    grupo.pagina = _Pagina(bytes(codigo))

    from .interprete import FuncionNativa

    for fun in funs:
        if flotante:
            firma = ctypes.CFUNCTYPE(ctypes.c_double, *([ctypes.c_double] * fun.aridad))
        else:
            firma = ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_int64] * fun.aridad))
        cruda = firma(grupo.pagina.en(bases[fun.nombre]))
        modo_flotante = flotante

        def hacer(nombre, aridad, cruda=cruda, modo_flotante=modo_flotante):
            def llamada(*argumentos):
                if len(argumentos) != aridad or any(
                    isinstance(a, bool) or not isinstance(a, (int, float)) for a in argumentos
                ):
                    raise ErrorEjecucion(
                        f"la función nativa '{nombre}' espera {aridad} número(s)"
                    )
                if modo_flotante:
                    resultado = cruda(*[float(a) for a in argumentos])
                    # paridad con JP: 5.0 se devuelve como entero 5
                    if isinstance(resultado, float) and resultado.is_integer():
                        return int(resultado)
                    return resultado
                # modo entero: 5.0 entra como 5; 5.5 se rechaza con mensaje
                enteros = []
                for a in argumentos:
                    if isinstance(a, float):
                        if not a.is_integer():
                            raise ErrorEjecucion(
                                f"la función nativa '{nombre}' espera enteros "
                                f"(recibió {a}); usa una función con división "
                            )
                        a = int(a)
                    enteros.append(a)
                return cruda(*enteros)

            return llamada

        grupo.funciones[fun.nombre] = FuncionNativa(fun.nombre, hacer(fun.nombre, fun.aridad), aridad=fun.aridad)
    return grupo


def instalar(programa, maquina) -> int:
    """Compila y reemplaza en el entorno las funciones que califican."""
    try:
        grupo = compilar_lote(programa)
    except Exception:
        return 0
    if not grupo.funciones:
        return 0
    entorno = maquina.globals if hasattr(maquina, "globals") else maquina.global_env.variables
    instaladas = 0
    for nombre, funcion_nativa in grupo.funciones.items():
        entorno[nombre] = funcion_nativa
        if hasattr(maquina, "resguardadas"):
            maquina.resguardadas.add(nombre)
        instaladas += 1
    return instaladas
