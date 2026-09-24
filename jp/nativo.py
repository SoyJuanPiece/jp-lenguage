"""JP nativo: compila funciones JP a código de máquina x86-64 y las ejecuta.

Esto es un JIT de verdad (como LuaJIT o PyPy, en miniatura): un ensamblador
que emite bytes, mmap RWX y ejecución directa por la CPU. Sin intérprete.

Alcance (a propósito, para garantizar corrección):
    - Funciones cuyo cálculo es ENTEROS de 64 bits (desborde tipo C).
    - Operadores: + - * % y comparaciones < > <= >= == !=.
    - Sentencias: var, si/sino, mientras, para..en (rangos), devuelve.
    - Hasta 3 parámetros (SysV: rdi, rsi, rdx) y 16 slots de 8 bytes.
    - Recursión nativa: las funciones del lote se llaman entre sí.

Cada temporal tiene SU propio slot (sin reuso): las expresiones anidadas no
se pisan nunca. Lo que no califica (límite de slots, tipos raros) se queda
en la VM normal, que es siempre correcta. Convención de llamada: SysV x86-64;
RAX devuelve el resultado; el callee preserva rbx y r12-r14.
"""

from __future__ import annotations

import ctypes

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

_REGS_ARG = [RDI, RSI, RDX]  # 1º, 2º, 3er parámetro (SysV)
_MAX_PARAMS = 3
_BYTES_LOCALES = 128         # 16 slots de 8 bytes (fijo, simple y suficiente)
_LIMITE_SLOTS = 16


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

    # ---------- movimiento ----------

    def mov_reg_imm(self, reg: int, valor: int) -> None:
        if -0x80000000 <= valor < 0x80000000:
            self.emitir(_rex(True, False, False, reg >= 8), b"\xC7", _modrm(3, 0, reg), _i32(valor))
        else:
            self.emitir(_rex(True, False, False, reg >= 8), bytes([0xB8 | (reg & 7)]), _i64(valor))

    def mov_reg_reg(self, dst: int, src: int) -> None:       # dst <- src
        self.emitir(_rex(True, src >= 8, False, dst >= 8), b"\x89", _modrm(3, src, dst))

    def mov_reg_mem(self, reg: int, disp: int) -> None:      # reg <- [rbp+disp]
        self.emitir(_rex(True, reg >= 8, False, False), b"\x8B", _modrm(1, reg, RBP), bytes([disp & 0xFF]))

    def mov_mem_reg(self, disp: int, reg: int) -> None:      # [rbp+disp] <- reg
        self.emitir(_rex(True, reg >= 8, False, False), b"\x89", _modrm(1, reg, RBP), bytes([disp & 0xFF]))

    # ---------- aritmética ----------

    def arit_rr(self, op: str, dst: int, src: int) -> None:  # dst op= src
        codigo = {"+": b"\x01", "-": b"\x29"}.get(op)
        if codigo is not None:
            self.emitir(_rex(True, src >= 8, False, dst >= 8), codigo, _modrm(3, src, dst))
        elif op == "*":  # imul dst, src
            self.emitir(_rex(True, dst >= 8, False, src >= 8), b"\x0F\xAF", _modrm(3, dst, src))
        else:
            raise FalloCompilacion(f"operador {op} rr")

    def arit_ri(self, op: str, dst: int, valor: int) -> None:  # dst op= imm
        if not -0x80000000 <= valor < 0x80000000:
            raise FalloCompilacion("constante fuera de 32 bits")
        if op == "+":
            self.emitir(_rex(True, False, False, dst >= 8), b"\x81", _modrm(3, 0, dst), _i32(valor))
        elif op == "-":
            self.emitir(_rex(True, False, False, dst >= 8), b"\x81", _modrm(3, 5, dst), _i32(valor))
        elif op == "*":  # imul dst, dst, imm
            self.emitir(_rex(True, False, False, dst >= 8), b"\x69", _modrm(3, dst, dst), _i32(valor))
        else:
            raise FalloCompilacion(f"operador {op} ri")

    def arit_rm(self, op: str, dst: int, disp: int) -> None:  # dst op= [rbp+disp]
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
        """dst = dst % divisor (divisor constante != 0). El dividendo llega en RAX."""
        if divisor == 0:
            raise FalloCompilacion("módulo por cero")
        self.emitir(b"\x48\x99")                     # cqo: RDX:RAX = signo(RAX)
        self.mov_reg_imm(RBX, divisor)
        # idiv rbx: ojo, RBX es r3 -> el bit B del REX va en 0 (con B=1 sería r11)
        self.emitir(_rex(True, False, False, RBX >= 8), b"\xF7", _modrm(3, 7, RBX))
        self.mov_reg_reg(RAX, RDX)                   # el resto vive en RDX -> RAX
        if dst != RAX:
            self.mov_mem_reg(dst, RAX)

    # ---------- comparaciones ----------

    _SETCC = {"<": 0x9C, ">": 0x9F, "<=": 0x9E, ">=": 0x9D, "==": 0x94, "!=": 0x95}

    def comparar(self, op: str, a: int, b: int = 0, imm: int | None = None, disp: int | None = None) -> None:
        """RAX = (a OP X) ? 1 : 0, con X = imm | [rbp+disp] | registro b."""
        if imm is not None:
            self.emitir(_rex(True, False, False, a >= 8), b"\x81", _modrm(3, 7, a), _i32(imm))
        elif disp is not None:
            self.emitir(_rex(True, False, False, a >= 8), b"\x3B", _modrm(1, a, RBP), bytes([disp & 0xFF]))
        else:
            self.emitir(_rex(True, False, False, b >= 8), b"\x3B", _modrm(3, a, b))
        self.emitir(b"\x0F", bytes([self._SETCC[op]]), b"\xC0")  # setcc al
        self.emitir(b"\x0F\xB6\xC0")                             # movzx eax, al

    # ---------- saltos ----------

    _JCC = {"<": 0x8C, ">": 0x8F, "<=": 0x8E, ">=": 0x8D, "==": 0x84, "!=": 0x85}

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

    # ---------- marco ----------

    def prologo(self, slots_params: list[tuple[int, int]]) -> None:
        """push salvados; sub rsp; vuelca args SysV a sus slots [rbp+disp]."""
        self.emitir(b"\x55")                        # push rbp
        self.emitir(b"\x48\x89\xE5")                # mov rbp, rsp
        self.emitir(b"\x53")                        # push rbx
        self.emitir(b"\x41\x54\x41\x55\x41\x56")    # push r12, r13, r14
        self.emitir(_rex(True, False, False, False), b"\x81", _modrm(3, 5, RSP), _i32(_BYTES_LOCALES))
        for registro, disp in slots_params:         # guarda los parámetros en memoria
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


class _Comp:
    def __init__(self, nombres: set[str]):
        self.funciones: dict[str, _Fun] = {}
        self.actual: _Fun = None  # type: ignore[assignment]
        self.nombres = nombres

    # ---------- función ----------

    def compilar(self, nodo: NodoFuncion) -> None:
        if len(nodo.parametros) > _MAX_PARAMS:
            raise FalloCompilacion("máximo 3 parámetros")
        fun = _Fun(nodo.nombre, len(nodo.parametros))
        self.funciones[nodo.nombre] = fun
        self.actual = fun
        # slots de parámetros PRE-asignados (se vuelcan del registro en el prólogo)
        vuelco = []
        for registro, parametro in zip(_REGS_ARG, nodo.parametros):
            disp = fun.slot_de(parametro)
            vuelco.append((registro, disp))
        fun.asm.prologo(vuelco)
        for sentencia in nodo.cuerpo.sentencias:
            self._sentencia(sentencia)
        fun.asm.mov_reg_imm(RAX, 0)     # retorno implícito nulo (0)
        fun.asm.etiqueta(".epi")
        fun.asm.epilogo()

    # ---------- sentencias ----------

    def _sentencia(self, nodo: Nodo) -> None:
        tipo = type(nodo)
        asm = self.actual.asm

        if tipo is NodoDeclaracionVar:
            disp = self.actual.slot_de(nodo.nombre)
            if nodo.inicializador is not None:
                self._expresion_a_mem(nodo.inicializador, disp)
            else:
                asm.mov_reg_imm(RAX, 0)
                asm.mov_mem_reg(disp, RAX)
            return

        if tipo is NodoAsignacion:
            if nodo.nombre not in self.actual.slots:
                raise FalloCompilacion(f"asignación a no declarada: {nodo.nombre}")
            self._expresion_a_mem(nodo.valor, self.actual.slots[nodo.nombre])
            return

        if tipo is NodoExpresion:
            self._expresion(nodo.expresion, None)
            return

        if tipo is NodoRetorna:
            if nodo.valor is not None:
                self._expresion(nodo.valor, RAX)
            else:
                asm.mov_reg_imm(RAX, 0)
            asm.jmp(".epi")
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
        # slots ÚNICOS por bucle (los anidados no se pisan)
        sufijo = f"{id(nodo) & 0xFFFF:x}"
        i_disp = self.actual.slot_de(nodo.variable)
        d_ini = self.actual.slot_de(f"%ini{sufijo}")
        d_fin = self.actual.slot_de(f"%fin{sufijo}")
        self._expresion_a_mem(nodo.iterable.izquierda, d_ini)
        self._expresion_a_mem(nodo.iterable.derecha, d_fin)
        paso = 1
        izq, der = nodo.iterable.izquierda, nodo.iterable.derecha
        if isinstance(izq, NodoNumero) and isinstance(der, NodoNumero) and int(izq.valor) > int(der.valor):
            paso = -1
        asm.mov_reg_mem(RAX, d_ini)
        asm.mov_mem_reg(i_disp, RAX)
        # condición de SALIDA: asciende -> sale cuando i > fin; desciende ->
        # sale cuando i < fin (mismo criterio que range() del árbol)
        cond_salida = "<" if paso == -1 else ">"
        asm.etiqueta(".vuelta")
        asm.mov_reg_mem(RAX, i_disp)
        asm.jmp(".fin", cond_salida, RAX, disp=d_fin)
        for s in nodo.cuerpo.sentencias:
            self._sentencia(s)
        asm.mov_reg_mem(RAX, i_disp)
        asm.arit_ri("+" if paso == 1 else "-", RAX, 1)
        asm.mov_mem_reg(i_disp, RAX)
        asm.jmp(".vuelta")
        asm.etiqueta(".fin")

    def _condicion_salto(self, cond: Nodo, etiqueta: str, invertir: bool) -> None:
        """Salta a `etiqueta` si la condición es (invertir: falsa, si no: verdadera)."""
        if not isinstance(cond, NodoBinario) or cond.operador not in ("<", ">", "<=", ">=", "==", "!="):
            raise FalloCompilacion("condición debe ser una comparación numérica")
        op = cond.operador
        if invertir:
            op = {"<": ">=", ">": "<=", "<=": ">", ">=": "<", "==": "!=", "!=": "=="}[op]
        self._expresion(cond.izquierda, RAX)
        if isinstance(cond.derecha, NodoNumero):
            self.actual.asm.jmp(etiqueta, op, RAX, imm=int(cond.derecha.valor))
        else:
            disp_izq = self.actual.slot_temporal()
            self.actual.asm.mov_mem_reg(disp_izq, RAX)
            disp = self.actual.slot_temporal()
            self._expresion_a_mem(cond.derecha, disp)
            self.actual.asm.mov_reg_mem(RAX, disp_izq)
            self.actual.asm.jmp(etiqueta, op, RAX, disp=disp)

    # ---------- expresiones ----------

    def _expresion_a_mem(self, nodo: Nodo, disp: int) -> None:
        """Evalúa y guarda el resultado en [rbp+disp]."""
        self._expresion(nodo, disp)

    def _expresion(self, nodo: Nodo, destino: int | None) -> None:
        """Evalúa `nodo`. destino: disp de memoria, RAX (valor None no: usa RAX)."""
        asm = self.actual.asm
        tipo = type(nodo)

        if tipo is NodoNumero:
            valor = int(nodo.valor)
            if not -0x80000000 <= valor < 0x80000000:
                raise FalloCompilacion("literal fuera de 32 bits")
            asm.mov_reg_imm(RAX, valor)
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
            return

        if tipo is NodoVariable:
            if nodo.nombre not in self.actual.slots:
                raise FalloCompilacion(f"variable no declarada: {nodo.nombre}")
            asm.mov_reg_mem(RAX, self.actual.slots[nodo.nombre])
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
            return

        if tipo is NodoAsignacion:
            # asignación como expresión: guarda y su valor es lo asignado
            if nodo.nombre not in self.actual.slots:
                raise FalloCompilacion(f"variable no declarada: {nodo.nombre}")
            disp = self.actual.slots[nodo.nombre]
            self._expresion(nodo.valor, disp)
            asm.mov_reg_mem(RAX, disp)
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
            return

        if tipo is NodoUnario and nodo.operador == "-":
            self._expresion(nodo.operando, RAX)
            asm.neg_reg(RAX)
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
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

        if op in ("<", ">", "<=", ">=", "==", "!="):
            self._expresion(nodo.izquierda, RAX)
            if isinstance(nodo.derecha, NodoNumero):
                asm.comparar(op, RAX, imm=int(nodo.derecha.valor))
            else:
                # el lado derecho puede LLAMAR (y las llamadas tumban RAX):
                # guardar el izquierdo en su temporal y restaurarlo después
                disp_izq = self.actual.slot_temporal()
                asm.mov_mem_reg(disp_izq, RAX)
                disp = self.actual.slot_temporal()
                self._expresion_a_mem(nodo.derecha, disp)
                asm.mov_reg_mem(RAX, disp_izq)
                asm.comparar(op, RAX, disp=disp)
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
            return

        if op not in ("+", "-", "*", "%"):
            raise FalloCompilacion(f"operador {op}")

        if op == "%":
            if not (isinstance(nodo.derecha, NodoNumero) and int(nodo.derecha.valor) != 0):
                raise FalloCompilacion("módulo requiere divisor constante != 0")
            self._expresion(nodo.izquierda, RAX)
            asm.modulo(RAX, int(nodo.derecha.valor))  # ya está en RAX
            if destino is not None and destino != RAX:
                asm.mov_mem_reg(destino, RAX)
            return

        # izquierda -> RAX -> temporal (las llamadas del lado derecho tumban
        # RAX); derecha -> constante/temporal; combinar y guardar
        self._expresion(nodo.izquierda, RAX)
        if isinstance(nodo.derecha, NodoNumero):
            asm.arit_ri(op, RAX, int(nodo.derecha.valor))
        else:
            disp_izq = self.actual.slot_temporal()
            asm.mov_mem_reg(disp_izq, RAX)
            disp = self.actual.slot_temporal()
            self._expresion_a_mem(nodo.derecha, disp)
            asm.mov_reg_mem(RAX, disp_izq)
            asm.arit_rm(op, RAX, disp)
        if destino is not None and destino != RAX:
            asm.mov_mem_reg(destino, RAX)

    def _llamada(self, nodo: NodoLlamada, destino: int | None) -> None:
        asm = self.actual.asm
        if not (isinstance(nodo.callee, NodoVariable) and nodo.callee.nombre in self.nombres):
            raise FalloCompilacion("solo se llaman funciones del lote nativo")
        if len(nodo.argumentos) > _MAX_PARAMS:
            raise FalloCompilacion("demasiados argumentos")
        # 1) evaluar TODOS los argumentos a slots propios (las llamadas
        #    anidadas estropearían rdi/rsi/rdx si se movieran al vuelo)
        disp_args = []
        for argumento in nodo.argumentos:
            disp = self.actual.slot_temporal()
            self._expresion_a_mem(argumento, disp)
            disp_args.append(disp)
        # 2) mover a los registros de llamada y llamar
        for registro, disp in zip(_REGS_ARG, disp_args):
            asm.mov_reg_mem(registro, disp)
        asm.llamar("fn:" + nodo.callee.nombre)
        if destino is not None and destino != RAX:
            asm.mov_mem_reg(destino, RAX)


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
        self.direccion = libc.mmap(None, tamano, 7, 0x22, -1, 0)  # RWX | PRIV|ANON
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
    """Compila las funciones top-level elegibles. Las que no, quedan en la VM."""
    grupo = GrupoNativo()
    candidatos = [n for n in programa.sentencias if isinstance(n, NodoFuncion)]
    if not candidatos:
        return grupo

    comp = _Comp({nodo.nombre for nodo in candidatos})
    funs: list[_Fun] = []
    for nodo in candidatos:
        try:
            comp.compilar(nodo)
            funs.append(comp.funciones[nodo.nombre])
        except FalloCompilacion:
            continue

    if not funs:
        return grupo

    # bases (con alineación a 8) y resolución de TODOS los fixups por función
    bases: dict[str, int] = {}
    offset = 0
    for fun in funs:
        bases[fun.nombre] = offset
        offset += len(fun.asm.codigo)
        offset += (8 - offset % 8) % 8
    for fun in funs:
        base = bases[fun.nombre]
        # Los fixups son rel32 en coordenadas LOCALES de cada función: las
        # etiquetas internas quedan tal cual; las referencias a otras funciones
        # se traducen al sistema local (base_otra - base_propia). Sumar la base
        # a las etiquetas internas desplazaría cada salto 'base' bytes.
        ambito = dict(fun.asm.etiquetas)
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
        firma = ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_int64] * fun.aridad))
        cruda = firma(grupo.pagina.en(bases[fun.nombre]))

        def hacer(nombre, aridad, cruda=cruda):
            def llamada(*argumentos):
                if len(argumentos) != aridad or any(
                    isinstance(a, bool) or not isinstance(a, int) for a in argumentos
                ):
                    raise ErrorEjecucion(
                        f"la función nativa '{nombre}' espera {aridad} entero(s) de 64 bits"
                    )
                return cruda(*argumentos)

            return llamada

        grupo.funciones[fun.nombre] = FuncionNativa(fun.nombre, hacer(fun.nombre, fun.aridad), aridad=fun.aridad)
    return grupo


def instalar(programa, maquina) -> int:
    """Compila y reemplaza en el entorno las funciones que califican.

    Devuelve cuántas quedaron nativas. Si algo falla, 0 y todo sigue en la VM.
    """
    try:
        grupo = compilar_lote(programa)
    except Exception:
        return 0
    if not grupo.funciones:
        return 0
    entorno = maquina.globals if hasattr(maquina, "globals") else maquina.global_env.variables
    instaladas = 0
    for nombre, funcion_nativa in grupo.funciones.items():
        # Se instala SIEMPRE bajo el mismo nombre y se RESGUARDA: cuando el
        # programa declare la función JP, DECLARAR (VM) y NodoFuncion (árbol)
        # no pisan la versión nativa gracias a maquina.resguardadas.
        entorno[nombre] = funcion_nativa
        if hasattr(maquina, "resguardadas"):
            maquina.resguardadas.add(nombre)
        instaladas += 1
    return instaladas
