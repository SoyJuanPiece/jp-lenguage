/* ============================================================================
 * jpvm — la máquina virtual nativa de JP.
 *
 * Un intérprete de bytecode en C11, sin dependencias (solo libc). Ejecuta
 * blobs .jpb producidos por `jp/compilar_nativo.py` y no necesita Python ni
 * ningún otro lenguaje en tiempo de ejecución: es un binario, como CPython.
 *
 * Diseño:
 *   - Valores de 16 bytes con etiqueta (nulo/booleano/entero/decimal/objeto).
 *   - Pila de valores + marcos con locales en slots (sin diccionarios en el
 *     camino caliente) y upvalues por celda (closures de verdad).
 *   - Despacho con "computed goto" (GCC): un salto indirecto por instrucción.
 *   - Recolector de basura mark-and-sweep para listas, textos, closures y celdas.
 *   - Las constantes enteras y las comparaciones tienen caminos rápidos.
 *
 * Semántica: espejo del intérprete de referencia (jp/interprete.py):
 *   - `+` concatena si hay texto; `*` repite texto; división exacta queda entera.
 *   - `%` es el módulo de Python (piso), no el de C (truncado).
 *   - Solo `nulo` y `falso` son falsos: el 0 es verdadero.
 *   - `1 == verdadero` es falso; `1 == 1.0` es verdadero.
 *   - `muestra`/`imprime` imprimen con jp_a_texto, separados por espacio.
 *   - `para x en 5` itera 1..5; los rangos `a..b` son inclusivos y al revés.
 *
 * Formato .jpb (little-endian):
 *   "JPB1" u32 version u32 n_funciones u32 n_cadenas u32 n_globales u32 reservado
 *   cadenas:  n_cadenas × (u32 largo, bytes UTF-8)
 *   globales: n_globales × u32 índice de cadena
 *   funciones: por cada una
 *       u32 nombre_idx, u32 aridad, u32 n_slots
 *       n_slots × u8 (1 = el slot guarda una celda)
 *       u32 n_upvalues × (u8 es_local, u32 índice)
 *       u32 n_const_i × i64
 *       u32 n_const_d × f64
 *       u32 n_const_s × u32 índice de cadena
 *       u32 n_codigo × bytes
 *       u32 n_lineas × (u32 pc, u32 linea)
 *   u32 n_fuente × bytes (código fuente, para los errores)
 *
 * Uso:
 *   jpvm programa.jpb            ejecuta un bytecode compilado
 *   jpvm --info programa.jpb     muestra cabecera y funciones
 *   jpvm --dumplineas ...        diagnóstico
 *
 * Compilar:  make -C motor-c
 * ==========================================================================*/

#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---------------------------------------------------------------- valores */

typedef enum { T_NULO = 0, T_BOOL, T_INT, T_DBL, T_OBJ } Etiqueta;

typedef struct Obj Obj;
typedef struct {
    uint8_t etiqueta;
    union {
        int64_t entero;
        double decimal;
        Obj *obj;
    } v;
} Valor;

typedef enum { O_TEXTO = 1, O_LISTA, O_FUNCION, O_NATIVA, O_CELDA, O_ITER } TipoObj;

struct Obj {
    uint8_t tipo;
    uint8_t marcado;
    Obj *siguiente;
};

typedef struct {
    Obj cabecera;
    uint32_t largo;
    uint32_t hash;
    char *datos; /* NUL terminado, para interpolar con C */
} Texto;

typedef struct {
    Obj cabecera;
    uint32_t largo;
    uint32_t capacidad;
    Valor *elementos;
} Lista;

typedef struct {
    uint8_t es_local; /* 1 = slot del marco que la crea, 0 = upvalue del padre */
    uint32_t indice;
} DescUpvalue;

typedef struct Funcion {
    uint32_t indice;
    Texto *nombre;
    uint32_t aridad;
    uint32_t n_slots;
    uint8_t *flags_celda;
    uint32_t n_upvalues;
    DescUpvalue *upvalues;
    uint32_t n_const_i, n_const_d, n_const_s;
    int64_t *const_i;
    double *const_d;
    Texto **const_s;
    uint32_t *codigo;
    uint32_t largo_codigo;
    uint32_t n_lineas;
    uint32_t *lineas; /* pares (pc, linea) */
} Funcion;

typedef struct {
    Obj cabecera;
    Funcion *funcion;
    uint32_t n_upvalues;
    Obj **upvalues; /* celdas */
} Cierre;

typedef struct VM VM;

typedef Valor (*NativaPtr)(VM *vm, int argc, Valor *args);

typedef struct {
    Obj cabecera;
    const char *nombre;
    int8_t aridad; /* -1 = varargs */
    NativaPtr funcion;
} Nativa;

typedef struct {
    Obj cabecera;
    Valor valor;
} Celda;

typedef struct {
    Obj cabecera;
    Lista *lista;
    uint32_t indice;
} Iter;

typedef struct {
    Funcion *funcion;
    Valor *base;      /* primer local */
    uint32_t *ip;
    Obj **upvalues;
    uint32_t n_upvalues;
} Marco;

/* ---------------------------------------------------------------- la VM */

#define PILA_MAX 65536
#define MARCOS_MAX 4096
#define GLOBALES_MAX 4096

typedef struct {
    Texto *nombre;
    Valor valor;
    uint8_t definido;
} Global;

struct VM {
    Valor pila[PILA_MAX];
    Valor *sp;
    Marco marcos[MARCOS_MAX];
    Marco *marco;
    Global globales[GLOBALES_MAX];
    uint32_t n_globales;
    jmp_buf salto_error;
    char error[512];
    uint32_t linea_error;
    Valor ultimo_valor;
    Lista *iter_nulo;
    /* cadenas del programa (no son basura) */
    Texto **cadenas;
    uint32_t n_cadenas;
    Funcion *funciones;
    uint32_t n_funciones;
    char *fuente;
    uint32_t largo_fuente;
    Obj *objetos;        /* lista de todos los objetos para el GC */
    size_t bytes_reservados;
    size_t umbral_gc;
    int nativos_instalados;
};

static VM vm_global;
static VM *vm = &vm_global;

/* ----------------------------------------------------------- utilidades */

static void *memoria(size_t bytes) {
    void *p = malloc(bytes ? bytes : 1);
    if (!p) {
        fprintf(stderr, "jpvm: sin memoria\n");
        exit(70);
    }
    return p;
}

static uint32_t leer_u32(const uint8_t *b) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) |
           ((uint32_t)b[3] << 24);
}

static uint64_t leer_u64(const uint8_t *b) {
    uint64_t x = 0;
    for (int i = 7; i >= 0; i--) x = (x << 8) | b[i];
    return x;
}

static void error_en(int linea, const char *formato, ...) {
    va_list ap;
    va_start(ap, formato);
    vsnprintf(vm->error, sizeof(vm->error), formato, ap);
    va_end(ap);
    vm->linea_error = (uint32_t)linea;
    longjmp(vm->salto_error, 1);
}

/* ------------------------------------------------------------- objetos */

static void *nuevo_objeto(size_t bytes, uint8_t tipo) {
    Obj *obj = memoria(bytes);
    memset(obj, 0, bytes);
    obj->tipo = tipo;
    obj->siguiente = vm->objetos;
    vm->objetos = obj;
    vm->bytes_reservados += bytes;
    return obj;
}

static Texto *nuevo_texto_largo(const char *datos, uint32_t largo) {
    Texto *t = nuevo_objeto(sizeof(Texto), O_TEXTO);
    t->largo = largo;
    t->datos = memoria(largo + 1);
    if (datos) memcpy(t->datos, datos, largo);
    t->datos[largo] = '\0';
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < largo; i++) {
        h ^= (unsigned char)t->datos[i];
        h *= 16777619u;
    }
    t->hash = h;
    return t;
}

static Texto *nuevo_texto(const char *datos) {
    return nuevo_texto_largo(datos, datos ? (uint32_t)strlen(datos) : 0);
}

static Lista *nueva_lista(uint32_t capacidad) {
    Lista *l = nuevo_objeto(sizeof(Lista), O_LISTA);
    l->largo = 0;
    l->capacidad = capacidad ? capacidad : 4;
    l->elementos = memoria(sizeof(Valor) * l->capacidad);
    return l;
}

static void lista_asegurar(Lista *l, uint32_t necesarios) {
    if (necesarios <= l->capacidad) return;
    while (l->capacidad < necesarios) l->capacidad *= 2;
    Valor *nuevos = memoria(sizeof(Valor) * l->capacidad);
    memcpy(nuevos, l->elementos, sizeof(Valor) * l->largo);
    free(l->elementos);
    l->elementos = nuevos;
}

static void lista_agregar(Lista *l, Valor v) {
    lista_asegurar(l, l->largo + 1);
    l->elementos[l->largo++] = v;
}

static Celda *nueva_celda(Valor v) {
    Celda *c = nuevo_objeto(sizeof(Celda), O_CELDA);
    c->valor = v;
    return c;
}

/* ------------------------------------------------------- constructores */

static Valor de_nulo(void) { Valor v; v.etiqueta = T_NULO; v.v.entero = 0; return v; }
static Valor de_bool(int b) { Valor v; v.etiqueta = T_BOOL; v.v.entero = b ? 1 : 0; return v; }
static Valor de_entero(int64_t i) { Valor v; v.etiqueta = T_INT; v.v.entero = i; return v; }
static Valor de_decimal(double d) { Valor v; v.etiqueta = T_DBL; v.v.decimal = d; return v; }
static Valor de_objeto(Obj *o) { Valor v; v.etiqueta = T_OBJ; v.v.obj = o; return v; }
static Valor de_texto(Texto *t) { return de_objeto((Obj *)t); }
static Valor de_lista(Lista *l) { return de_objeto((Obj *)l); }

static int es_verdad(Valor v) {
    if (v.etiqueta == T_NULO) return 0;
    if (v.etiqueta == T_BOOL) return v.v.entero != 0;
    return 1; /* el 0 es verdadero, como en Ruby */
}

static int es_numero(Valor v) { return v.etiqueta == T_INT || v.etiqueta == T_DBL; }

/* ------------------------------------------------------- texto de JP */

/* Reproduce str(float) de Python (el más corto que vuelve exacto). */
static void decimal_a_texto(double d, char *salida, size_t tamano) {
    if (isnan(d)) { snprintf(salida, tamano, "nan"); return; }
    if (isinf(d)) { snprintf(salida, tamano, d > 0 ? "inf" : "-inf"); return; }
    if (d == floor(d) && fabs(d) < 1e16) {
        snprintf(salida, tamano, "%.0f", d);
        return;
    }
    for (int precision = 1; precision <= 17; precision++) {
        snprintf(salida, tamano, "%.*g", precision, d);
        if (strtod(salida, NULL) == d) return;
    }
}

static void texto_de(Valor v, char *salida, size_t tamano);

static void texto_inspeccion(Valor v, char *salida, size_t tamano) {
    if (v.etiqueta == T_OBJ && v.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)v.v.obj;
        snprintf(salida, tamano, "\"%.*s\"", (int)t->largo, t->datos);
        return;
    }
    texto_de(v, salida, tamano);
}

static void texto_de(Valor v, char *salida, size_t tamano) {
    switch (v.etiqueta) {
        case T_NULO:
            snprintf(salida, tamano, "nulo");
            return;
        case T_BOOL:
            snprintf(salida, tamano, v.v.entero ? "verdadero" : "falso");
            return;
        case T_INT:
            snprintf(salida, tamano, "%lld", (long long)v.v.entero);
            return;
        case T_DBL: {
            double d = v.v.decimal;
            if (d == floor(d) && fabs(d) < 1e18) {
                snprintf(salida, tamano, "%.0f", d);
                return;
            }
            decimal_a_texto(d, salida, tamano);
            return;
        }
        case T_OBJ:
            break;
    }
    Obj *obj = v.v.obj;
    switch (obj->tipo) {
        case O_TEXTO: {
            Texto *t = (Texto *)obj;
            size_t copiar = t->largo < tamano - 1 ? t->largo : tamano - 1;
            memcpy(salida, t->datos, copiar);
            salida[copiar] = '\0';
            return;
        }
        case O_LISTA: {
            Lista *l = (Lista *)obj;
            size_t usado = 0;
            usado += (size_t)snprintf(salida + usado, tamano - usado, "[");
            for (uint32_t i = 0; i < l->largo && usado < tamano; i++) {
                char trozo[1024];
                texto_inspeccion(l->elementos[i], trozo, sizeof(trozo));
                usado += (size_t)snprintf(salida + usado, tamano - usado, "%s%s",
                                          i ? ", " : "", trozo);
            }
            snprintf(salida + usado, tamano - usado, "]");
            return;
        }
        case O_FUNCION:
            snprintf(salida, tamano, "<fun %.*s>",
                     (int)((Cierre *)obj)->funcion->nombre->largo,
                     ((Cierre *)obj)->funcion->nombre->datos);
            return;
        case O_NATIVA:
            snprintf(salida, tamano, "<nativa %s>", ((Nativa *)obj)->nombre);
            return;
        default:
            snprintf(salida, tamano, "<objeto>");
            return;
    }
}

/* --------------------------------------------------------------- GC */

static void marcar(Valor v);
static void marcar_objeto(Obj *obj);

static void marcar_objeto(Obj *obj) {
    if (!obj || obj->marcado) return;
    obj->marcado = 1;
    switch (obj->tipo) {
        case O_LISTA: {
            Lista *l = (Lista *)obj;
            for (uint32_t i = 0; i < l->largo; i++) marcar(l->elementos[i]);
            break;
        }
        case O_FUNCION: {
            Cierre *c = (Cierre *)obj;
            for (uint32_t i = 0; i < c->n_upvalues; i++) marcar_objeto(c->upvalues[i]);
            break;
        }
        case O_CELDA:
            marcar(((Celda *)obj)->valor);
            break;
        case O_ITER:
            marcar_objeto((Obj *)((Iter *)obj)->lista);
            break;
        default:
            break;
    }
}

static void marcar(Valor v) {
    if (v.etiqueta == T_OBJ) marcar_objeto(v.v.obj);
}

static void recolectar(void) {
    for (Valor *p = vm->pila; p < vm->sp; p++) marcar(*p);
    for (Marco *m = vm->marcos; m <= vm->marco; m++) {
        if (!m->funcion) continue;
        for (uint32_t i = 0; i < m->funcion->n_slots; i++) marcar(*(m->base + i));
        for (uint32_t i = 0; i < m->n_upvalues; i++) marcar_objeto(m->upvalues[i]);
    }
    for (uint32_t i = 0; i < vm->n_globales; i++) marcar(vm->globales[i].valor);
    marcar(vm->ultimo_valor);
    /* las funciones y sus constantes nunca se liberan: son el programa */
    size_t vivos = 0, total = 0;
    Obj **enlace = &vm->objetos;
    while (*enlace) {
        Obj *obj = *enlace;
        if (obj->marcado) {
            obj->marcado = 0;
            vivos += 1;
            enlace = &obj->siguiente;
        } else {
            *enlace = obj->siguiente;
            if (obj->tipo == O_TEXTO) free(((Texto *)obj)->datos);
            if (obj->tipo == O_LISTA) free(((Lista *)obj)->elementos);
            if (obj->tipo == O_FUNCION) free(((Cierre *)obj)->upvalues);
            free(obj);
        }
        total += 1;
    }
    (void)total;
    vm->bytes_reservados = 0;
    for (Obj *obj = vm->objetos; obj; obj = obj->siguiente) vm->bytes_reservados += 32;
    vm->umbral_gc = vm->bytes_reservados * 2 + 1024 * 1024;
}

static void quizas_recolectar(void) {
    if (vm->bytes_reservados > vm->umbral_gc) recolectar();
}

/* ------------------------------------------------------- operaciones */

static int textos_iguales(Texto *a, Texto *b) {
    if (a == b) return 1;
    if (a->largo != b->largo) return 0;
    return memcmp(a->datos, b->datos, a->largo) == 0;
}

static int iguales(Valor a, Valor b) {
    if (a.etiqueta == T_BOOL || b.etiqueta == T_BOOL) {
        return a.etiqueta == b.etiqueta && a.v.entero == b.v.entero;
    }
    if (es_numero(a) && es_numero(b)) {
        if (a.etiqueta == T_INT && b.etiqueta == T_INT) return a.v.entero == b.v.entero;
        double x = a.etiqueta == T_INT ? (double)a.v.entero : a.v.decimal;
        double y = b.etiqueta == T_INT ? (double)b.v.entero : b.v.decimal;
        return x == y;
    }
    if (a.etiqueta != b.etiqueta) return 0;
    if (a.etiqueta == T_NULO) return 1;
    if (a.etiqueta == T_OBJ) {
        Obj *oa = a.v.obj, *ob = b.v.obj;
        if (oa->tipo != ob->tipo) return 0;
        if (oa->tipo == O_TEXTO) return textos_iguales((Texto *)oa, (Texto *)ob);
        if (oa->tipo == O_LISTA) {
            Lista *la = (Lista *)oa, *lb = (Lista *)ob;
            if (la->largo != lb->largo) return 0;
            for (uint32_t i = 0; i < la->largo; i++)
                if (!iguales(la->elementos[i], lb->elementos[i])) return 0;
            return 1;
        }
        return oa == ob; /* funciones y celdas: identidad */
    }
    return 0;
}

static void exigir_numeros(Valor a, Valor b, const char *operador, int linea) {
    Valor valores[2] = {a, b};
    for (int i = 0; i < 2; i++) {
        if (valores[i].etiqueta == T_BOOL || !es_numero(valores[i])) {
            char texto[256];
            texto_de(valores[i], texto, sizeof(texto));
            error_en(linea, "el operador '%s' espera números, recibió '%s'", operador, texto);
        }
    }
}

static double a_double(Valor v) {
    return v.etiqueta == T_INT ? (double)v.v.entero : v.v.decimal;
}

static int64_t a_entero(Valor v) {
    return v.etiqueta == T_INT ? v.v.entero : (int64_t)v.v.decimal;
}

/* suma de enteros con promoción a decimal si se desborda */
static Valor suma_enteros(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_add_overflow(a, b, &r)) return de_decimal((double)a + (double)b);
    return de_entero(r);
}

static Valor restar_enteros(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_sub_overflow(a, b, &r)) return de_decimal((double)a - (double)b);
    return de_entero(r);
}

static Valor multiplicar_enteros(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_mul_overflow(a, b, &r)) return de_decimal((double)a * (double)b);
    return de_entero(r);
}

static Valor op_suma(Valor a, Valor b, int linea) {
    /* concatenar si hay texto */
    if ((a.etiqueta == T_OBJ && a.v.obj->tipo == O_TEXTO) ||
        (b.etiqueta == T_OBJ && b.v.obj->tipo == O_TEXTO)) {
        char ta[1024], tb[1024];
        texto_de(a, ta, sizeof(ta));
        texto_de(b, tb, sizeof(tb));
        size_t la = strlen(ta), lb = strlen(tb);
        char *union_texto = memoria(la + lb + 1);
        memcpy(union_texto, ta, la);
        memcpy(union_texto + la, tb, lb + 1);
        Texto *t = nuevo_texto(union_texto);
        free(union_texto);
        return de_texto(t);
    }
    if (a.etiqueta == T_OBJ && b.etiqueta == T_OBJ && a.v.obj->tipo == O_LISTA &&
        b.v.obj->tipo == O_LISTA) {
        Lista *la = (Lista *)a.v.obj, *lb = (Lista *)b.v.obj;
        Lista *nueva = nueva_lista(la->largo + lb->largo);
        for (uint32_t i = 0; i < la->largo; i++) lista_agregar(nueva, la->elementos[i]);
        for (uint32_t i = 0; i < lb->largo; i++) lista_agregar(nueva, lb->elementos[i]);
        return de_lista(nueva);
    }
    exigir_numeros(a, b, "+", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) return suma_enteros(a.v.entero, b.v.entero);
    return de_decimal(a_double(a) + a_double(b));
}

static Valor op_resta(Valor a, Valor b, int linea) {
    exigir_numeros(a, b, "-", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) return restar_enteros(a.v.entero, b.v.entero);
    return de_decimal(a_double(a) - a_double(b));
}

static Valor op_mult(Valor a, Valor b, int linea) {
    if (a.etiqueta == T_OBJ && a.v.obj->tipo == O_TEXTO && es_numero(b)) {
        Texto *t = (Texto *)a.v.obj;
        int64_t veces = a_entero(b);
        if (veces < 0) veces = 0;
        if (t->largo && veces > (int64_t)(64u * 1024 * 1024) / (int64_t)t->largo)
            error_en(linea, "texto repetido demasiado grande");
        size_t total = (size_t)t->largo * (size_t)veces;
        char *datos = memoria(total + 1);
        for (int64_t i = 0; i < veces; i++) memcpy(datos + (size_t)i * t->largo, t->datos, t->largo);
        datos[total] = '\0';
        Texto *nuevo = nuevo_texto_largo(datos, (uint32_t)total);
        free(datos);
        return de_texto(nuevo);
    }
    exigir_numeros(a, b, "*", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) return multiplicar_enteros(a.v.entero, b.v.entero);
    return de_decimal(a_double(a) * a_double(b));
}

static Valor op_div(Valor a, Valor b, int linea) {
    exigir_numeros(a, b, "/", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) {
        if (b.v.entero == 0) error_en(linea, "división por cero");
        /* división exacta: se queda entera, como en el intérprete */
        if (a.v.entero % b.v.entero == 0) return de_entero(a.v.entero / b.v.entero);
        return de_decimal((double)a.v.entero / (double)b.v.entero);
    }
    double divisor = a_double(b);
    if (divisor == 0) error_en(linea, "división por cero");
    return de_decimal(a_double(a) / divisor);
}

/* módulo con piso (el de Python), no el truncado de C */
static Valor op_mod(Valor a, Valor b, int linea) {
    exigir_numeros(a, b, "%", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) {
        if (b.v.entero == 0) error_en(linea, "módulo por cero");
        int64_t r = a.v.entero % b.v.entero;
        if (r != 0 && ((r < 0) != (b.v.entero < 0))) r += b.v.entero;
        return de_entero(r);
    }
    double divisor = a_double(b);
    if (divisor == 0) error_en(linea, "módulo por cero");
    double r = fmod(a_double(a), divisor);
    if (r != 0 && ((r < 0) != (divisor < 0))) r += divisor;
    return de_decimal(r);
}

static Valor op_potencia(Valor a, Valor b, int linea) {
    exigir_numeros(a, b, "**", linea);
    if (a.etiqueta == T_INT && b.etiqueta == T_INT && b.v.entero >= 0) {
        int64_t resultado = 1, base = a.v.entero, exponente = b.v.entero;
        int desbordo = 0;
        while (exponente > 0) {
            if (exponente & 1) {
                if (__builtin_mul_overflow(resultado, base, &resultado)) { desbordo = 1; break; }
            }
            exponente >>= 1;
            if (exponente) {
                if (__builtin_mul_overflow(base, base, &base)) { desbordo = 1; break; }
            }
        }
        if (!desbordo) return de_entero(resultado);
    }
    double base = a_double(a), exponente = a_double(b);
    if (base == 0 && exponente < 0) error_en(linea, "potencia no válida (¿0 elevado a algo negativo?)");
    double r = pow(base, exponente);
    if (isnan(r)) error_en(linea, "la potencia no dio un número real");
    return de_decimal(r);
}

/* ------------------------------------------------------------ cadenas */

static int64_t indice_normalizado(Valor indice, int64_t largo, const char *que, int linea) {
    if (indice.etiqueta == T_BOOL || !es_numero(indice))
        error_en(linea, "el índice de %s debe ser un número", que);
    int64_t i = a_entero(indice);
    if (i < 0) i += largo;
    return i;
}

/* ------------------------------------------------------------ nativas */

static long reloj_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000L + ts.tv_nsec;
}

static Valor nativa_imprime(VM *v, int argc, Valor *args) {
    (void)v;
    for (int i = 0; i < argc; i++) {
        char texto[4096];
        texto_de(args[i], texto, sizeof(texto));
        if (i) putchar(' ');
        fputs(texto, stdout);
    }
    putchar('\n');
    return de_nulo();
}

static Valor nativa_longitud(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1) error_en(0, "longitud() espera 1 argumento");
    Valor x = args[0];
    if (x.etiqueta == T_OBJ && x.v.obj->tipo == O_TEXTO) return de_entero(((Texto *)x.v.obj)->largo);
    if (x.etiqueta == T_OBJ && x.v.obj->tipo == O_LISTA) return de_entero(((Lista *)x.v.obj)->largo);
    char texto[256];
    texto_de(x, texto, sizeof(texto));
    error_en(0, "longitud() espera cadena, lista o diccionario, no '%s'", texto);
    return de_nulo();
}

static int32_t a_entero_estricto(Valor x, const char *nombre) {
    if (x.etiqueta == T_INT) return (int32_t)x.v.entero;
    if (x.etiqueta == T_DBL) return (int32_t)x.v.decimal;
    char texto[256];
    texto_de(x, texto, sizeof(texto));
    error_en(0, "%s() espera un número, no '%s'", nombre, texto);
    return 0;
}

static Valor nativa_entero(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1) error_en(0, "entero() espera 1 argumento");
    Valor x = args[0];
    if (x.etiqueta == T_BOOL) error_en(0, "entero() no acepta booleanos");
    if (x.etiqueta == T_INT) return x;
    if (x.etiqueta == T_DBL) return de_entero((int64_t)x.v.decimal);
    if (x.etiqueta == T_OBJ && x.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)x.v.obj;
        char *fin = NULL;
        double d = strtod(t->datos, &fin);
        if (fin == t->datos) error_en(0, "entero() no puede convertir la cadena '%s'", t->datos);
        return de_entero((int64_t)d);
    }
    char texto[256];
    texto_de(x, texto, sizeof(texto));
    error_en(0, "entero() espera número o cadena, no '%s'", texto);
    return de_nulo();
}

static Valor nativa_numero(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1) error_en(0, "numero() espera 1 argumento");
    Valor x = args[0];
    if (x.etiqueta == T_BOOL) error_en(0, "numero() no acepta booleanos");
    if (x.etiqueta == T_INT) return de_decimal((double)x.v.entero);
    if (x.etiqueta == T_DBL) return x;
    if (x.etiqueta == T_OBJ && x.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)x.v.obj;
        char *fin = NULL;
        double d = strtod(t->datos, &fin);
        if (fin == t->datos) error_en(0, "numero() no puede convertir la cadena '%s'", t->datos);
        return de_decimal(d);
    }
    char texto[256];
    texto_de(x, texto, sizeof(texto));
    error_en(0, "numero() espera número o cadena, no '%s'", texto);
    return de_nulo();
}

static Valor nativa_texto(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1) error_en(0, "texto() espera 1 argumento");
    char buffer[4096];
    texto_de(args[0], buffer, sizeof(buffer));
    return de_texto(nuevo_texto(buffer));
}

static Valor nativa_tipo(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1) error_en(0, "tipo() espera 1 argumento");
    Valor x = args[0];
    switch (x.etiqueta) {
        case T_NULO: return de_texto(nuevo_texto("nulo"));
        case T_BOOL: return de_texto(nuevo_texto("booleano"));
        case T_INT:
        case T_DBL: return de_texto(nuevo_texto("número"));
        default: break;
    }
    switch (x.v.obj->tipo) {
        case O_TEXTO: return de_texto(nuevo_texto("texto"));
        case O_LISTA: return de_texto(nuevo_texto("lista"));
        case O_FUNCION:
        case O_NATIVA: return de_texto(nuevo_texto("función"));
        default: return de_texto(nuevo_texto("valor"));
    }
}

static double exigir_numero(Valor x, const char *nombre) {
    if (x.etiqueta == T_BOOL || !es_numero(x)) {
        char texto[256];
        texto_de(x, texto, sizeof(texto));
        error_en(0, "%s() espera un número, no '%s'", nombre, texto);
    }
    return a_double(x);
}

static Valor nativa_raiz(VM *v, int argc, Valor *args) {
    (void)v;
    double x = exigir_numero(args[0], "raiz");
    if (x < 0) error_en(0, "raiz() de un número negativo");
    return de_decimal(sqrt(x));
}

static Valor nativa_absoluto(VM *v, int argc, Valor *args) {
    (void)v;
    Valor x = args[0];
    if (x.etiqueta == T_INT) return de_entero(x.v.entero < 0 ? -x.v.entero : x.v.entero);
    return de_decimal(fabs(exigir_numero(x, "absoluto")));
}

static Valor nativa_piso(VM *v, int argc, Valor *args) {
    (void)v;
    Valor x = args[0];
    if (x.etiqueta == T_INT) return x;
    return de_entero((int64_t)floor(exigir_numero(x, "piso")));
}

static Valor nativa_techo(VM *v, int argc, Valor *args) {
    (void)v;
    Valor x = args[0];
    if (x.etiqueta == T_INT) return x;
    return de_entero((int64_t)ceil(exigir_numero(x, "techo")));
}

static Valor nativa_redondear(VM *v, int argc, Valor *args) {
    (void)v;
    double x = exigir_numero(args[0], "redondear");
    int cifras = argc > 1 ? a_entero_estricto(args[1], "redondear") : 0;
    double factor = pow(10, cifras);
    double r = round(x * factor) / factor;
    if (cifras <= 0 && r == floor(r) && fabs(r) < 1e18) return de_entero((int64_t)r);
    return de_decimal(r);
}

static Valor nativa_log(VM *v, int argc, Valor *args) {
    (void)v;
    double base = argc > 1 ? exigir_numero(args[1], "log") : 2.718281828459045235360287471352662;
    double x = exigir_numero(args[0], "log");
    if (x <= 0) error_en(0, "log() de un número no positivo");
    return de_decimal(log(x) / log(base));
}

static Valor nativa_exp(VM *v, int argc, Valor *args) {
    (void)v;
    return de_decimal(exp(exigir_numero(args[0], "exp")));
}

static Valor nativa_seno(VM *v, int argc, Valor *args) {
    (void)v;
    return de_decimal(sin(exigir_numero(args[0], "seno")));
}

static Valor nativa_coseno(VM *v, int argc, Valor *args) {
    (void)v;
    return de_decimal(cos(exigir_numero(args[0], "coseno")));
}

static Valor nativa_potencia(VM *v, int argc, Valor *args) {
    (void)v;
    return op_potencia(args[0], args[1], 0);
}

static Valor nativa_minimo(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc == 1 && args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)args[0].v.obj;
        if (!l->largo) error_en(0, "minimo() de una lista vacía");
        Valor mejor = l->elementos[0];
        for (uint32_t i = 1; i < l->largo; i++)
            if (a_double(l->elementos[i]) < a_double(mejor)) mejor = l->elementos[i];
        return mejor;
    }
    Valor mejor = args[0];
    for (int i = 1; i < argc; i++) if (a_double(args[i]) < a_double(mejor)) mejor = args[i];
    return mejor;
}

static Valor nativa_maximo(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc == 1 && args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)args[0].v.obj;
        if (!l->largo) error_en(0, "maximo() de una lista vacía");
        Valor mejor = l->elementos[0];
        for (uint32_t i = 1; i < l->largo; i++)
            if (a_double(l->elementos[i]) > a_double(mejor)) mejor = l->elementos[i];
        return mejor;
    }
    Valor mejor = args[0];
    for (int i = 1; i < argc; i++) if (a_double(args[i]) > a_double(mejor)) mejor = args[i];
    return mejor;
}

static Valor nativa_sumar(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *l;
    if (argc == 1 && args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        l = (Lista *)args[0].v.obj;
    } else {
        l = nueva_lista((uint32_t)argc);
        for (int i = 0; i < argc; i++) lista_agregar(l, args[i]);
    }
    Valor total = de_entero(0);
    for (uint32_t i = 0; i < l->largo; i++) total = op_suma(total, l->elementos[i], 0);
    return total;
}

static Valor nativa_pi(VM *v, int argc, Valor *args) {
    (void)v; (void)argc; (void)args;
    return de_decimal(3.14159265358979323846264338327950288);
}

static Valor nativa_reloj(VM *v, int argc, Valor *args) {
    (void)v; (void)argc; (void)args;
    return de_decimal((double)reloj_ns() / 1e9);
}

static Valor nativa_aleatorio(VM *v, int argc, Valor *args) {
    (void)v; (void)argc; (void)args;
    return de_decimal((double)rand() / ((double)RAND_MAX + 1.0));
}

static Valor nativa_azar(VM *v, int argc, Valor *args) {
    (void)v;
    int64_t n = a_entero_estricto(args[0], "azar");
    if (n <= 0) error_en(0, "azar() espera un número mayor que 0");
    return de_entero(1 + rand() % n);
}

static Valor nativa_mayusculas(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "mayusculas() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    char *copia = memoria(t->largo + 1);
    memcpy(copia, t->datos, t->largo + 1);
    for (uint32_t i = 0; i < t->largo; i++) copia[i] = (char)toupper((unsigned char)copia[i]);
    Texto *nuevo = nuevo_texto_largo(copia, t->largo);
    free(copia);
    return de_texto(nuevo);
}

static Valor nativa_minusculas(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "minusculas() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    char *copia = memoria(t->largo + 1);
    memcpy(copia, t->datos, t->largo + 1);
    for (uint32_t i = 0; i < t->largo; i++) copia[i] = (char)tolower((unsigned char)copia[i]);
    Texto *nuevo = nuevo_texto_largo(copia, t->largo);
    free(copia);
    return de_texto(nuevo);
}

static Valor nativa_recortar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "recortar() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    uint32_t inicio = 0, fin = t->largo;
    while (inicio < fin && isspace((unsigned char)t->datos[inicio])) inicio++;
    while (fin > inicio && isspace((unsigned char)t->datos[fin - 1])) fin--;
    return de_texto(nuevo_texto_largo(t->datos + inicio, fin - inicio));
}

static Valor nativa_contiene(VM *v, int argc, Valor *args) {
    (void)v;
    Valor donde = args[0], que = args[1];
    if (donde.etiqueta == T_OBJ && donde.v.obj->tipo == O_TEXTO) {
        if (que.etiqueta != T_OBJ || que.v.obj->tipo != O_TEXTO) return de_bool(0);
        Texto *a = (Texto *)donde.v.obj, *b = (Texto *)que.v.obj;
        if (!b->largo) return de_bool(1);
        for (uint32_t i = 0; i + b->largo <= a->largo; i++)
            if (memcmp(a->datos + i, b->datos, b->largo) == 0) return de_bool(1);
        return de_bool(0);
    }
    if (donde.etiqueta == T_OBJ && donde.v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)donde.v.obj;
        for (uint32_t i = 0; i < l->largo; i++) if (iguales(l->elementos[i], que)) return de_bool(1);
        return de_bool(0);
    }
    error_en(0, "contiene() espera texto o lista");
    return de_nulo();
}

static Valor nativa_agregar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_LISTA)
        error_en(0, "agregar() espera una lista");
    Lista *l = (Lista *)args[0].v.obj;
    lista_agregar(l, args[1]);
    return args[0];
}

static Valor nativa_invertir(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)args[0].v.obj;
        Lista *nueva = nueva_lista(l->largo);
        for (uint32_t i = 0; i < l->largo; i++) lista_agregar(nueva, l->elementos[l->largo - 1 - i]);
        return de_lista(nueva);
    }
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)args[0].v.obj;
        char *copia = memoria(t->largo + 1);
        for (uint32_t i = 0; i < t->largo; i++) copia[i] = t->datos[t->largo - 1 - i];
        copia[t->largo] = '\0';
        Texto *nuevo = nuevo_texto_largo(copia, t->largo);
        free(copia);
        return de_texto(nuevo);
    }
    error_en(0, "invertir() espera lista o texto");
    return de_nulo();
}

static Valor nativa_unir(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_LISTA)
        error_en(0, "unir() espera una lista");
    Lista *l = (Lista *)args[0].v.obj;
    const char *separador = "";
    if (argc > 1) {
        if (args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO)
            error_en(0, "unir() espera un separador de texto");
        separador = ((Texto *)args[1].v.obj)->datos;
    }
    size_t total = 0, largo_sep = strlen(separador);
    char trozos[4096];
    for (uint32_t i = 0; i < l->largo; i++) {
        texto_de(l->elementos[i], trozos, sizeof(trozos));
        total += strlen(trozos) + (i ? largo_sep : 0);
    }
    char *datos = memoria(total + 1);
    size_t usado = 0;
    for (uint32_t i = 0; i < l->largo; i++) {
        if (i) { memcpy(datos + usado, separador, largo_sep); usado += largo_sep; }
        texto_de(l->elementos[i], trozos, sizeof(trozos));
        size_t l_trozo = strlen(trozos);
        memcpy(datos + usado, trozos, l_trozo);
        usado += l_trozo;
    }
    datos[usado] = '\0';
    Texto *nuevo = nuevo_texto_largo(datos, (uint32_t)usado);
    free(datos);
    return de_texto(nuevo);
}

static Valor nativa_rango(VM *v, int argc, Valor *args) {
    (void)v;
    int64_t inicio, fin, paso = 1;
    if (argc == 1) { inicio = 1; fin = a_entero_estricto(args[0], "rango"); }
    else if (argc == 2) { inicio = a_entero_estricto(args[0], "rango"); fin = a_entero_estricto(args[1], "rango"); }
    else { inicio = a_entero_estricto(args[0], "rango"); fin = a_entero_estricto(args[1], "rango");
           paso = a_entero_estricto(args[2], "rango"); }
    if (paso <= 0) error_en(0, "rango() espera un paso mayor que 0");
    Lista *l = nueva_lista(16);
    if (inicio <= fin) for (int64_t i = inicio; i < fin; i += paso) lista_agregar(l, de_entero(i));
    else for (int64_t i = inicio; i > fin; i -= paso) lista_agregar(l, de_entero(i));
    return de_lista(l);
}

static Valor nativa_leer(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc > 0) {
        char texto[1024];
        texto_de(args[0], texto, sizeof(texto));
        fputs(texto, stdout);
        fflush(stdout);
    }
    char linea[4096];
    if (!fgets(linea, sizeof(linea), stdin)) return de_texto(nuevo_texto(""));
    size_t largo = strlen(linea);
    while (largo && (linea[largo - 1] == '\n' || linea[largo - 1] == '\r')) linea[--largo] = '\0';
    return de_texto(nuevo_texto_largo(linea, (uint32_t)largo));
}

/* --------------------------------------------------------- la máquina */

static void definir_global(const char *nombre, Valor valor) {
    for (uint32_t i = 0; i < vm->n_globales; i++) {
        Texto *t = vm->globales[i].nombre;
        if (strcmp(t->datos, nombre) == 0) {
            vm->globales[i].valor = valor;
            vm->globales[i].definido = 1;
            return;
        }
    }
    if (vm->n_globales < GLOBALES_MAX) {
        Global *g = &vm->globales[vm->n_globales++];
        g->nombre = nuevo_texto(nombre);
        g->valor = valor;
        g->definido = 1;
    }
}

static void instalar_nativa(const char *nombre, int8_t aridad, NativaPtr funcion) {
    Nativa *n = nuevo_objeto(sizeof(Nativa), O_NATIVA);
    n->nombre = nombre;
    n->aridad = aridad;
    n->funcion = funcion;
    definir_global(nombre, de_objeto((Obj *)n));
}

/*--------------------------------------------------------------- cargar */

static Funcion *funciones_deblob;
static uint32_t total_funciones;

static int cargar(const char *ruta, uint8_t **datos_salida, size_t *largo_salida) {
    FILE *archivo = fopen(ruta, "rb");
    if (!archivo) return 0;
    fseek(archivo, 0, SEEK_END);
    long largo = ftell(archivo);
    fseek(archivo, 0, SEEK_SET);
    uint8_t *datos = memoria((size_t)largo);
    if (fread(datos, 1, (size_t)largo, archivo) != (size_t)largo) {
        fclose(archivo);
        free(datos);
        return 0;
    }
    fclose(archivo);
    *datos_salida = datos;
    *largo_salida = (size_t)largo;
    return 1;
}

static void preparar_programa(uint8_t *blob, size_t largo) {
    if (largo < 24 || memcmp(blob, "JPB1", 4) != 0) {
        fprintf(stderr, "jpvm: el archivo no es bytecode de JP (.jpb)\n");
        exit(66);
    }
    size_t pos = 4;
    uint32_t version = leer_u32(blob + pos); pos += 4;
    uint32_t n_fun = leer_u32(blob + pos); pos += 4;
    uint32_t n_cadenas = leer_u32(blob + pos); pos += 4;
    uint32_t n_globales = leer_u32(blob + pos); pos += 4;
    pos += 4;
    if (version != 1) {
        fprintf(stderr, "jpvm: versión de bytecode no soportada: %u\n", version);
        exit(66);
    }

    vm->cadenas = memoria(sizeof(Texto *) * (n_cadenas ? n_cadenas : 1));
    vm->n_cadenas = n_cadenas;
    for (uint32_t i = 0; i < n_cadenas; i++) {
        uint32_t largo_texto = leer_u32(blob + pos); pos += 4;
        vm->cadenas[i] = nuevo_texto_largo((char *)blob + pos, largo_texto);
        pos += largo_texto;
    }

    vm->n_globales = n_globales < GLOBALES_MAX ? n_globales : GLOBALES_MAX;
    for (uint32_t i = 0; i < n_globales; i++) {
        uint32_t indice = leer_u32(blob + pos); pos += 4;
        if (i < GLOBALES_MAX) {
            vm->globales[i].nombre = vm->cadenas[indice];
            vm->globales[i].valor = de_nulo();
            vm->globales[i].definido = 0;
        }
    }

    total_funciones = n_fun;
    funciones_deblob = memoria(sizeof(Funcion) * n_fun);
    vm->funciones = funciones_deblob;
    for (uint32_t i = 0; i < n_fun; i++) {
        Funcion *f = &funciones_deblob[i];
        uint32_t nombre_idx = leer_u32(blob + pos); pos += 4;
        f->indice = i;
        f->nombre = vm->cadenas[nombre_idx];
        f->aridad = leer_u32(blob + pos); pos += 4;
        f->n_slots = leer_u32(blob + pos); pos += 4;
        f->flags_celda = memoria(f->n_slots ? f->n_slots : 1);
        memcpy(f->flags_celda, blob + pos, f->n_slots); pos += f->n_slots;
        f->n_upvalues = leer_u32(blob + pos); pos += 4;
        f->upvalues = memoria(sizeof(DescUpvalue) * (f->n_upvalues ? f->n_upvalues : 1));
        for (uint32_t u = 0; u < f->n_upvalues; u++) {
            f->upvalues[u].es_local = blob[pos]; pos += 1;
            f->upvalues[u].indice = leer_u32(blob + pos); pos += 4;
        }
        f->n_const_i = leer_u32(blob + pos); pos += 4;
        f->const_i = memoria(sizeof(int64_t) * (f->n_const_i ? f->n_const_i : 1));
        for (uint32_t c = 0; c < f->n_const_i; c++) { f->const_i[c] = (int64_t)leer_u64(blob + pos); pos += 8; }
        f->n_const_d = leer_u32(blob + pos); pos += 4;
        f->const_d = memoria(sizeof(double) * (f->n_const_d ? f->n_const_d : 1));
        for (uint32_t c = 0; c < f->n_const_d; c++) {
            uint64_t bits = leer_u64(blob + pos); pos += 8;
            memcpy(&f->const_d[c], &bits, 8);
        }
        f->n_const_s = leer_u32(blob + pos); pos += 4;
        f->const_s = memoria(sizeof(Texto *) * (f->n_const_s ? f->n_const_s : 1));
        for (uint32_t c = 0; c < f->n_const_s; c++) {
            uint32_t indice = leer_u32(blob + pos); pos += 4;
            f->const_s[c] = vm->cadenas[indice];
        }
        f->largo_codigo = leer_u32(blob + pos); pos += 4;
        f->codigo = memoria(sizeof(uint32_t) * (f->largo_codigo ? f->largo_codigo : 1));
        /* el bytecode son palabras de 32 bits little-endian (máquinas x86-64/ARM64) */
        memcpy(f->codigo, blob + pos, sizeof(uint32_t) * f->largo_codigo);
        pos += sizeof(uint32_t) * f->largo_codigo;
        f->n_lineas = leer_u32(blob + pos); pos += 4;
        f->lineas = memoria(sizeof(uint32_t) * 2 * (f->n_lineas ? f->n_lineas : 1));
        for (uint32_t c = 0; c < f->n_lineas; c++) {
            f->lineas[c * 2] = leer_u32(blob + pos); pos += 4;
            f->lineas[c * 2 + 1] = leer_u32(blob + pos); pos += 4;
        }
    }

    if (pos + 4 <= largo) {
        uint32_t largo_fuente = leer_u32(blob + pos); pos += 4;
        if (pos + largo_fuente <= largo) {
            vm->fuente = memoria(largo_fuente + 1);
            memcpy(vm->fuente, blob + pos, largo_fuente);
            vm->fuente[largo_fuente] = '\0';
            vm->largo_fuente = largo_fuente;
        }
    }
}

/* línea de la instrucción en la función actual */
static uint32_t linea_de(uint32_t pc) {
    Funcion *f = vm->marco->funcion;
    uint32_t mejor = 0;
    for (uint32_t i = 0; i < f->n_lineas; i++) {
        if (f->lineas[i * 2] <= pc) mejor = f->lineas[i * 2 + 1];
        else break;
    }
    return mejor;
}

static void imprimir_linea_fuente(uint32_t numero) {
    if (!vm->fuente || numero == 0) return;
    uint32_t inicio = 0, actual = 1;
    while (inicio < vm->largo_fuente && actual < numero) {
        if (vm->fuente[inicio] == '\n') actual++;
        inicio++;
    }
    if (actual != numero) return;
    uint32_t fin = inicio;
    while (fin < vm->largo_fuente && vm->fuente[fin] != '\n') fin++;
    /* cuenta la columna del primer carácter no blanco */
    uint32_t columna = 0;
    while (inicio + columna < fin && (vm->fuente[inicio + columna] == ' ' || vm->fuente[inicio + columna] == '\t'))
        columna++;
    printf("    --> línea %u, columna %u\n", numero, columna + 1);
    printf(" %4u | %.*s\n", numero, (int)(fin - inicio), vm->fuente + inicio);
    printf("      | %*s^\n", (int)columna, "");
}

/* -------------------------------------------------------- despachador */

static void ejecutar(Funcion *principal) {
    static const void *etiquetas[] = {
        &&L_NOP, &&L_CONST_I, &&L_CONST_D, &&L_CONST_S, &&L_NULO, &&L_VERDADERO,
        &&L_FALSO, &&L_GET_LOCAL, &&L_SET_LOCAL, &&L_GET_CELDA, &&L_SET_CELDA,
        &&L_GET_GLOBAL, &&L_SET_GLOBAL, &&L_DECL_GLOBAL, &&L_GET_UPVAL, &&L_SET_UPVAL,
        &&L_POP, &&L_DUP, &&L_SUMA, &&L_RESTA, &&L_MULT, &&L_DIV, &&L_MOD, &&L_POT,
        &&L_NEG, &&L_NO, &&L_IGUAL, &&L_DIF, &&L_MENOR, &&L_MAYOR, &&L_MENOR_IG,
        &&L_MAYOR_IG, &&L_SALTO, &&L_SALTO_FALSO, &&L_SALTO_FALSO_MANTENER,
        &&L_SALTO_VERDAD_MANTENER, &&L_IMPRIMIR, &&L_LLAMAR, &&L_RETORNAR,
        &&L_RETORNAR_NULO, &&L_LISTA, &&L_RANGO, &&L_INDICE, &&L_INDICE_ASIG,
        &&L_CIERRE, &&L_CELDA, &&L_ITER_INIT, &&L_ITER_NEXT, &&L_ITER_NEXT_CELDA,
        &&L_EXPR_SENT, &&L_FIN,
    };

    /* marco del programa principal */
    Valor *base_principal = vm->sp;
    for (uint32_t i = 0; i < principal->n_slots; i++) *vm->sp++ = de_nulo();
    Marco *marco_principal = vm->marco + 1;
    marco_principal->funcion = principal;
    marco_principal->base = base_principal;
    marco_principal->ip = principal->codigo;
    marco_principal->upvalues = NULL;
    marco_principal->n_upvalues = 0;

    /* marca de agua para el recolector: el marco del programa es el actual */
    vm->marco = marco_principal;

    #define PUSH(v) (*vm->sp++ = (v))
    #define POP() (*(--vm->sp))
    #define LEER_U32() (*ip++)
    #define LEER_I32() ((int32_t)*ip++)
    #define LEER_I64() (ip += 2, \
        (int64_t)(((uint64_t)ip[-2]) | ((uint64_t)ip[-1] << 32)))
    #define LEER_F64() (ip += 2, \
        (double)((union { uint64_t bits; double d; }){.bits = \
            (uint64_t)ip[-2] | ((uint64_t)ip[-1] << 32)}).d)

    Marco *marco = vm->marco;
    register uint32_t *ip = marco->ip;
    register Valor *base = marco->base;

    #define SIGUIENTE() goto *etiquetas[(uint32_t)*ip++]
    #define ACTUALIZAR_IP() (vm->marco->ip = ip)
    #define RECARGAR() (marco = vm->marco, ip = marco->ip, base = marco->base)

    SIGUIENTE();

L_NOP:
    SIGUIENTE();
L_CONST_I: {
    int64_t valor = LEER_I64();
    PUSH(de_entero(valor));
    SIGUIENTE();
}
L_CONST_D: {
    double valor = LEER_F64();
    PUSH(de_decimal(valor));
    SIGUIENTE();
}
L_CONST_S: {
    uint32_t indice = LEER_U32();
    PUSH(de_texto(marco->funcion->const_s[indice]));
    SIGUIENTE();
}
L_NULO: PUSH(de_nulo()); SIGUIENTE();
L_VERDADERO: PUSH(de_bool(1)); SIGUIENTE();
L_FALSO: PUSH(de_bool(0)); SIGUIENTE();

L_GET_LOCAL: {
    uint32_t slot = LEER_U32();
    PUSH(base[slot]);
    SIGUIENTE();
}
L_SET_LOCAL: {
    uint32_t slot = LEER_U32();
    base[slot] = vm->sp[-1];
    SIGUIENTE();
}
L_GET_CELDA: {
    uint32_t slot = LEER_U32();
    PUSH(((Celda *)base[slot].v.obj)->valor);
    SIGUIENTE();
}
L_SET_CELDA: {
    uint32_t slot = LEER_U32();
    ((Celda *)base[slot].v.obj)->valor = vm->sp[-1];
    SIGUIENTE();
}
L_GET_GLOBAL: {
    uint32_t indice = LEER_U32();
    Global *g = &vm->globales[indice];
    if (!g->definido) {
        ACTUALIZAR_IP();
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "variable no definida: '%s'", g->nombre->datos);
    }
    PUSH(g->valor);
    SIGUIENTE();
}
L_SET_GLOBAL: {
    uint32_t indice = LEER_U32();
    Global *g = &vm->globales[indice];
    if (!g->definido) {
        ACTUALIZAR_IP();
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "variable no definida: '%s' (usa 'var' para declararla)", g->nombre->datos);
    }
    g->valor = vm->sp[-1];
    SIGUIENTE();
}
L_DECL_GLOBAL: {
    uint32_t indice = LEER_U32();
    Global *g = &vm->globales[indice];
    g->valor = vm->sp[-1];
    g->definido = 1;
    SIGUIENTE();
}
L_GET_UPVAL: {
    uint32_t indice = LEER_U32();
    PUSH(((Celda *)marco->upvalues[indice])->valor);
    SIGUIENTE();
}
L_SET_UPVAL: {
    uint32_t indice = LEER_U32();
    ((Celda *)marco->upvalues[indice])->valor = vm->sp[-1];
    SIGUIENTE();
}
L_POP: vm->sp--; SIGUIENTE();
L_DUP: {
    Valor v = vm->sp[-1];
    PUSH(v);
    SIGUIENTE();
}

L_SUMA: {
    Valor b = POP(), a = POP();
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) {
        int64_t r;
        if (!__builtin_add_overflow(a.v.entero, b.v.entero, &r)) { PUSH(de_entero(r)); SIGUIENTE(); }
    }
    if (a.etiqueta == T_DBL && b.etiqueta == T_DBL) {
        PUSH(de_decimal(a.v.decimal + b.v.decimal));
        SIGUIENTE();
    }
    PUSH(op_suma(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_RESTA: {
    Valor b = POP(), a = POP();
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) {
        int64_t r;
        if (!__builtin_sub_overflow(a.v.entero, b.v.entero, &r)) { PUSH(de_entero(r)); SIGUIENTE(); }
    }
    PUSH(op_resta(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_MULT: {
    Valor b = POP(), a = POP();
    if (a.etiqueta == T_INT && b.etiqueta == T_INT) {
        int64_t r;
        if (!__builtin_mul_overflow(a.v.entero, b.v.entero, &r)) { PUSH(de_entero(r)); SIGUIENTE(); }
    }
    PUSH(op_mult(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_DIV: {
    Valor b = POP(), a = POP();
    if (a.etiqueta == T_INT && b.etiqueta == T_INT && b.v.entero != 0 && a.v.entero % b.v.entero == 0) {
        PUSH(de_entero(a.v.entero / b.v.entero));
        SIGUIENTE();
    }
    PUSH(op_div(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_MOD: {
    Valor b = POP(), a = POP();
    PUSH(op_mod(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_POT: {
    Valor b = POP(), a = POP();
    PUSH(op_potencia(a, b, (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1)));
    SIGUIENTE();
}
L_NEG: {
    Valor a = POP();
    if (a.etiqueta == T_INT) PUSH(de_entero(-a.v.entero));
    else if (a.etiqueta == T_DBL) PUSH(de_decimal(-a.v.decimal));
    else {
        char texto[256];
        texto_de(a, texto, sizeof(texto));
        ACTUALIZAR_IP();
        error_en(0, "el operador '-' espera números, recibió '%s'", texto);
    }
    SIGUIENTE();
}
L_NO: {
    Valor a = POP();
    PUSH(de_bool(!es_verdad(a)));
    SIGUIENTE();
}

L_IGUAL: {
    Valor b = POP(), a = POP();
    PUSH(de_bool(iguales(a, b)));
    SIGUIENTE();
}
L_DIF: {
    Valor b = POP(), a = POP();
    PUSH(de_bool(!iguales(a, b)));
    SIGUIENTE();
}
#define SALTO_COMPARACION(simbolo, expresion)                                          \
    {                                                                                  \
        Valor b = POP(), a = POP();                                                    \
        if (a.etiqueta == T_INT && b.etiqueta == T_INT) {                              \
            PUSH(de_bool(a.v.entero simbolo b.v.entero));                              \
            SIGUIENTE();                                                               \
        }                                                                              \
        exigir_numeros(a, b, expresion,                                                \
                       (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1));    \
        PUSH(de_bool(a_double(a) simbolo a_double(b)));                                \
        SIGUIENTE();                                                                   \
    }
L_MENOR: SALTO_COMPARACION(<, "<")
L_MAYOR: SALTO_COMPARACION(>, ">")
L_MENOR_IG: SALTO_COMPARACION(<=, "<=")
L_MAYOR_IG: SALTO_COMPARACION(>=, ">=")
#undef SALTO_COMPARACION

L_SALTO: {
    int32_t relativo = LEER_I32();
    ip = ip + relativo; /* el relativo cuenta palabras desde la instrucción siguiente */
    SIGUIENTE();
}
L_SALTO_FALSO: {
    int32_t relativo = LEER_I32();
    Valor condicion = POP();
    if (!es_verdad(condicion)) ip = ip + relativo;
    SIGUIENTE();
}
L_SALTO_FALSO_MANTENER: {
    int32_t relativo = LEER_I32();
    if (!es_verdad(vm->sp[-1])) ip = ip + relativo;
    SIGUIENTE();
}
L_SALTO_VERDAD_MANTENER: {
    int32_t relativo = LEER_I32();
    if (es_verdad(vm->sp[-1])) ip = ip + relativo;
    SIGUIENTE();
}
L_IMPRIMIR: {
    uint32_t argc = LEER_U32();
    Valor *args = vm->sp - argc;
    for (uint32_t i = 0; i < argc; i++) {
        char texto[4096];
        texto_de(args[i], texto, sizeof(texto));
        if (i) putchar(' ');
        fputs(texto, stdout);
    }
    putchar('\n');
    vm->sp -= argc;
    SIGUIENTE();
}

L_LLAMAR: {
    uint32_t argc = LEER_U32();
    Valor callee = vm->sp[-1 - (int32_t)argc];
    if (callee.etiqueta != T_OBJ)
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "esto no es una función");
    Obj *obj = callee.v.obj;
    if (obj->tipo == O_NATIVA) {
        Nativa *n = (Nativa *)obj;
        if (n->aridad >= 0 && n->aridad != (int8_t)argc) {
            ACTUALIZAR_IP();
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "%s() espera %d argumento(s), recibió %u", n->nombre, n->aridad, argc);
        }
        Valor resultado = n->funcion(vm, (int)argc, vm->sp - argc);
        vm->sp -= argc + 1;
        PUSH(resultado);
        SIGUIENTE();
    }
    if (obj->tipo != O_FUNCION) {
        char texto[256];
        texto_de(callee, texto, sizeof(texto));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "este valor no es una función: '%s'", texto);
    }
    Cierre *cierre = (Cierre *)obj;
    Funcion *f = cierre->funcion;
    if (f->aridad != argc) {
        ACTUALIZAR_IP();
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "la función '%s' espera %u argumento(s), recibió %u",
                 f->nombre->datos, f->aridad, argc);
    }
    if (vm->marco - vm->marcos >= MARCOS_MAX - 1)
        error_en(0, "desbordamiento de pila (¿recursión infinita?)");
    /* reutilizar los argumentos como primeros locales */
    Valor *nueva_base = vm->sp - argc - 1;
    for (uint32_t i = argc; i < f->n_slots; i++) *vm->sp++ = de_nulo();
    ACTUALIZAR_IP();
    vm->marco += 1;
    vm->marco->funcion = f;
    vm->marco->base = nueva_base + 1;
    vm->marco->ip = f->codigo;
    vm->marco->upvalues = cierre->upvalues;
    vm->marco->n_upvalues = cierre->n_upvalues;
    RECARGAR();
    SIGUIENTE();
}

L_RETORNAR: {
    Valor resultado = POP();
    vm->marco->ip = ip;
    vm->sp = base;          /* descarta locales y temporales del marco */
    vm->marco -= 1;
    if (vm->marco < vm->marcos) {
        vm->ultimo_valor = resultado;  /* 'retorna' en el nivel superior termina en paz */
        return;
    }
    vm->sp -= 1;            /* el callee estaba justo debajo de los locales */
    marco = vm->marco;
    ip = marco->ip;
    base = marco->base;
    PUSH(resultado);
    SIGUIENTE();
}
L_RETORNAR_NULO: {
    vm->marco->ip = ip;
    vm->sp = base;
    vm->marco -= 1;
    if (vm->marco < vm->marcos) {
        vm->ultimo_valor = de_nulo();
        return;
    }
    vm->sp -= 1;
    marco = vm->marco;
    ip = marco->ip;
    base = marco->base;
    PUSH(de_nulo());
    SIGUIENTE();
}

L_LISTA: {
    uint32_t n = LEER_U32();
    Lista *l = nueva_lista(n ? n : 1);
    Valor *inicio = vm->sp - n;
    for (uint32_t i = 0; i < n; i++) lista_agregar(l, inicio[i]);
    vm->sp -= n;
    PUSH(de_lista(l));
    quizas_recolectar();
    SIGUIENTE();
}
L_RANGO: {
    uint8_t tiene_paso = (uint8_t)*ip++;
    Valor paso = tiene_paso ? POP() : de_entero(1);
    Valor fin_v = POP(), inicio_v = POP();
    if (inicio_v.etiqueta == T_BOOL || !es_numero(inicio_v) || fin_v.etiqueta == T_BOOL || !es_numero(fin_v)) {
        char texto[256];
        texto_de(inicio_v.etiqueta == T_BOOL || !es_numero(inicio_v) ? inicio_v : fin_v, texto, sizeof(texto));
        ACTUALIZAR_IP();
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "el rango '..' espera números, recibió '%s'", texto);
    }
    int64_t i0 = a_entero(inicio_v), f0 = a_entero(fin_v);
    int64_t p;
    if (tiene_paso) {
        if (paso.etiqueta == T_BOOL || !es_numero(paso)) {
            char texto[256];
            texto_de(paso, texto, sizeof(texto));
            ACTUALIZAR_IP();
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "el paso de '..' espera un número, recibió '%s'", texto);
        }
        p = a_entero(paso);
        if (p <= 0) error_en(0, "el paso de '..' debe ser mayor que 0 (la dirección la deciden los extremos)");
        if (i0 > f0) p = -p;
    } else {
        p = i0 <= f0 ? 1 : -1;
    }
    Lista *l = nueva_lista(16);
    if (p > 0) for (int64_t i = i0; i <= f0; i += p) { lista_agregar(l, de_entero(i)); }
    else for (int64_t i = i0; i >= f0; i += p) { lista_agregar(l, de_entero(i)); }
    PUSH(de_lista(l));
    quizas_recolectar();
    SIGUIENTE();
}

L_INDICE: {
    Valor indice = POP(), objeto = POP();
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)objeto.v.obj;
        int64_t i = indice_normalizado(indice, l->largo, "una lista", 
                                      (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1));
        if (i < 0 || i >= (int64_t)l->largo) {
            char texto[64];
            snprintf(texto, sizeof(texto), "%lld (lista de %u elementos)", (long long)i, l->largo);
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1), "índice fuera de rango: %s", texto);
        }
        PUSH(l->elementos[i]);
        SIGUIENTE();
    }
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)objeto.v.obj;
        int64_t i = indice_normalizado(indice, t->largo, "una cadena",
                                      (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1));
        if (i < 0 || i >= (int64_t)t->largo)
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "índice fuera de rango: %lld (cadena de %u caracteres)", (long long)i, t->largo);
        PUSH(de_texto(nuevo_texto_largo(t->datos + i, 1)));
        SIGUIENTE();
    }
    {
        char texto[256];
        texto_de(objeto, texto, sizeof(texto));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "no se puede indexar '%s'", texto);
    }
    SIGUIENTE();
}
L_INDICE_ASIG: {
    Valor valor = POP();
    Valor indice = POP();
    Valor objeto = POP();
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)objeto.v.obj;
        int64_t i = indice_normalizado(indice, l->largo, "una lista",
                                      (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1));
        if (i < 0 || i >= (int64_t)l->largo)
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "índice fuera de rango: %lld (lista de %u elementos)", (long long)i, l->largo);
        l->elementos[i] = valor;
        PUSH(valor);
        SIGUIENTE();
    }
    error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
             "solo se puede asignar por índice en listas (los diccionarios aún no están en el motor nativo)");
    SIGUIENTE();
}

L_CIERRE: {
    uint32_t indice = LEER_U32();
    Funcion *f = &vm->funciones[indice];
    Cierre *c = nuevo_objeto(sizeof(Cierre), O_FUNCION);
    c->funcion = f;
    c->n_upvalues = f->n_upvalues;
    c->upvalues = memoria(sizeof(Obj *) * (f->n_upvalues ? f->n_upvalues : 1));
    for (uint32_t i = 0; i < f->n_upvalues; i++) {
        DescUpvalue *d = &f->upvalues[i];
        c->upvalues[i] = d->es_local ? base[d->indice].v.obj : marco->upvalues[d->indice];
    }
    PUSH(de_objeto((Obj *)c));
    SIGUIENTE();
}
L_CELDA: {
    uint32_t slot = LEER_U32();
    base[slot] = de_objeto((Obj *)nueva_celda(base[slot]));
    SIGUIENTE();
}

L_ITER_INIT: {
    uint32_t slot = LEER_U32();
    Valor iterable = POP();
    Lista *l = NULL;
    if (iterable.etiqueta == T_OBJ && iterable.v.obj->tipo == O_LISTA) {
        l = (Lista *)iterable.v.obj;
    } else if (iterable.etiqueta == T_OBJ && iterable.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)iterable.v.obj;
        l = nueva_lista(t->largo ? t->largo : 1);
        for (uint32_t i = 0; i < t->largo; i++) lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + i, 1)));
    } else if (iterable.etiqueta == T_INT) {
        int64_t n = iterable.v.entero;
        l = nueva_lista(n > 0 ? (uint32_t)n : 1);
        for (int64_t i = 1; i <= n; i++) lista_agregar(l, de_entero(i));
    } else if (iterable.etiqueta == T_DBL) {
        int64_t n = (int64_t)iterable.v.decimal;
        l = nueva_lista(n > 0 ? (uint32_t)n : 1);
        for (int64_t i = 1; i <= n; i++) lista_agregar(l, de_entero(i));
    } else {
        char texto[256];
        texto_de(iterable, texto, sizeof(texto));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "'para ... en' espera una lista, cadena, diccionario o número, no '%s'", texto);
    }
    Iter *it = nuevo_objeto(sizeof(Iter), O_ITER);
    it->lista = l;
    it->indice = 0;
    base[slot] = de_objeto((Obj *)it);
    SIGUIENTE();
}
L_ITER_NEXT: {
    uint32_t slot_iter = LEER_U32();
    uint32_t slot_var = LEER_U32();
    int32_t relativo = LEER_I32();
    Iter *it = (Iter *)base[slot_iter].v.obj;
    if (it->indice >= it->lista->largo) {
        ip = ip + relativo;
        SIGUIENTE();
    }
    base[slot_var] = it->lista->elementos[it->indice++];
    SIGUIENTE();
}
L_ITER_NEXT_CELDA: {
    uint32_t slot_iter = LEER_U32();
    uint32_t slot_var = LEER_U32();
    int32_t relativo = LEER_I32();
    Iter *it = (Iter *)base[slot_iter].v.obj;
    if (it->indice >= it->lista->largo) {
        ip = ip + relativo;
        SIGUIENTE();
    }
    base[slot_var] = de_objeto((Obj *)nueva_celda(it->lista->elementos[it->indice++]));
    SIGUIENTE();
}

L_EXPR_SENT: {
    vm->ultimo_valor = POP();
    SIGUIENTE();
}
L_FIN:
    return;
}

/* --------------------------------------------------------- diagnóstico */

static void mostrar_info(Funcion *f) {
    printf("JPB1 v1: %u función(es), %u cadena(s), %u global(es), %u bytes de código fuente\n",
           total_funciones, vm->n_cadenas, vm->n_globales, vm->largo_fuente);
    for (uint32_t i = 0; i < total_funciones; i++) {
        printf("  #%u '%s' aridad=%u slots=%u upvalues=%u código=%u B\n", i,
               f[i].nombre->datos, f[i].aridad, f[i].n_slots, f[i].n_upvalues, f[i].largo_codigo);
    }
}

/* Un programa compilado a binario puede traer su bytecode pegado dentro:
 * el generador escribe otro .c con estos dos símbolos y se enlaza con este
 * archivo. Si no están, el símbolo queda en NULL y se usa el archivo. */
extern const unsigned char jp_chunk_embebido[] __attribute__((weak));
extern const unsigned long jp_chunk_largo __attribute__((weak));

int main(int argc, char **argv) {
    const char *ruta = NULL;
    int modo_info = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--info") == 0) modo_info = 1;
        else if (strcmp(argv[i], "--version") == 0) {
            printf("jpvm 0.1 (motor nativo de JP)\n");
            return 0;
        } else ruta = argv[i];
    }
    if (!ruta && !(jp_chunk_embebido != NULL)) {
        fprintf(stderr, "uso: jpvm [--info] programa.jpb\n");
        return 64;
    }

    srand((unsigned)time(NULL) ^ 0x5f3759dfu);
    vm->sp = vm->pila;
    vm->marco = vm->marcos - 1;
    vm->ultimo_valor = de_nulo();
    vm->bytes_reservados = 0;
    vm->umbral_gc = 8 * 1024 * 1024;

    uint8_t *blob = NULL;
    size_t largo = 0;
    if (!ruta) {
        /* binario independiente: el bytecode viene embebido en el ejecutable */
        blob = (uint8_t *)jp_chunk_embebido;
        largo = (size_t)jp_chunk_largo;
    } else if (!cargar(ruta, &blob, &largo)) {
        fprintf(stderr, "jpvm: no se pudo leer '%s'\n", ruta);
        return 66;
    }
    preparar_programa(blob, largo);

    /* librería estándar (subconjunto del motor nativo) */
    instalar_nativa("muestra", -1, nativa_imprime);
    instalar_nativa("imprime", -1, nativa_imprime);
    instalar_nativa("longitud", 1, nativa_longitud);
    instalar_nativa("entero", 1, nativa_entero);
    instalar_nativa("numero", 1, nativa_numero);
    instalar_nativa("texto", 1, nativa_texto);
    instalar_nativa("tipo", 1, nativa_tipo);
    instalar_nativa("raiz", 1, nativa_raiz);
    instalar_nativa("absoluto", 1, nativa_absoluto);
    instalar_nativa("piso", 1, nativa_piso);
    instalar_nativa("techo", 1, nativa_techo);
    instalar_nativa("redondear", -1, nativa_redondear);
    instalar_nativa("log", -1, nativa_log);
    instalar_nativa("exp", 1, nativa_exp);
    instalar_nativa("seno", 1, nativa_seno);
    instalar_nativa("coseno", 1, nativa_coseno);
    instalar_nativa("potencia", 2, nativa_potencia);
    instalar_nativa("minimo", -1, nativa_minimo);
    instalar_nativa("maximo", -1, nativa_maximo);
    instalar_nativa("sumar", -1, nativa_sumar);
    instalar_nativa("pi", 0, nativa_pi);
    instalar_nativa("reloj", 0, nativa_reloj);
    instalar_nativa("aleatorio", 0, nativa_aleatorio);
    instalar_nativa("azar", 1, nativa_azar);
    instalar_nativa("mayusculas", 1, nativa_mayusculas);
    instalar_nativa("minusculas", 1, nativa_minusculas);
    instalar_nativa("recortar", 1, nativa_recortar);
    instalar_nativa("contiene", 2, nativa_contiene);
    instalar_nativa("agregar", 2, nativa_agregar);
    instalar_nativa("invertir", 1, nativa_invertir);
    instalar_nativa("unir", -1, nativa_unir);
    instalar_nativa("rango", -1, nativa_rango);
    instalar_nativa("leer", -1, nativa_leer);

    if (modo_info) {
        mostrar_info(vm->funciones);
        return 0;
    }

    if (setjmp(vm->salto_error)) {
        fflush(stdout);
        fprintf(stderr, "Error de ejecución: %s\n", vm->error);
        if (vm->linea_error) imprimir_linea_fuente(vm->linea_error);
        return 65;
    }

    ejecutar(&vm->funciones[0]);
    fflush(stdout);
    return 0;
}
