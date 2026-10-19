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

#define _DEFAULT_SOURCE 1
#include <ctype.h>
#include <errno.h>
#include <dirent.h>
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

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

typedef enum {
    O_TEXTO = 1, O_LISTA, O_FUNCION, O_NATIVA, O_CELDA, O_ITER, O_DICTO, O_LIGADA,
    O_CLASE, O_INSTANCIA, O_METODO
} TipoObj;

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

/* Diccionario: claves de texto, en orden de inserción (como Python) y con
 * una tabla hash de índices para que buscar sea O(1). */
typedef struct {
    Texto *clave;
    Valor valor;
} EntradaDict;

typedef struct {
    Obj cabecera;
    uint32_t largo;             /* entradas usadas, en orden de inserción */
    uint32_t capacidad;
    EntradaDict *entradas;
    uint32_t capacidad_indice;  /* potencia de dos */
    uint32_t *indice;           /* ranura -> (índice de entrada + 1); 0 = libre */
} Dicto;

typedef struct {
    Obj cabecera;
    Lista *lista;
    uint32_t indice;
    Dicto *dicto;      /* si el iterable era un dict, para (clave, valor) */
} Iter;

/* Nativa ligada a un receptor: "hola".mayusculas  (sin llamar todavía). */
typedef struct {
    Obj cabecera;
    Texto *nombre;
    Valor receptor;
} Ligada;

/* Una clase de JP (v1.25): molde con métodos y madre, como ClaseJP. */
typedef struct {
    Obj cabecera;
    Texto *nombre;
    Valor padre;              /* la clase madre (O_CLASE) o nulo */
    uint32_t n_metodos;
    Texto **nombres_met;
    Cierre **metodos;
} Clase;

/* Un objeto de una clase: sus campos viven en un diccionario. */
typedef struct {
    Obj cabecera;
    Clase *clase;
    Dicto *campos;
} Instancia;

/* Un método ya ligado a su objeto: punto.mover (sin llamar todavía). */
typedef struct {
    Obj cabecera;
    Cierre *cierre;
    Valor receptor;
} Metodo;

typedef struct {
    Funcion *funcion;
    Valor *base;      /* primer local */
    uint32_t *ip;
    Obj **upvalues;
    uint32_t n_upvalues;
    uint32_t n_manejadores;  /* 'intenta' activos al entrar al marco */
    uint32_t n_args;         /* argumentos pasados (sin rellenar defectos) */
} Marco;

/* Un 'intenta' activo: a dónde volver si algo falla dentro. */
typedef struct {
    Marco *marco;
    Valor *sp;
    uint32_t pc;      /* palabra del bytecode donde empieza el 'atrapa' */
} Maneja;

/* Un bucle en curso (el del programa o el de una nativa que llama a JP).
 * 'piso' es el marco por debajo del cual este nivel ya no puede atrapar: si el
 * 'intenta' que falla vive más arriba, el error sigue hacia fuera (y la pila
 * de C de la nativa se descarta, como en Python al desenrollar). */
typedef struct {
    jmp_buf salto;
    Marco *piso;
} Nivel;

/* ---------------------------------------------------------------- la VM */

#define PILA_MAX 65536
#define MARCOS_MAX 4096
#define GLOBALES_MAX 4096

typedef struct {
    Texto *nombre;
    Valor valor;
    uint8_t definido;
} Global;

static int textos_iguales(Texto *a, Texto *b);

/* Registro de nativas por nombre: es lo que hace posible los métodos de
 * valor ("hola".mayusculas() y tambien lista.agregar como función suelta). */
#define NATIVAS_MAX 128
static Nativa *nativas_por_nombre[NATIVAS_MAX];
static const char *nombres_nativas[NATIVAS_MAX];
static uint32_t n_nativas_registradas;

static Nativa *nativa_por_nombre(Texto *nombre) {
    for (uint32_t i = 0; i < n_nativas_registradas; i++) {
        Nativa *n = nativas_por_nombre[i];
        if (n && n->nombre && strlen(n->nombre) == nombre->largo &&
            memcmp(n->nombre, nombre->datos, nombre->largo) == 0) {
            return n;
        }
    }
    return NULL;
}

struct VM {
    Valor pila[PILA_MAX];
    Valor *sp;
    Marco marcos[MARCOS_MAX];
    Marco *marco;
    Global globales[GLOBALES_MAX];
    uint32_t n_globales;
    jmp_buf salto_error;
    Nivel niveles[256];     /* un nivel por cada bucle en curso (programa y nativas) */
    uint32_t n_niveles;
    char error[512];
    uint32_t linea_error;
    Marco *piso_marco;     /* el bucle vuelve cuando un 'retorna' baja hasta aquí */
    Maneja manejadores[64];
    uint32_t n_manejadores;
    uint32_t pc_inicio;    /* pc desde el que (re)arranca el bucle tras atrapar */
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
    if (vm->n_manejadores > 0 && vm->n_niveles > 0)
        longjmp(vm->niveles[vm->n_niveles - 1].salto, 1);
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

static Dicto *nuevo_dicto(void) {
    Dicto *d = nuevo_objeto(sizeof(Dicto), O_DICTO);
    d->capacidad = 4;
    d->entradas = memoria(sizeof(EntradaDict) * d->capacidad);
    d->capacidad_indice = 8;
    d->indice = memoria(sizeof(uint32_t) * d->capacidad_indice);
    memset(d->indice, 0, sizeof(uint32_t) * d->capacidad_indice);
    return d;
}

static uint32_t dicto_ranura(Dicto *d, Texto *clave) {
    uint32_t mascara = d->capacidad_indice - 1;
    uint32_t i = clave->hash & mascara;
    while (d->indice[i] != 0) {
        if (textos_iguales(d->entradas[d->indice[i] - 1].clave, clave)) return i;
        i = (i + 1) & mascara;
    }
    return i;
}

static Valor *dicto_buscar(Dicto *d, Texto *clave) {
    uint32_t ranura = dicto_ranura(d, clave);
    if (d->indice[ranura] == 0) return NULL;
    return &d->entradas[d->indice[ranura] - 1].valor;
}

static void dicto_reindexar(Dicto *d, uint32_t nueva_capacidad) {
    free(d->indice);
    d->capacidad_indice = nueva_capacidad;
    d->indice = memoria(sizeof(uint32_t) * nueva_capacidad);
    memset(d->indice, 0, sizeof(uint32_t) * nueva_capacidad);
    for (uint32_t k = 0; k < d->largo; k++)
        d->indice[dicto_ranura(d, d->entradas[k].clave)] = k + 1;
}

static void dicto_poner(Dicto *d, Texto *clave, Valor valor) {
    uint32_t ranura = dicto_ranura(d, clave);
    if (d->indice[ranura] != 0) {
        d->entradas[d->indice[ranura] - 1].valor = valor;
        return;
    }
    if (d->largo == d->capacidad) {
        d->capacidad *= 2;
        d->entradas = realloc(d->entradas, sizeof(EntradaDict) * d->capacidad);
    }
    d->entradas[d->largo].clave = clave;
    d->entradas[d->largo].valor = valor;
    d->largo += 1;
    if (d->largo * 4 > d->capacidad_indice * 3) dicto_reindexar(d, d->capacidad_indice * 2);
    else d->indice[ranura] = d->largo;
}

static Valor de_objeto(Obj *obj);

/* ---------------- Métodos de valor ("hola".mayusculas(), [1].agregar(x)) ------
 * Son las mismas nativas, con el receptor como primer argumento; la tabla de
 * cada tipo decide qué nombres existen (como en el motor de Python). */

static const char *const METODOS_TEXTO[] = {
    "mayusculas", "minusculas", "recortar", "separar", "reemplazar", "subtexto",
    "letra", "contiene", "longitud", "empezar_con", "terminar_con", "buscar",
    "repetir", "invertir", "indice_de",
};
static const char *const METODOS_LISTA[] = {
    "agregar", "longitud", "contiene", "mapear", "filtrar", "reducir", "para_cada",
    "ordenar", "invertir", "sumar", "indice_de", "insertar", "quitar", "eliminar",
    "unir",
};
static const char *const METODOS_DICTO[] = {"claves", "tiene", "valores", "elementos"};
#define N_METODOS(tabla) (sizeof(tabla) / sizeof((tabla)[0]))

static int nombre_en_tabla(const char *const *tabla, size_t n, Texto *nombre) {
    for (size_t i = 0; i < n; i++) {
        size_t largo = strlen(tabla[i]);
        if (largo == nombre->largo && memcmp(tabla[i], nombre->datos, largo) == 0) return 1;
    }
    return 0;
}

/* Devuelve la nativa que implementa `nombre` para el receptor, o NULL. */
static Nativa *metodo_de_valor(Valor receptor, Texto *nombre) {
    if (receptor.etiqueta != T_OBJ) return NULL;
    const char *const *tabla = NULL;
    size_t n = 0;
    switch (receptor.v.obj->tipo) {
        case O_TEXTO: tabla = METODOS_TEXTO; n = N_METODOS(METODOS_TEXTO); break;
        case O_LISTA: tabla = METODOS_LISTA; n = N_METODOS(METODOS_LISTA); break;
        case O_DICTO: tabla = METODOS_DICTO; n = N_METODOS(METODOS_DICTO); break;
        default: return NULL;
    }
    if (!nombre_en_tabla(tabla, n, nombre)) return NULL;
    return nativa_por_nombre(nombre);
}

static Valor de_ligada(Nativa *nativa, Valor receptor) {
    Ligada *lig = nuevo_objeto(sizeof(Ligada), O_LIGADA);
    lig->nombre = nuevo_texto_largo(nativa->nombre, (uint32_t)strlen(nativa->nombre));
    lig->receptor = receptor;
    return de_objeto((Obj *)lig);
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

/* Centinela de "este argumento no vino": la llamada rellena con él los
 * parámetros que faltan y el prólogo DEFECTOS de la función lo sustituye
 * por el valor por defecto. Nunca se ve desde JP. */
static Obj centinela_defecto = { 250, 1, NULL };
static Valor de_centinela(void) { return de_objeto(&centinela_defecto); }
static int es_sin_valor(Valor v) {
    return v.etiqueta == T_OBJ && v.v.obj == &centinela_defecto;
}
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
        case O_DICTO: {
            Dicto *d = (Dicto *)obj;
            size_t usado = 0;
            usado += (size_t)snprintf(salida + usado, tamano - usado, "{");
            for (uint32_t i = 0; i < d->largo && usado < tamano; i++) {
                char clave[512], valor[1024];
                snprintf(clave, sizeof(clave), "\"%.*s\"", (int)d->entradas[i].clave->largo,
                         d->entradas[i].clave->datos);
                texto_inspeccion(d->entradas[i].valor, valor, sizeof(valor));
                usado += (size_t)snprintf(salida + usado, tamano - usado, "%s%s: %s",
                                          i ? ", " : "", clave, valor);
            }
            snprintf(salida + usado, tamano - usado, "}");
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
        case O_CLASE:
            snprintf(salida, tamano, "<clase %.*s>",
                     (int)((Clase *)obj)->nombre->largo, ((Clase *)obj)->nombre->datos);
            return;
        case O_METODO:
            snprintf(salida, tamano, "<método %.*s>",
                     (int)((Metodo *)obj)->cierre->funcion->nombre->largo,
                     ((Metodo *)obj)->cierre->funcion->nombre->datos);
            return;
        case O_INSTANCIA: {
            Instancia *ins = (Instancia *)obj;
            Dicto *d = ins->campos;
            size_t usado = 0;
            usado += (size_t)snprintf(salida + usado, tamano - usado, "%.*s{",
                                      (int)ins->clase->nombre->largo, ins->clase->nombre->datos);
            for (uint32_t i = 0; i < d->largo && usado < tamano; i++) {
                char valor[1024];
                texto_inspeccion(d->entradas[i].valor, valor, sizeof(valor));
                usado += (size_t)snprintf(salida + usado, tamano - usado, "%s%.*s: %s",
                                          i ? ", " : "", (int)d->entradas[i].clave->largo,
                                          d->entradas[i].clave->datos, valor);
            }
            snprintf(salida + usado, tamano - usado, "}");
            return;
        }
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
            if (((Iter *)obj)->dicto) marcar_objeto((Obj *)((Iter *)obj)->dicto);
            break;
        case O_DICTO: {
            Dicto *d = (Dicto *)obj;
            for (uint32_t i = 0; i < d->largo; i++) {
                marcar_objeto((Obj *)d->entradas[i].clave);
                marcar(d->entradas[i].valor);
            }
            break;
        }
        case O_LIGADA:
            marcar_objeto((Obj *)((Ligada *)obj)->nombre);
            marcar(((Ligada *)obj)->receptor);
            break;
        case O_CLASE: {
            Clase *c = (Clase *)obj;
            marcar_objeto((Obj *)c->nombre);
            marcar(c->padre);
            for (uint32_t i = 0; i < c->n_metodos; i++) {
                marcar_objeto((Obj *)c->nombres_met[i]);
                marcar_objeto((Obj *)c->metodos[i]);
            }
            break;
        }
        case O_INSTANCIA: {
            Instancia *ins = (Instancia *)obj;
            marcar_objeto((Obj *)ins->clase);
            marcar_objeto((Obj *)ins->campos);
            break;
        }
        case O_METODO: {
            Metodo *m = (Metodo *)obj;
            marcar_objeto((Obj *)m->cierre);
            marcar(m->receptor);
            break;
        }
        default:
            break;
    }
}

static void marcar(Valor v) {
    if (v.etiqueta == T_OBJ) marcar_objeto(v.v.obj);
}

static void recolectar(void) {
    for (Valor *p = vm->pila; p < vm->sp; p++) marcar(*p);
    /* las cadenas del programa (nombres de funciones/globales/constantes)
     * viven todo lo que vive la VM: sin marcarlas, el barrido las libera */
    for (uint32_t i = 0; i < vm->n_cadenas; i++) marcar_objeto((Obj *)vm->cadenas[i]);
    for (Marco *m = vm->marcos; m <= vm->marco; m++) {
        if (!m->funcion) continue;
        for (uint32_t i = 0; i < m->funcion->n_slots; i++) marcar(*(m->base + i));
        for (uint32_t i = 0; i < m->n_upvalues; i++) marcar_objeto(m->upvalues[i]);
    }
    for (uint32_t i = 0; i < vm->n_globales; i++) marcar(vm->globales[i].valor);
    /* el registro de nativas es una raíz de por vida: al cargar el programa
     * el contador de globales se reinicia y las Nativa quedarían solo en
     * este array; sin marcarlas, el barrido las liberaba y cualquier
     * método de valor posterior leía memoria muerta (red-profunda) */
    for (uint32_t i = 0; i < n_nativas_registradas; i++)
        if (nativas_por_nombre[i]) marcar_objeto((Obj *)nativas_por_nombre[i]);
    for (uint32_t i = 0; i < vm->n_globales; i++)
        if (vm->globales[i].nombre) marcar_objeto((Obj *)vm->globales[i].nombre);
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
            if (obj->tipo == O_DICTO) {
                free(((Dicto *)obj)->entradas);
                free(((Dicto *)obj)->indice);
            }
            if (obj->tipo == O_FUNCION) free(((Cierre *)obj)->upvalues);
            if (obj->tipo == O_CLASE) {
                free(((Clase *)obj)->nombres_met);
                free(((Clase *)obj)->metodos);
            }
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

/* El método 'nombre' de una clase, subiendo por la cadena de madres
 * (como buscar_metodo() en jp/interprete.py). NULL si no está. */
static Cierre *buscar_metodo_clase(Clase *clase, Texto *nombre) {
    for (Clase *c = clase; c;) {
        for (uint32_t i = 0; i < c->n_metodos; i++)
            if (textos_iguales(c->nombres_met[i], nombre)) return c->metodos[i];
        c = c->padre.etiqueta == T_OBJ ? (Clase *)c->padre.v.obj : NULL;
    }
    return NULL;
}

/* Tipos graduales (v1.27): mismas reglas y nombres que cumple_tipo() y
 * nombre_tipo() de jp/interprete.py. Un tipo desconocido no estorba. */
static int cumple_tipo(Valor v, Texto *tipo) {
    const char *t = tipo->datos;
    if (!strcmp(t, "cualquiera")) return 1;
    if (!strcmp(t, "nulo")) return v.etiqueta == T_NULO;
    if (!strcmp(t, "numero") || !strcmp(t, "número"))
        return v.etiqueta == T_INT || v.etiqueta == T_DBL;
    if (!strcmp(t, "entero")) return v.etiqueta == T_INT;
    if (!strcmp(t, "texto")) return v.etiqueta == T_OBJ && v.v.obj->tipo == O_TEXTO;
    if (!strcmp(t, "booleano")) return v.etiqueta == T_BOOL;
    if (!strcmp(t, "lista")) return v.etiqueta == T_OBJ && v.v.obj->tipo == O_LISTA;
    if (!strcmp(t, "diccionario")) return v.etiqueta == T_OBJ && v.v.obj->tipo == O_DICTO;
    if (!strcmp(t, "funcion") || !strcmp(t, "función")) {
        if (v.etiqueta != T_OBJ) return 0;
        uint8_t k = v.v.obj->tipo;
        return k == O_FUNCION || k == O_NATIVA || k == O_METODO || k == O_LIGADA || k == O_CLASE;
    }
    return 1;
}

static const char *nombre_tipo_jp(Valor v) {
    switch (v.etiqueta) {
        case T_NULO: return "nulo";
        case T_BOOL: return "booleano";
        case T_INT:
        case T_DBL: return "número";
        default: break;
    }
    switch (v.v.obj->tipo) {
        case O_TEXTO: return "texto";
        case O_LISTA: return "lista";
        case O_DICTO: return "diccionario";
        case O_INSTANCIA: return "objeto";
        case O_CLASE: return "clase";
        case O_FUNCION:
        case O_NATIVA:
        case O_METODO:
        case O_LIGADA: return "función";
        default: return "valor";
    }
}

static Cierre *buscar_metodo_cstr(Clase *clase, const char *nombre) {
    size_t largo = strlen(nombre);
    for (Clase *c = clase; c;) {
        for (uint32_t i = 0; i < c->n_metodos; i++)
            if (c->nombres_met[i]->largo == largo &&
                memcmp(c->nombres_met[i]->datos, nombre, largo) == 0)
                return c->metodos[i];
        c = c->padre.etiqueta == T_OBJ ? (Clase *)c->padre.v.obj : NULL;
    }
    return NULL;
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
        if (oa->tipo == O_DICTO) {
            Dicto *da = (Dicto *)oa, *db = (Dicto *)ob;
            if (da->largo != db->largo) return 0;
            for (uint32_t i = 0; i < da->largo; i++) {
                Valor *v = dicto_buscar(db, da->entradas[i].clave);
                if (!v || !iguales(*v, da->entradas[i].valor)) return 0;
            }
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
    if (x.etiqueta == T_OBJ && x.v.obj->tipo == O_DICTO) return de_entero(((Dicto *)x.v.obj)->largo);
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
        case O_DICTO: return de_texto(nuevo_texto("diccionario"));
        case O_FUNCION:
        case O_NATIVA:
        case O_METODO:
        case O_LIGADA: return de_texto(nuevo_texto("función"));
        case O_CLASE: return de_texto(nuevo_texto("clase"));
        case O_INSTANCIA: return de_texto(nuevo_texto("objeto"));
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

static Lista *exigir_lista_numeros(Valor x, const char *nombre) {
    if (x.etiqueta != T_OBJ || x.v.obj->tipo != O_LISTA) {
        char texto[256];
        texto_de(x, texto, sizeof(texto));
        error_en(0, "%s espera una lista de números, no '%s'", nombre, texto);
    }
    return (Lista *)x.v.obj;
}

static Valor nativa_sigmoide(VM *v, int argc, Valor *args) {
    (void)v;
    double x = exigir_numero(args[0], "sigmoide");
    double r = x >= 0 ? 1.0 / (1.0 + exp(-x)) : exp(x) / (1.0 + exp(x));
    return de_decimal(r);
}

static Valor nativa_producto_punto(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *a = exigir_lista_numeros(args[0], "producto_punto()");
    Lista *b = exigir_lista_numeros(args[1], "producto_punto()");
    if (a->largo != b->largo)
        error_en(0, "producto_punto() espera listas del mismo largo (%u y %u)", a->largo, b->largo);
    double total_d = 0.0;
    int64_t total_i = 0;
    int hay_decimal = 0;
    for (uint32_t i = 0; i < a->largo; i++) {
        double x = exigir_numero(a->elementos[i], "producto_punto"), y = exigir_numero(b->elementos[i], "producto_punto");
        if (a->elementos[i].etiqueta == T_DBL || b->elementos[i].etiqueta == T_DBL) hay_decimal = 1;
        total_d += x * y;
        if (!hay_decimal) total_i += (int64_t)x * (int64_t)y;
    }
    return hay_decimal ? de_decimal(total_d) : de_entero(total_i);
}

static double suma_lista(Lista *l, const char *nombre) {
    double total = 0.0;
    for (uint32_t i = 0; i < l->largo; i++) total += exigir_numero(l->elementos[i], nombre);
    return total;
}

static Valor nativa_promedio(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *l = exigir_lista_numeros(args[0], "promedio()");
    if (!l->largo) error_en(0, "promedio() espera una lista de números con al menos un valor");
    return de_decimal(suma_lista(l, "promedio()") / (double)l->largo);
}

static int comparar_doubles(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static Valor nativa_mediana(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *l = exigir_lista_numeros(args[0], "mediana()");
    if (!l->largo) error_en(0, "mediana() espera una lista de números con al menos un valor");
    double *valores = memoria(sizeof(double) * l->largo);
    for (uint32_t i = 0; i < l->largo; i++) valores[i] = exigir_numero(l->elementos[i], "mediana()");
    qsort(valores, l->largo, sizeof(double), comparar_doubles);
    uint32_t m = l->largo / 2;
    double r = l->largo % 2 ? valores[m] : (valores[m - 1] + valores[m]) / 2.0;
    free(valores);
    return de_decimal(r);
}

static Valor nativa_norma(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *l = exigir_lista_numeros(args[0], "norma()");
    double total = 0.0;
    for (uint32_t i = 0; i < l->largo; i++) { double x = exigir_numero(l->elementos[i], "norma()"); total += x * x; }
    return de_decimal(sqrt(total));
}

static Valor nativa_distancia(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *a = exigir_lista_numeros(args[0], "distancia()");
    Lista *b = exigir_lista_numeros(args[1], "distancia()");
    if (a->largo != b->largo)
        error_en(0, "distancia(): los vectores deben tener el mismo largo (%u y %u)", a->largo, b->largo);
    double total = 0.0;
    for (uint32_t i = 0; i < a->largo; i++) {
        double d = exigir_numero(a->elementos[i], "distancia()") - exigir_numero(b->elementos[i], "distancia()");
        total += d * d;
    }
    return de_decimal(sqrt(total));
}

static Valor nativa_softmax(VM *v, int argc, Valor *args) {
    (void)v;
    Lista *l = exigir_lista_numeros(args[0], "softmax()");
    if (!l->largo) error_en(0, "softmax() espera una lista de números no vacía");
    double mayor = exigir_numero(l->elementos[0], "softmax()");
    for (uint32_t i = 1; i < l->largo; i++) { double x = exigir_numero(l->elementos[i], "softmax()"); if (x > mayor) mayor = x; }
    Lista *salida = nueva_lista(l->largo);
    double total = 0.0;
    for (uint32_t i = 0; i < l->largo; i++) {
        double e = exp(exigir_numero(l->elementos[i], "softmax()") - mayor);
        lista_agregar(salida, de_decimal(e));
        total += e;
    }
    for (uint32_t i = 0; i < salida->largo; i++) salida->elementos[i] = de_decimal(a_double(salida->elementos[i]) / total);
    return de_lista(salida);
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
    if (donde.etiqueta == T_OBJ && donde.v.obj->tipo == O_DICTO) {
        if (que.etiqueta != T_OBJ || que.v.obj->tipo != O_TEXTO) return de_bool(0);
        return de_bool(dicto_buscar((Dicto *)donde.v.obj, (Texto *)que.v.obj) != NULL);
    }
    error_en(0, "contiene() espera texto, lista o diccionario");
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

static const char *nombre_tipo_objeto(uint8_t tipo) {
    switch (tipo) {
        case O_TEXTO: return "texto";
        case O_LISTA: return "lista";
        case O_DICTO: return "diccionario";
        default: return "valor";
    }
}

static Dicto *exigir_dicto(Valor x, const char *nombre) {
    if (x.etiqueta != T_OBJ || x.v.obj->tipo != O_DICTO) {
        char texto[256];
        texto_de(x, texto, sizeof(texto));
        error_en(0, "%s() espera un diccionario, no '%s'", nombre, texto);
    }
    return (Dicto *)x.v.obj;
}

static Valor nativa_claves(VM *v, int argc, Valor *args) {
    (void)v;
    Dicto *d = exigir_dicto(args[0], "claves");
    Lista *l = nueva_lista(d->largo ? d->largo : 1);
    for (uint32_t i = 0; i < d->largo; i++) lista_agregar(l, de_texto(d->entradas[i].clave));
    return de_lista(l);
}

static Valor nativa_valores(VM *v, int argc, Valor *args) {
    (void)v;
    Dicto *d = exigir_dicto(args[0], "valores");
    Lista *l = nueva_lista(d->largo ? d->largo : 1);
    for (uint32_t i = 0; i < d->largo; i++) lista_agregar(l, d->entradas[i].valor);
    return de_lista(l);
}

static Valor nativa_elementos(VM *v, int argc, Valor *args) {
    (void)v;
    Dicto *d = exigir_dicto(args[0], "elementos");
    Lista *l = nueva_lista(d->largo ? d->largo : 1);
    for (uint32_t i = 0; i < d->largo; i++) {
        Lista *par = nueva_lista(2);
        lista_agregar(par, de_texto(d->entradas[i].clave));
        lista_agregar(par, d->entradas[i].valor);
        lista_agregar(l, de_lista(par));
    }
    return de_lista(l);
}

static Valor nativa_tiene(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_DICTO) {
        if (args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO) return de_bool(0);
        return de_bool(dicto_buscar((Dicto *)args[0].v.obj, (Texto *)args[1].v.obj) != NULL);
    }
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)args[0].v.obj;
        for (uint32_t i = 0; i < l->largo; i++) if (iguales(l->elementos[i], args[1])) return de_bool(1);
        return de_bool(0);
    }
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_TEXTO) {
        if (args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO) return de_bool(0);
        Texto *a = (Texto *)args[0].v.obj, *b = (Texto *)args[1].v.obj;
        for (uint32_t i = 0; i + b->largo <= a->largo; i++)
            if (memcmp(a->datos + i, b->datos, b->largo) == 0) return de_bool(1);
        return de_bool(0);
    }
    char texto[256];
    texto_de(args[0], texto, sizeof(texto));
    error_en(0, "tiene() espera diccionario, lista o texto, no '%s'", texto);
    return de_nulo();
}

static Valor nativa_separar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "separar() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    Lista *l = nueva_lista(8);
    if (argc < 2) {
        /* split() de Python: sin separador, corta por espacios y descarta vacíos */
        uint32_t i = 0;
        while (i < t->largo) {
            while (i < t->largo && isspace((unsigned char)t->datos[i])) i++;
            uint32_t inicio = i;
            while (i < t->largo && !isspace((unsigned char)t->datos[i])) i++;
            if (i > inicio)
                lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + inicio, i - inicio)));
        }
        return de_lista(l);
    }
    if (args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO)
        error_en(0, "separar() espera un separador de texto");
    Texto *sep = (Texto *)args[1].v.obj;
    if (sep->largo == 0) {
        for (uint32_t i = 0; i < t->largo; i++)
            lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + i, 1)));
        return de_lista(l);
    }
    uint32_t inicio = 0;
    while (inicio <= t->largo) {
        uint32_t i = inicio;
        int encontrado = -1;
        while (i + sep->largo <= t->largo) {
            if (memcmp(t->datos + i, sep->datos, sep->largo) == 0) { encontrado = (int)i; break; }
            i++;
        }
        if (encontrado < 0) {
            lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + inicio, t->largo - inicio)));
            break;
        }
        lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + inicio, (uint32_t)encontrado - inicio)));
        inicio = (uint32_t)encontrado + sep->largo;
    }
    return de_lista(l);
}

static Valor nativa_reemplazar(VM *v, int argc, Valor *args) {
    (void)v;
    for (int i = 0; i < 3; i++)
        if (args[i].etiqueta != T_OBJ || args[i].v.obj->tipo != O_TEXTO)
            error_en(0, "reemplazar() espera tres cadenas");
    Texto *t = (Texto *)args[0].v.obj, *viejo = (Texto *)args[1].v.obj, *nuevo = (Texto *)args[2].v.obj;
    if (viejo->largo == 0)
        error_en(0, "reemplazar() no acepta un texto vacío que reemplazar");
    size_t capacidad = (size_t)t->largo + 1;
    char *salida = memoria(capacidad);
    size_t usado = 0;
    for (uint32_t i = 0; i < t->largo; ) {
        if (i + viejo->largo <= t->largo && memcmp(t->datos + i, viejo->datos, viejo->largo) == 0) {
            if (usado + nuevo->largo + 1 > capacidad) {
                capacidad = (usado + nuevo->largo + 1) * 2;
                salida = realloc(salida, capacidad);
            }
            memcpy(salida + usado, nuevo->datos, nuevo->largo);
            usado += nuevo->largo;
            i += viejo->largo;
        } else {
            salida[usado++] = t->datos[i++];
        }
    }
    salida[usado] = '\0';
    Texto *resultado = nuevo_texto_largo(salida, (uint32_t)usado);
    free(salida);
    return de_texto(resultado);
}

static Valor nativa_subtexto(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "subtexto() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    if (args[1].etiqueta == T_BOOL || !es_numero(args[1]))
        error_en(0, "subtexto() espera números para inicio y fin");
    int64_t inicio = a_entero(args[1]);
    int64_t fin = argc > 2 ? (args[2].etiqueta == T_BOOL || !es_numero(args[2])
                                  ? (error_en(0, "subtexto() espera números para inicio y fin"), 0)
                                  : a_entero(args[2]))
                           : (int64_t)t->largo;
    if (inicio < 0) inicio += t->largo;
    if (fin < 0) fin += t->largo;
    if (inicio < 0) inicio = 0;
    if (fin > (int64_t)t->largo) fin = t->largo;
    if (fin < inicio) fin = inicio;
    return de_texto(nuevo_texto_largo(t->datos + inicio, (uint32_t)(fin - inicio)));
}

static Valor nativa_letra(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "letra() espera una cadena");
    Texto *t = (Texto *)args[0].v.obj;
    if (args[1].etiqueta == T_BOOL || !es_numero(args[1]))
        error_en(0, "letra() espera una posición numérica");
    int64_t i = a_entero(args[1]);
    if (i < 0) i += t->largo;
    if (i < 0 || i >= (int64_t)t->largo)
        error_en(0, "índice fuera de rango: %lld (cadena de %u caracteres)", (long long)i, t->largo);
    return de_texto(nuevo_texto_largo(t->datos + i, 1));
}

static Valor nativa_empezar_con(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO ||
        args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO)
        error_en(0, "empezar_con() espera dos cadenas");
    Texto *t = (Texto *)args[0].v.obj, *p = (Texto *)args[1].v.obj;
    return de_bool(p->largo <= t->largo && memcmp(t->datos, p->datos, p->largo) == 0);
}

static Valor nativa_terminar_con(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO ||
        args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO)
        error_en(0, "terminar_con() espera dos cadenas");
    Texto *t = (Texto *)args[0].v.obj, *s = (Texto *)args[1].v.obj;
    return de_bool(s->largo <= t->largo &&
                   memcmp(t->datos + (t->largo - s->largo), s->datos, s->largo) == 0);
}

static Valor nativa_buscar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO ||
        args[1].etiqueta != T_OBJ || args[1].v.obj->tipo != O_TEXTO)
        error_en(0, "buscar() espera dos cadenas");
    Texto *t = (Texto *)args[0].v.obj, *aguja = (Texto *)args[1].v.obj;
    if (aguja->largo == 0) return de_entero(0);
    for (uint32_t i = 0; i + aguja->largo <= t->largo; i++)
        if (memcmp(t->datos + i, aguja->datos, aguja->largo) == 0) return de_entero(i);
    return de_entero(-1);
}

static Valor nativa_repetir(VM *v, int argc, Valor *args) {
    (void)v;
    int64_t veces = a_entero_estricto(args[1], "repetir");
    if (veces < 0) veces = 0;
    if (args[0].etiqueta == T_OBJ && args[0].v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)args[0].v.obj;
        Lista *nueva = nueva_lista((uint32_t)(l->largo * veces + 1));
        for (int64_t k = 0; k < veces; k++)
            for (uint32_t i = 0; i < l->largo; i++) lista_agregar(nueva, l->elementos[i]);
        return de_lista(nueva);
    }
    return op_mult(args[0], de_entero(veces), 0);
}

static Valor nativa_indice_de(VM *v, int argc, Valor *args) {
    (void)v;
    Valor secuencia = args[0], valor = args[1];
    if (secuencia.etiqueta == T_OBJ && secuencia.v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)secuencia.v.obj;
        for (uint32_t i = 0; i < l->largo; i++) if (iguales(l->elementos[i], valor)) return de_entero(i);
        return de_entero(-1);
    }
    if (secuencia.etiqueta == T_OBJ && secuencia.v.obj->tipo == O_TEXTO) {
        if (valor.etiqueta != T_OBJ || valor.v.obj->tipo != O_TEXTO) return de_entero(-1);
        Texto *t = (Texto *)secuencia.v.obj, *b = (Texto *)valor.v.obj;
        if (b->largo == 0) return de_entero(0);
        for (uint32_t i = 0; i + b->largo <= t->largo; i++)
            if (memcmp(t->datos + i, b->datos, b->largo) == 0) return de_entero(i);
        return de_entero(-1);
    }
    error_en(0, "indice_de() espera lista o texto");
    return de_nulo();
}

static Valor nativa_insertar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_LISTA)
        error_en(0, "insertar() espera una lista");
    Lista *l = (Lista *)args[0].v.obj;
    if (args[1].etiqueta == T_BOOL || !es_numero(args[1]))
        error_en(0, "insertar() espera un índice numérico");
    int64_t i = a_entero(args[1]);
    if (i < 0) i += l->largo;
    if (i < 0) i = 0;
    if (i > (int64_t)l->largo) i = l->largo;
    lista_agregar(l, de_nulo());
    for (uint32_t k = l->largo - 1; k > (uint32_t)i; k--) l->elementos[k] = l->elementos[k - 1];
    l->elementos[i] = args[2];
    return args[0];
}

static Valor nativa_quitar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_LISTA)
        error_en(0, "quitar() espera una lista");
    Lista *l = (Lista *)args[0].v.obj;
    if (l->largo == 0) error_en(0, "quitar() de una lista vacía");
    int64_t i = -1;
    if (argc > 1) {
        if (args[1].etiqueta == T_BOOL || !es_numero(args[1]))
            error_en(0, "quitar() espera un índice numérico");
        i = a_entero(args[1]);
        if (i < 0) i += l->largo;
        if (i < 0 || i >= (int64_t)l->largo)
            error_en(0, "índice fuera de rango: %lld (lista de %u elementos)", (long long)i, l->largo);
    } else {
        i = (int64_t)l->largo - 1;
    }
    Valor quitado = l->elementos[i];
    for (uint32_t k = (uint32_t)i; k + 1 < l->largo; k++) l->elementos[k] = l->elementos[k + 1];
    l->largo -= 1;
    return quitado;
}

static Valor nativa_eliminar(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_LISTA)
        error_en(0, "eliminar() espera una lista");
    Lista *l = (Lista *)args[0].v.obj;
    for (uint32_t i = 0; i < l->largo; i++) {
        if (iguales(l->elementos[i], args[1])) {
            for (uint32_t k = i; k + 1 < l->largo; k++) l->elementos[k] = l->elementos[k + 1];
            l->largo -= 1;
            return de_bool(1);
        }
    }
    return de_bool(0);
}

static Valor nativa_esperar(VM *v, int argc, Valor *args) {
    (void)v;
    double segundos = argc ? exigir_numero(args[0], "esperar") : 0;
    if (segundos > 0) {
        struct timespec peticion;
        peticion.tv_sec = (time_t)segundos;
        peticion.tv_nsec = (long)((segundos - (double)peticion.tv_sec) * 1e9);
        nanosleep(&peticion, NULL);
    }
    return de_nulo();
}

/* ------------------------------------------------------------ archivos
 * Las mismas nativas que jp/archivos.py: leer, escribir, agregar, existe,
 * tamaño y lista de una carpeta. */

static Texto *ruta_de(Valor x) {
    if (x.etiqueta != T_OBJ || x.v.obj->tipo != O_TEXTO || ((Texto *)x.v.obj)->largo == 0)
        error_en(0, "se esperaba una ruta de archivo en texto");
    return (Texto *)x.v.obj;
}

static Valor nativa_leer_archivo(VM *v, int argc, Valor *args) {
    (void)v;
    Texto *ruta = ruta_de(args[0]);
    FILE *a = fopen(ruta->datos, "rb");
    if (!a) {
        if (errno == EISDIR) error_en(0, "es una carpeta, no un archivo: %s", ruta->datos);
        error_en(0, "no existe el archivo: %s", ruta->datos);
    }
    size_t capacidad = 4096, usado = 0;
    char *datos = memoria(capacidad);
    for (;;) {
        if (usado == capacidad) { capacidad *= 2; datos = realloc(datos, capacidad); }
        size_t leidos = fread(datos + usado, 1, capacidad - usado, a);
        usado += leidos;
        if (leidos == 0) break;
    }
    fclose(a);
    Texto *resultado = nuevo_texto_largo(datos, (uint32_t)usado);
    free(datos);
    return de_texto(resultado);
}

static Valor escribir_texto(Texto *ruta, Valor contenido, const char *modo) {
    FILE *a = fopen(ruta->datos, modo);
    if (!a) error_en(0, "no se pudo escribir %s: %s", ruta->datos, strerror(errno));
    int bien = 1;
    if (contenido.etiqueta == T_OBJ && contenido.v.obj->tipo == O_TEXTO) {
        Texto *x = (Texto *)contenido.v.obj;
        bien = fwrite(x->datos, 1, x->largo, a) == x->largo;
    } else {
        char *texto = memoria(65536);
        texto_de(contenido, texto, 65536);
        size_t largo = strlen(texto);
        bien = fwrite(texto, 1, largo, a) == largo;
        free(texto);
    }
    fclose(a);
    if (!bien) error_en(0, "no se pudo escribir %s", ruta->datos);
    return de_bool(1);
}

static Valor nativa_escribir_archivo(VM *v, int argc, Valor *args) {
    (void)v;
    return escribir_texto(ruta_de(args[0]), args[1], "wb");
}

static Valor nativa_agregar_archivo(VM *v, int argc, Valor *args) {
    (void)v;
    return escribir_texto(ruta_de(args[0]), args[1], "ab");
}

static Valor nativa_existe_archivo(VM *v, int argc, Valor *args) {
    (void)v;
    return de_bool(access(ruta_de(args[0])->datos, F_OK) == 0);
}

static Valor nativa_tamano_archivo(VM *v, int argc, Valor *args) {
    (void)v;
    struct stat info;
    const char *ruta = ruta_de(args[0])->datos;
    if (stat(ruta, &info) != 0) return de_entero(0);
    return de_entero((int64_t)info.st_size);
}

static int comparar_entradas(const void *a, const void *b) {
    return strcmp((*(struct dirent *const *)a)->d_name, (*(struct dirent *const *)b)->d_name);
}

static Valor nativa_lista_archivos(VM *v, int argc, Valor *args) {
    (void)v;
    const char *ruta = (argc > 0 && args[0].etiqueta != T_NULO) ? ruta_de(args[0])->datos : ".";
    DIR *carpeta = opendir(ruta);
    if (!carpeta) error_en(0, "no es una carpeta: %s", ruta);
    size_t cantidad = 0, capacidad = 16;
    struct dirent **entradas = memoria(sizeof(struct dirent *) * capacidad);
    struct dirent *entrada;
    while ((entrada = readdir(carpeta)) != NULL) {
        if (strcmp(entrada->d_name, ".") == 0 || strcmp(entrada->d_name, "..") == 0) continue;
        if (cantidad == capacidad) {
            capacidad *= 2;
            entradas = realloc(entradas, sizeof(struct dirent *) * capacidad);
        }
        entradas[cantidad] = memoria(sizeof(struct dirent));
        memcpy(entradas[cantidad], entrada, sizeof(struct dirent));
        cantidad += 1;
    }
    closedir(carpeta);
    qsort(entradas, cantidad, sizeof(struct dirent *), comparar_entradas);
    Lista *l = nueva_lista(cantidad ? (uint32_t)cantidad : 1);
    for (size_t i = 0; i < cantidad; i++) {
        lista_agregar(l, de_texto(nuevo_texto(entradas[i]->d_name)));
        free(entradas[i]);
    }
    free(entradas);
    return de_lista(l);
}

/* ---------------------------------------------------------------- JSON
 * json_leer (texto -> valores de JP) y json_texto (valores de JP -> texto),
 * como jp/red.py. Sin red: el JSON es análisis y composición de texto. */

typedef struct {
    Texto *texto;
    uint32_t pos;
} Json;

static Valor json_valor(Json *j);

static void json_saltar(Json *j) {
    while (j->pos < j->texto->largo && isspace((unsigned char)j->texto->datos[j->pos])) j->pos++;
}

static void json_exigir(Json *j, char c) {
    json_saltar(j);
    if (j->pos >= j->texto->largo || j->texto->datos[j->pos] != c)
        error_en(0, "el JSON no es válido (se esperaba '%c' en la posición %u)", c, j->pos);
    j->pos++;
}

static Valor json_cadena(Json *j) {
    json_exigir(j, '"');
    size_t capacidad = 32, usado = 0;
    char *salida = memoria(capacidad);
    while (j->pos < j->texto->largo && j->texto->datos[j->pos] != '"') {
        char c = j->texto->datos[j->pos++];
        if (c == '\\') {
            if (j->pos >= j->texto->largo) break;
            char e = j->texto->datos[j->pos++];
            if (e == 'n') c = '\n';
            else if (e == 't') c = '\t';
            else if (e == 'r') c = '\r';
            else if (e == 'b') c = '\b';
            else if (e == 'f') c = '\f';
            else if (e == 'u') {
                if (j->pos + 4 > j->texto->largo) error_en(0, "el JSON no es válido (\\u incompleto)");
                char hex[5] = {j->texto->datos[j->pos], j->texto->datos[j->pos + 1],
                               j->texto->datos[j->pos + 2], j->texto->datos[j->pos + 3], 0};
                j->pos += 4;
                unsigned punto = (unsigned)strtoul(hex, NULL, 16);
                if (usado + 4 >= capacidad) { capacidad *= 2; salida = realloc(salida, capacidad); }
                if (punto < 0x80) salida[usado++] = (char)punto;
                else if (punto < 0x800) {
                    salida[usado++] = (char)(0xC0 | (punto >> 6));
                    salida[usado++] = (char)(0x80 | (punto & 0x3F));
                } else {
                    salida[usado++] = (char)(0xE0 | (punto >> 12));
                    salida[usado++] = (char)(0x80 | ((punto >> 6) & 0x3F));
                    salida[usado++] = (char)(0x80 | (punto & 0x3F));
                }
                continue;
            }
        }
        if (usado + 4 >= capacidad) { capacidad *= 2; salida = realloc(salida, capacidad); }
        salida[usado++] = c;
    }
    json_exigir(j, '"');
    Texto *resultado = nuevo_texto_largo(salida, (uint32_t)usado);
    free(salida);
    return de_texto(resultado);
}

static Valor json_valor(Json *j) {
    json_saltar(j);
    if (j->pos >= j->texto->largo) error_en(0, "el JSON no es válido (terminó antes de tiempo)");
    char c = j->texto->datos[j->pos];
    if (c == '{') {
        j->pos++;
        Dicto *d = nuevo_dicto();
        json_saltar(j);
        if (j->pos < j->texto->largo && j->texto->datos[j->pos] == '}') { j->pos++; return de_objeto((Obj *)d); }
        for (;;) {
            Valor clave = json_cadena(j);
            json_exigir(j, ':');
            dicto_poner(d, (Texto *)clave.v.obj, json_valor(j));
            json_saltar(j);
            if (j->pos < j->texto->largo && j->texto->datos[j->pos] == ',') { j->pos++; continue; }
            json_exigir(j, '}');
            return de_objeto((Obj *)d);
        }
    }
    if (c == '[') {
        j->pos++;
        Lista *l = nueva_lista(8);
        json_saltar(j);
        if (j->pos < j->texto->largo && j->texto->datos[j->pos] == ']') { j->pos++; return de_lista(l); }
        for (;;) {
            lista_agregar(l, json_valor(j));
            json_saltar(j);
            if (j->pos < j->texto->largo && j->texto->datos[j->pos] == ',') { j->pos++; continue; }
            json_exigir(j, ']');
            return de_lista(l);
        }
    }
    if (c == '"') return json_cadena(j);
    if (j->texto->largo - j->pos >= 4 && memcmp(j->texto->datos + j->pos, "true", 4) == 0) { j->pos += 4; return de_bool(1); }
    if (j->texto->largo - j->pos >= 5 && memcmp(j->texto->datos + j->pos, "false", 5) == 0) { j->pos += 5; return de_bool(0); }
    if (j->texto->largo - j->pos >= 4 && memcmp(j->texto->datos + j->pos, "null", 4) == 0) { j->pos += 4; return de_nulo(); }
    if (strchr("+-0123456789", c)) {
        const char *inicio = j->texto->datos + j->pos;
        char *fin = NULL;
        long long entero = strtoll(inicio, &fin, 10);
        if (fin && (*fin == '.' || *fin == 'e' || *fin == 'E')) {
            double decimal = strtod(inicio, &fin);
            j->pos += (uint32_t)(fin - inicio);
            return de_decimal(decimal);
        }
        if (fin == inicio) error_en(0, "el JSON no es válido (número mal formado)");
        j->pos += (uint32_t)(fin - inicio);
        return de_entero((int64_t)entero);
    }
    error_en(0, "el JSON no es válido (no entiendo '%c' en la posición %u)", c, j->pos);
    return de_nulo();
}

static Valor nativa_json_leer(VM *v, int argc, Valor *args) {
    (void)v;
    if (args[0].etiqueta != T_OBJ || args[0].v.obj->tipo != O_TEXTO)
        error_en(0, "json_leer() espera una cadena de texto");
    Json j = {(Texto *)args[0].v.obj, 0};
    Valor resultado = json_valor(&j);
    json_saltar(&j);
    if (j.pos != j.texto->largo) error_en(0, "el JSON no es válido (sobra texto al final)");
    return resultado;
}

/* --- json_texto: serializa con la misma forma que json.dumps --- */

typedef struct {
    char *datos;
    size_t usado;
    size_t capacidad;
} Buffer;

static void buffer_agregar(Buffer *b, const char *texto) {
    size_t largo = strlen(texto);
    if (b->usado + largo + 1 > b->capacidad) {
        while (b->capacidad < b->usado + largo + 1) b->capacidad *= 2;
        b->datos = realloc(b->datos, b->capacidad);
    }
    memcpy(b->datos + b->usado, texto, largo);
    b->usado += largo;
    b->datos[b->usado] = '\0';
}

static void json_escribir_cadena(Buffer *b, Texto *t) {
    buffer_agregar(b, "\"");
    char trozo[16];
    for (uint32_t i = 0; i < t->largo; i++) {
        unsigned char c = (unsigned char)t->datos[i];
        if (c == '"') buffer_agregar(b, "\\\"");
        else if (c == '\\') buffer_agregar(b, "\\\\");
        else if (c == '\n') buffer_agregar(b, "\\n");
        else if (c == '\r') buffer_agregar(b, "\\r");
        else if (c == '\t') buffer_agregar(b, "\\t");
        else if (c < 0x20) { snprintf(trozo, sizeof(trozo), "\\u%04x", c); buffer_agregar(b, trozo); }
        else { trozo[0] = (char)c; trozo[1] = '\0'; buffer_agregar(b, trozo); }
    }
    buffer_agregar(b, "\"");
}

static void json_escribir_numero(Buffer *b, Valor v) {
    char numero[64];
    if (v.etiqueta == T_INT) {
        snprintf(numero, sizeof(numero), "%lld", (long long)v.v.entero);
    } else {
        double d = v.v.decimal;
        if (d == floor(d) && fabs(d) < 1e15) {
            snprintf(numero, sizeof(numero), "%.0f", d);
        } else {
            for (int precision = 15; precision <= 17; precision++) {
                snprintf(numero, sizeof(numero), "%.*g", precision, d);
                if (strtod(numero, NULL) == d) break;
            }
            /* Python escribe los exponentes como 'e+20' / 'e-07' */
            for (char *p = numero; *p; p++) {
                if (*p != 'e' && *p != 'E') continue;
                char *signo = p + 1;
                if (*signo != '+' && *signo != '-') {
                    memmove(signo + 1, signo, strlen(signo) + 1);
                    *signo = '+';
                }
                if (signo[1] != '-' && signo[1] != '\0' && signo[2] == '\0') {
                    memmove(signo + 2, signo + 1, 2);
                    signo[1] = '0';
                }
                break;
            }
        }
    }
    buffer_agregar(b, numero);
}

static void json_escribir_valor(Buffer *b, Valor v) {
    if (v.etiqueta == T_NULO) { buffer_agregar(b, "null"); return; }
    if (v.etiqueta == T_BOOL) { buffer_agregar(b, v.v.entero ? "true" : "false"); return; }
    if (v.etiqueta == T_INT || v.etiqueta == T_DBL) { json_escribir_numero(b, v); return; }
    if (v.etiqueta != T_OBJ) { buffer_agregar(b, "null"); return; }
    switch (v.v.obj->tipo) {
        case O_TEXTO:
            json_escribir_cadena(b, (Texto *)v.v.obj);
            return;
        case O_LISTA: {
            Lista *l = (Lista *)v.v.obj;
            buffer_agregar(b, "[");
            for (uint32_t i = 0; i < l->largo; i++) {
                if (i) buffer_agregar(b, ", ");
                json_escribir_valor(b, l->elementos[i]);
            }
            buffer_agregar(b, "]");
            return;
        }
        case O_DICTO: {
            Dicto *d = (Dicto *)v.v.obj;
            buffer_agregar(b, "{");
            for (uint32_t i = 0; i < d->largo; i++) {
                if (i) buffer_agregar(b, ", ");
                json_escribir_cadena(b, d->entradas[i].clave);
                buffer_agregar(b, ": ");
                json_escribir_valor(b, d->entradas[i].valor);
            }
            buffer_agregar(b, "}");
            return;
        }
        default: {
            char texto[256];
            texto_de(v, texto, sizeof(texto));
            error_en(0, "json_texto() no sabe serializar '%s'", texto);
            return;
        }
    }
}

static Valor nativa_json_texto(VM *v, int argc, Valor *args) {
    (void)v;
    Buffer b;
    b.datos = memoria(64);
    b.usado = 0;
    b.capacidad = 64;
    b.datos[0] = '\0';
    json_escribir_valor(&b, args[0]);
    Texto *resultado = nuevo_texto_largo(b.datos, (uint32_t)b.usado);
    free(b.datos);
    return de_texto(resultado);
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
    if (!fgets(linea, sizeof(linea), stdin))
        error_en(0, "leer() no recibió entrada (fin de archivo)");
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
    if (n_nativas_registradas < NATIVAS_MAX) {
        nativas_por_nombre[n_nativas_registradas] = n;
        nombres_nativas[n_nativas_registradas] = nombre;
        n_nativas_registradas += 1;
    }
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
    /* el oráculo (jp/vm.py) lanza sus errores de ejecución sin columna:
       siempre imprime "columna 0" y el puntero en la primera columna. */
    if (fin > inicio && vm->fuente[fin - 1] == '\r') fin--;
    printf("    --> línea %u, columna 0\n", numero);
    printf(" %4u | %.*s\n", numero, (int)(fin - inicio), vm->fuente + inicio);
    printf("      | ^\n");
}

/* ------------------------------------------- orden superior
 * mapear, filtrar, reducir, para_cada y ordenar: las mismas de jp/red.py y
 * jp/interprete.py, pero llamando a funciones de JP desde C.
 *
 * Para llamar a un valor hay que reentrar al bucle con un marco nuevo; el
 * bucle vuelve cuando ese marco se cierra (vm->piso_marco). Todo lo que tiene
 * que sobrevivir a una llamada (una lista a medio construir, un acumulador) se
 * deja en la pila del VM, que es raíz del recolector. */

static void bucle(uint32_t pc_inicio);   /* adelante: lo reentran las nativas */
static Valor llamar_valor(Valor callee, int argc, Valor *args);
static int valor_menor(Valor a, Valor b);

/* Copia de la secuencia (como _secuencia() en Python): lista, texto,
 * diccionario (sus claves) o número (1..n). La copia es inalcanzable desde JP,
 * así que el programa no puede cambiarla mientras se itera. */
static Lista *secuencia_para(Valor v, const char *nombre) {
    if (v.etiqueta == T_OBJ && v.v.obj->tipo == O_LISTA) {
        Lista *original = (Lista *)v.v.obj;
        Lista *copia = nueva_lista(original->largo);
        for (uint32_t i = 0; i < original->largo; i++) lista_agregar(copia, original->elementos[i]);
        return copia;
    }
    if (v.etiqueta == T_OBJ && v.v.obj->tipo == O_TEXTO) {
        Texto *texto = (Texto *)v.v.obj;
        Lista *copia = nueva_lista(8);
        uint32_t i = 0;
        while (i < texto->largo) {
            uint32_t inicio = i;
            i += 1;
            while (i < texto->largo && ((unsigned char)texto->datos[i] & 0xC0) == 0x80) i += 1;
            lista_agregar(copia, de_texto(nuevo_texto_largo(texto->datos + inicio, i - inicio)));
        }
        return copia;
    }
    if (v.etiqueta == T_OBJ && v.v.obj->tipo == O_DICTO) {
        Dicto *d = (Dicto *)v.v.obj;
        Lista *copia = nueva_lista(d->largo);
        for (uint32_t i = 0; i < d->largo; i++) lista_agregar(copia, de_texto(d->entradas[i].clave));
        return copia;
    }
    if (v.etiqueta == T_INT || v.etiqueta == T_DBL) {
        int64_t hasta = v.etiqueta == T_INT ? v.v.entero : (int64_t)v.v.decimal;
        Lista *copia = nueva_lista(8);
        for (int64_t i = 1; i <= hasta; i++) lista_agregar(copia, de_entero(i));
        return copia;
    }
    char texto[256];
    texto_de(v, texto, sizeof(texto));
    error_en(0, "%s() espera lista, texto, diccionario o número, no '%s'", nombre, texto);
    return NULL;
}

static const char *tipo_python(Valor v) {
    switch (v.etiqueta) {
        case T_NULO: return "NoneType";
        case T_BOOL: return "bool";
        case T_INT: return "int";
        case T_DBL: return "float";
        default: break;
    }
    switch (v.v.obj->tipo) {
        case O_TEXTO: return "str";
        case O_LISTA: return "list";
        case O_DICTO: return "dict";
        case O_NATIVA: return "FuncionNativa";
        default: return "Cierre";
    }
}

/* a < b con las reglas de Python (y su mismo mensaje si no se puede comparar) */
static int valor_menor(Valor a, Valor b) {
    int a_num = a.etiqueta == T_INT || a.etiqueta == T_DBL;
    int b_num = b.etiqueta == T_INT || b.etiqueta == T_DBL;
    if (a_num && b_num) {
        if (a.etiqueta == T_INT && b.etiqueta == T_INT) return a.v.entero < b.v.entero;
        double x = a.etiqueta == T_INT ? (double)a.v.entero : a.v.decimal;
        double y = b.etiqueta == T_INT ? (double)b.v.entero : b.v.decimal;
        return x < y;
    }
    int a_txt = a.etiqueta == T_OBJ && a.v.obj->tipo == O_TEXTO;
    int b_txt = b.etiqueta == T_OBJ && b.v.obj->tipo == O_TEXTO;
    if (a_txt && b_txt) {
        Texto *ta = (Texto *)a.v.obj, *tb = (Texto *)b.v.obj;
        uint32_t minimo = ta->largo < tb->largo ? ta->largo : tb->largo;
        int comparacion = memcmp(ta->datos, tb->datos, minimo);
        if (comparacion != 0) return comparacion < 0;
        return ta->largo < tb->largo;
    }
    int a_lista = a.etiqueta == T_OBJ && a.v.obj->tipo == O_LISTA;
    int b_lista = b.etiqueta == T_OBJ && b.v.obj->tipo == O_LISTA;
    if (a_lista && b_lista) {
        Lista *la = (Lista *)a.v.obj, *lb = (Lista *)b.v.obj;
        uint32_t minimo = la->largo < lb->largo ? la->largo : lb->largo;
        for (uint32_t i = 0; i < minimo; i++) {
            if (valor_menor(la->elementos[i], lb->elementos[i])) return 1;
            if (valor_menor(lb->elementos[i], la->elementos[i])) return 0;
        }
        return la->largo < lb->largo;
    }
    error_en(0, "ordenar() no puede comparar esos valores: '<' not supported between "
                "instances of '%s' and '%s'", tipo_python(a), tipo_python(b));
    return 0;
}

/* Llamar a un valor de JP (función, cierre, ligada o nativa) desde una nativa. */
static Valor llamar_valor(Valor callee, int argc, Valor *args) {
    if (callee.etiqueta == T_OBJ && callee.v.obj->tipo == O_LIGADA) {
        Ligada *lig = (Ligada *)callee.v.obj;
        Nativa *nativa = nativa_por_nombre(lig->nombre);
        if (!nativa)
            error_en(0, "no existe el método '%.*s'",
                     (int)lig->nombre->largo, lig->nombre->datos);
        Valor *guardado = vm->sp;
        *vm->sp++ = callee;                              /* el callee va primero */
        *vm->sp++ = lig->receptor;                       /* y el receptor, de primer argumento */
        for (int i = 0; i < argc; i++) *vm->sp++ = args[i];
        int total = argc + 1;
        if (nativa->aridad >= 0 && nativa->aridad != (int8_t)total)
            error_en(0, "%s() espera %d argumento(s), recibió %d",
                     nativa->nombre, nativa->aridad, total);
        Valor resultado = nativa->funcion(vm, total, vm->sp - total);
        vm->sp = guardado;
        return resultado;
    }
    if (callee.etiqueta == T_OBJ && callee.v.obj->tipo == O_NATIVA) {
        Nativa *nativa = (Nativa *)callee.v.obj;
        if (nativa->aridad >= 0 && nativa->aridad != (int8_t)argc)
            error_en(0, "%s() espera %d argumento(s), recibió %d",
                     nativa->nombre, nativa->aridad, argc);
        Valor *guardado = vm->sp;
        *vm->sp++ = callee;
        for (int i = 0; i < argc; i++) *vm->sp++ = args[i];
        Valor resultado = nativa->funcion(vm, argc, vm->sp - argc);
        vm->sp = guardado;
        return resultado;
    }
    if (callee.etiqueta != T_OBJ || callee.v.obj->tipo != O_FUNCION) {
        char texto[512];
        texto_de(callee, texto, sizeof(texto));
        error_en(0, "este valor no es una función: '%s'", texto);
    }
    Cierre *cierre = (Cierre *)callee.v.obj;
    Funcion *f = cierre->funcion;
    int con_defectos = f->codigo[0] == 57 /* DEFECTOS */;
    if ((uint32_t)argc > f->aridad || (!con_defectos && f->aridad != (uint32_t)argc))
        error_en(0, "la función '%s' espera %u argumento(s), recibió %d",
                 f->nombre->datos, f->aridad, argc);
    if (vm->marco - vm->marcos >= MARCOS_MAX - 1)
        error_en(0, "desbordamiento de pila (¿recursión infinita?)");
    Valor *guardado = vm->sp;
    *vm->sp++ = callee;
    for (int i = 0; i < argc; i++) *vm->sp++ = args[i];
    Valor *nueva_base = vm->sp - argc - 1;
    for (uint32_t i = (uint32_t)argc; i < f->n_slots; i++)
        *vm->sp++ = i < f->aridad ? de_centinela() : de_nulo();
    Marco *piso_anterior = vm->piso_marco;
    vm->piso_marco = vm->marco;
    vm->marco += 1;
    vm->marco->funcion = f;
    vm->marco->base = nueva_base + 1;
    vm->marco->ip = f->codigo;
    vm->marco->upvalues = cierre->upvalues;
    vm->marco->n_upvalues = cierre->n_upvalues;
    vm->marco->n_manejadores = vm->n_manejadores;
    vm->marco->n_args = (uint32_t)argc;

    uint32_t nivel = vm->n_niveles;
    if (nivel >= 256) error_en(0, "demasiadas llamadas anidadas desde nativas");
    /* el marco que llama es el suelo de este nivel: un 'intenta' de más arriba
     * no se puede reanudar aquí (su pila de C ya no existe) */
    vm->niveles[nivel].piso = vm->marco - 1;
    vm->n_niveles = nivel + 1;
    vm->pc_inicio = 0;
    for (;;) {
        if (setjmp(vm->niveles[nivel].salto) != 0) {
            vm->n_niveles = nivel;
            if (vm->n_manejadores == 0) {
                /* nada que atrapar aquí: fuera */
                if (vm->n_niveles > 0) longjmp(vm->niveles[vm->n_niveles - 1].salto, 1);
                longjmp(vm->salto_error, 1);
            }
            Maneja *m = &vm->manejadores[vm->n_manejadores - 1];
            if (m->marco <= vm->niveles[nivel].piso) {
                /* el 'intenta' es de más arriba: que lo atrape un nivel de fuera */
                if (vm->n_niveles > 0) longjmp(vm->niveles[vm->n_niveles - 1].salto, 1);
                longjmp(vm->salto_error, 1);
            }
            vm->n_manejadores -= 1;
            vm->marco = m->marco;
            vm->sp = m->sp;
            vm->pc_inicio = m->pc;
            vm->piso_marco = vm->niveles[nivel].piso;
            vm->n_niveles = nivel + 1;
            continue;
        }
        bucle(vm->pc_inicio);
        break;
    }
    vm->n_niveles = nivel;
    vm->piso_marco = piso_anterior;
    Valor resultado = vm->ultimo_valor;
    vm->sp = guardado;
    return resultado;
}

/* raiz[0] = secuencia copiada · raiz[1] = resultado · raiz[2] = temporal */
#define RAICES_ORDEN()                                              \
    Valor *raiz = vm->sp;                                           \
    raiz[0] = de_nulo(); raiz[1] = de_nulo(); raiz[2] = de_nulo();  \
    vm->sp += 3

static Valor nativa_mapear(VM *v, int argc, Valor *args) {
    (void)v;
    RAICES_ORDEN();
    raiz[0] = de_lista(secuencia_para(args[0], "mapear"));
    Lista *original = (Lista *)raiz[0].v.obj;
    raiz[1] = de_lista(nueva_lista(original->largo));
    for (uint32_t i = 0; i < original->largo; i++) {
        raiz[2] = original->elementos[i];
        raiz[2] = llamar_valor(args[1], 1, &raiz[2]);
        lista_agregar((Lista *)raiz[1].v.obj, raiz[2]);
    }
    Valor salida = raiz[1];
    vm->sp = raiz;
    return salida;
}

static Valor nativa_filtrar(VM *v, int argc, Valor *args) {
    (void)v;
    RAICES_ORDEN();
    raiz[0] = de_lista(secuencia_para(args[0], "filtrar"));
    Lista *original = (Lista *)raiz[0].v.obj;
    raiz[1] = de_lista(nueva_lista(4));
    for (uint32_t i = 0; i < original->largo; i++) {
        raiz[2] = original->elementos[i];
        Valor prueba = llamar_valor(args[1], 1, &raiz[2]);
        if (es_verdad(prueba)) lista_agregar((Lista *)raiz[1].v.obj, raiz[2]);
    }
    Valor salida = raiz[1];
    vm->sp = raiz;
    return salida;
}

static Valor nativa_para_cada(VM *v, int argc, Valor *args) {
    (void)v;
    RAICES_ORDEN();
    raiz[0] = de_lista(secuencia_para(args[0], "para_cada"));
    Lista *original = (Lista *)raiz[0].v.obj;
    for (uint32_t i = 0; i < original->largo; i++) {
        raiz[2] = original->elementos[i];
        llamar_valor(args[1], 1, &raiz[2]);
    }
    vm->sp = raiz;
    return de_nulo();
}

static Valor nativa_reducir(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 2 && argc != 3) error_en(0, "reducir() espera 2 o 3 argumentos");
    RAICES_ORDEN();
    raiz[0] = de_lista(secuencia_para(args[0], "reducir"));
    Lista *original = (Lista *)raiz[0].v.obj;
    uint32_t inicio = 1;
    if (argc == 3) { raiz[1] = args[2]; inicio = 0; }
    else if (original->largo > 0) raiz[1] = original->elementos[0];
    else {
        vm->sp = raiz;
        error_en(0, "reducir() de una lista vacía necesita un valor inicial");
    }
    for (uint32_t i = inicio; i < original->largo; i++) {
        Valor argumentos[2];
        argumentos[0] = raiz[1];
        argumentos[1] = original->elementos[i];
        raiz[1] = llamar_valor(args[1], 2, argumentos);
    }
    Valor salida = raiz[1];
    vm->sp = raiz;
    return salida;
}

/* ordenar() estable: inserción (como el binary insertion sort de CPython en
 * listas cortas). Se comparan claves y se mueven elementos y claves a la vez. */
static void ordenar_estable(Lista *elementos, Lista *claves) {
    for (uint32_t i = 1; i < elementos->largo; i++) {
        Valor clave = claves->elementos[i], elemento = elementos->elementos[i];
        uint32_t j = i;
        while (j > 0 && valor_menor(clave, claves->elementos[j - 1])) {
            claves->elementos[j] = claves->elementos[j - 1];
            elementos->elementos[j] = elementos->elementos[j - 1];
            j -= 1;
        }
        claves->elementos[j] = clave;
        elementos->elementos[j] = elemento;
    }
}

static Valor nativa_ordenar(VM *v, int argc, Valor *args) {
    (void)v;
    if (argc != 1 && argc != 2) error_en(0, "ordenar() espera 1 o 2 argumentos");
    RAICES_ORDEN();
    raiz[0] = de_lista(secuencia_para(args[0], "ordenar"));
    Lista *original = (Lista *)raiz[0].v.obj;
    raiz[1] = de_lista(nueva_lista(original->largo));
    for (uint32_t i = 0; i < original->largo; i++)
        lista_agregar((Lista *)raiz[1].v.obj, original->elementos[i]);
    Lista *claves = nueva_lista(original->largo);
    raiz[2] = de_lista(claves);
    if (argc == 2) {
        for (uint32_t i = 0; i < original->largo; i++) {
            Valor argumento = original->elementos[i];
            lista_agregar(claves, llamar_valor(args[1], 1, &argumento));
        }
    } else {
        for (uint32_t i = 0; i < original->largo; i++) lista_agregar(claves, original->elementos[i]);
    }
    ordenar_estable((Lista *)raiz[1].v.obj, claves);
    Valor salida = raiz[1];
    vm->sp = raiz;
    return salida;
}


/* -------------------------------------------------------- despachador */

static void bucle(uint32_t pc_inicio) {
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
        &&L_EXPR_SENT, &&L_FIN, &&L_DICT, &&L_MANEJAR, &&L_FIN_MANEJAR, &&L_ERROR_EN,
        &&L_SALTO_NO_NULO_MANTENER, &&L_CREAR_CLASE, &&L_DEFECTOS,
        &&L_SALTAR_SI_HAY_VALOR, &&L_ITER_NEXT_PAR, &&L_ITER_NEXT_PAR_CELDA,
        &&L_DESESTRUCTURAR, &&L_VERIFICAR_TIPO, &&L_VERIFICAR_ARG, &&L_VERIFICAR_RET,
    };

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
    register uint32_t *ip = marco->funcion->codigo + pc_inicio;
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
L_SALTO_NO_NULO_MANTENER: {
    int32_t relativo = LEER_I32();
    if (vm->sp[-1].etiqueta != T_NULO) ip = ip + relativo;
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
    if (callee.etiqueta == T_OBJ && callee.v.obj->tipo == O_LIGADA) {
        /* "hola".mayusculas() -> mayusculas("hola"): el receptor entra como
         * primer argumento y el callee pasa a ser la nativa. */
        Ligada *lig = (Ligada *)callee.v.obj;
        Nativa *nativa = nativa_por_nombre(lig->nombre);
        if (!nativa) {
            ACTUALIZAR_IP();
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "no existe el método '%.*s'",
                     (int)lig->nombre->largo, lig->nombre->datos);
        }
        /* se corre un hueco hacia arriba para meter el receptor como args[0] */
        memmove(vm->sp - argc + 1, vm->sp - argc, sizeof(Valor) * argc);
        vm->sp[-(int32_t)argc] = lig->receptor;
        vm->sp += 1;
        vm->sp[-2 - (int32_t)argc] = de_objeto((Obj *)nativa);
        argc += 1;
        callee = de_objeto((Obj *)nativa);
    }
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
    if (obj->tipo == O_CLASE) {
        /* instanciar: objeto nuevo + su 'iniciar' si lo hay */
        Clase *cl = (Clase *)obj;
        int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
        Cierre *ini = buscar_metodo_cstr(cl, "iniciar");
        Instancia *ins = nuevo_objeto(sizeof(Instancia), O_INSTANCIA);
        ins->clase = cl;
        ins->campos = nuevo_dicto();
        Valor valor_ins = de_objeto((Obj *)ins);
        if (!ini) {
            if (argc > 0)
                error_en(linea, "la clase '%.*s' no tiene un método 'iniciar' y no acepta argumentos",
                         (int)cl->nombre->largo, cl->nombre->datos);
            vm->sp -= argc + 1;
            PUSH(valor_ins);
            SIGUIENTE();
        }
        if (argc > ini->funcion->aridad - 1 ||
            (ini->funcion->codigo[0] != 57 /* DEFECTOS */ && argc != ini->funcion->aridad - 1))
            error_en(linea, "la clase '%.*s' espera %u argumento(s) en su 'iniciar', recibió %u",
                     (int)cl->nombre->largo, cl->nombre->datos,
                     ini->funcion->aridad - 1, argc);
        Valor *args_ini = memoria(sizeof(Valor) * (argc + 1));
        args_ini[0] = valor_ins;
        for (uint32_t i = 0; i < argc; i++)
            args_ini[i + 1] = vm->sp[(int32_t)i - (int32_t)argc];
        ACTUALIZAR_IP();
        llamar_valor(de_objeto((Obj *)ini), (int)argc + 1, args_ini);
        vm->bytes_reservados -= sizeof(Valor) * (argc + 1);
        free(args_ini);
        vm->sp -= argc + 1;
        PUSH(valor_ins);
        SIGUIENTE();
    }
    if (obj->tipo == O_METODO) {
        /* el receptor entra como primer argumento ('este') y el callee
         * pasa a ser el cierre del método: seguir por el camino normal */
        Metodo *mt = (Metodo *)obj;
        memmove(vm->sp - argc + 1, vm->sp - argc, sizeof(Valor) * argc);
        vm->sp += 1;
        vm->sp[-2 - (int32_t)argc] = de_objeto((Obj *)mt->cierre);
        vm->sp[-1 - (int32_t)argc] = mt->receptor;
        argc += 1;
        obj = (Obj *)mt->cierre;
    }
    if (obj->tipo != O_FUNCION) {
        char texto[256];
        texto_de(callee, texto, sizeof(texto));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "este valor no es una función: '%s'", texto);
    }
    Cierre *cierre = (Cierre *)obj;
    Funcion *f = cierre->funcion;
    int con_defectos = f->codigo[0] == 57 /* DEFECTOS */;
    if (argc > f->aridad || (!con_defectos && argc != f->aridad)) {
        ACTUALIZAR_IP();
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "la función '%s' espera %u argumento(s), recibió %u",
                 f->nombre->datos, f->aridad, argc);
    }
    if (vm->marco - vm->marcos >= MARCOS_MAX - 1)
        error_en(0, "desbordamiento de pila (¿recursión infinita?)");
    /* reutilizar los argumentos como primeros locales; los parámetros
     * que faltan llevan el centinela (su defecto los sustituye) */
    Valor *nueva_base = vm->sp - argc - 1;
    for (uint32_t i = argc; i < f->n_slots; i++)
        *vm->sp++ = i < f->aridad ? de_centinela() : de_nulo();
    ACTUALIZAR_IP();
    vm->marco += 1;
    vm->marco->funcion = f;
    vm->marco->base = nueva_base + 1;
    vm->marco->ip = f->codigo;
    vm->marco->upvalues = cierre->upvalues;
    vm->marco->n_upvalues = cierre->n_upvalues;
    vm->marco->n_manejadores = vm->n_manejadores;
    vm->marco->n_args = argc;
    RECARGAR();
    SIGUIENTE();
}

L_RETORNAR: {
    Valor resultado = POP();
    vm->marco->ip = ip;
    vm->n_manejadores = vm->marco->n_manejadores;  /* se van sus 'intenta' */
    vm->sp = base;          /* descarta locales y temporales del marco */
    vm->marco -= 1;
    if (vm->marco == vm->piso_marco) {
        vm->ultimo_valor = resultado;  /* se cierra el nivel: vuelve al que llamó */
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
    vm->n_manejadores = vm->marco->n_manejadores;
    vm->sp = base;
    vm->marco -= 1;
    if (vm->marco == vm->piso_marco) {
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
    int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_DICTO) {
        if (indice.etiqueta != T_OBJ || indice.v.obj->tipo != O_TEXTO)
            error_en(linea, "la clave de un diccionario debe ser texto");
        Dicto *d = (Dicto *)objeto.v.obj;
        Texto *clave = (Texto *)indice.v.obj;
        Valor *guardado = dicto_buscar(d, clave);
        if (guardado) {
            PUSH(*guardado);
            SIGUIENTE();
        }
        Nativa *metodo = metodo_de_valor(objeto, clave);  /* la clave manda; el método es el respaldo */
        if (metodo) {
            PUSH(de_ligada(metodo, objeto));
            SIGUIENTE();
        }
        char disponibles[512];
        size_t usado = 0;
        for (uint32_t i = 0; i < d->largo && usado < sizeof(disponibles) - 1; i++)
            usado += (size_t)snprintf(disponibles + usado, sizeof(disponibles) - usado, "%s%.*s",
                                      i ? ", " : "", (int)d->entradas[i].clave->largo,
                                      d->entradas[i].clave->datos);
        if (!usado) snprintf(disponibles, sizeof(disponibles), "ninguna");
        error_en(linea, "no existe la clave '%.*s' (claves disponibles: %s)",
                 (int)clave->largo, clave->datos, disponibles);
    }
    /* texto.longitud, lista.ordenar...: el nombre del método trae la nativa ligada */
    if (objeto.etiqueta == T_OBJ && indice.etiqueta == T_OBJ && indice.v.obj->tipo == O_TEXTO &&
        (objeto.v.obj->tipo == O_TEXTO || objeto.v.obj->tipo == O_LISTA)) {
        Nativa *metodo = metodo_de_valor(objeto, (Texto *)indice.v.obj);
        if (!metodo)
            error_en(linea, "no existe el método '%.*s' para %s",
                     (int)((Texto *)indice.v.obj)->largo, ((Texto *)indice.v.obj)->datos,
                     nombre_tipo_objeto(objeto.v.obj->tipo));
        PUSH(de_ligada(metodo, objeto));
        SIGUIENTE();
    }
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_LISTA) {
        Lista *l = (Lista *)objeto.v.obj;
        int64_t i = indice_normalizado(indice, l->largo, "una lista", linea);
        if (i < 0 || i >= (int64_t)l->largo) {
            char texto[64];
            snprintf(texto, sizeof(texto), "%lld (lista de %u elementos)", (long long)i, l->largo);
            error_en(linea, "índice fuera de rango: %s", texto);
        }
        PUSH(l->elementos[i]);
        SIGUIENTE();
    }
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)objeto.v.obj;
        int64_t i = indice_normalizado(indice, t->largo, "una cadena", linea);
        if (i < 0 || i >= (int64_t)t->largo)
            error_en(linea, "índice fuera de rango: %lld (cadena de %u caracteres)", (long long)i, t->largo);
        PUSH(de_texto(nuevo_texto_largo(t->datos + i, 1)));
        SIGUIENTE();
    }
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_INSTANCIA) {
        Instancia *ins = (Instancia *)objeto.v.obj;
        if (indice.etiqueta != T_OBJ || indice.v.obj->tipo != O_TEXTO)
            error_en(linea, "los objetos de '%.*s' solo tienen atributos con nombre",
                     (int)ins->clase->nombre->largo, ins->clase->nombre->datos);
        Texto *clave = (Texto *)indice.v.obj;
        Valor *campo = dicto_buscar(ins->campos, clave);
        if (campo) {
            PUSH(*campo);
            SIGUIENTE();
        }
        Cierre *metodo = buscar_metodo_clase(ins->clase, clave);
        if (metodo) {
            Metodo *ligado = nuevo_objeto(sizeof(Metodo), O_METODO);
            ligado->cierre = metodo;
            ligado->receptor = objeto;
            PUSH(de_objeto((Obj *)ligado));
            SIGUIENTE();
        }
        error_en(linea, "el objeto %.*s no tiene '%.*s'",
                 (int)ins->clase->nombre->largo, ins->clase->nombre->datos,
                 (int)clave->largo, clave->datos);
    }
    {
        char texto[256];
        texto_de(objeto, texto, sizeof(texto));
        error_en(linea, "no se puede indexar '%s'", texto);
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
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_DICTO) {
        int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
        if (indice.etiqueta != T_OBJ || indice.v.obj->tipo != O_TEXTO)
            error_en(linea, "la clave de un diccionario debe ser texto");
        dicto_poner((Dicto *)objeto.v.obj, (Texto *)indice.v.obj, valor);
        PUSH(valor);
        SIGUIENTE();
    }
    if (objeto.etiqueta == T_OBJ && objeto.v.obj->tipo == O_INSTANCIA) {
        int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
        if (indice.etiqueta != T_OBJ || indice.v.obj->tipo != O_TEXTO)
            error_en(linea, "los objetos solo tienen atributos con nombre");
        dicto_poner(((Instancia *)objeto.v.obj)->campos, (Texto *)indice.v.obj, valor);
        PUSH(valor);
        SIGUIENTE();
    }
    error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
             "solo se puede asignar por índice en listas y diccionarios");
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
L_CREAR_CLASE: {
    uint32_t ci_nombre = LEER_U32();
    uint32_t n = LEER_U32();
    uint32_t *ci_nombres = memoria(sizeof(uint32_t) * (n ? n : 1));
    for (uint32_t i = 0; i < n; i++) ci_nombres[i] = LEER_U32();
    int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
    Valor padre = vm->sp[-1 - (int32_t)n];
    if (padre.etiqueta != T_NULO &&
        !(padre.etiqueta == T_OBJ && padre.v.obj->tipo == O_CLASE))
        error_en(linea, "solo se puede heredar de una clase");
    Clase *cl = nuevo_objeto(sizeof(Clase), O_CLASE);
    cl->nombre = marco->funcion->const_s[ci_nombre];
    cl->padre = padre;
    cl->n_metodos = n;
    cl->nombres_met = memoria(sizeof(Texto *) * (n ? n : 1));
    cl->metodos = memoria(sizeof(Cierre *) * (n ? n : 1));
    for (uint32_t i = 0; i < n; i++) {
        cl->nombres_met[i] = marco->funcion->const_s[ci_nombres[i]];
        cl->metodos[i] = (Cierre *)vm->sp[-((int32_t)n - (int32_t)i)].v.obj;
    }
    vm->bytes_reservados -= sizeof(uint32_t) * (n ? n : 1);
    free(ci_nombres);
    vm->sp -= n + 1;
    PUSH(de_objeto((Obj *)cl));
    SIGUIENTE();
}
L_DEFECTOS: {
    uint32_t minimos = LEER_U32();
    if (vm->marco->n_args < minimos)
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "la función '%.*s' espera %u argumento(s), recibió %u",
                 (int)marco->funcion->nombre->largo, marco->funcion->nombre->datos,
                 minimos, vm->marco->n_args);
    SIGUIENTE();
}
L_SALTAR_SI_HAY_VALOR: {
    uint32_t slot = LEER_U32();
    int32_t relativo = LEER_I32();
    if (!es_sin_valor(base[slot])) ip += relativo;
    SIGUIENTE();
}
L_CELDA: {
    uint32_t slot = LEER_U32();
    base[slot] = de_objeto((Obj *)nueva_celda(base[slot]));
    SIGUIENTE();
}

L_MANEJAR: {
    /* el compilador parcha este hueco con un salto relativo desde la palabra
     * siguiente (parchar(): destino - (hueco + 1)) */
    int32_t relativo = LEER_I32();
    if (vm->n_manejadores >= 64) error_en(0, "demasiados 'intenta' anidados");
    Maneja *m = &vm->manejadores[vm->n_manejadores++];
    m->marco = vm->marco;
    m->sp = vm->sp;
    m->pc = (uint32_t)(ip - marco->funcion->codigo) + (uint32_t)relativo;
    SIGUIENTE();
}
L_FIN_MANEJAR: {
    if (vm->n_manejadores > 0) vm->n_manejadores -= 1;
    SIGUIENTE();
}
L_ERROR_EN: {
    uint32_t slot = LEER_U32();
    base[slot] = de_texto(nuevo_texto(vm->error));
    SIGUIENTE();
}
L_DICT: {
    uint32_t n = LEER_U32();
    Dicto *d = nuevo_dicto();
    Valor *inicio = vm->sp - 2 * (int32_t)n;
    for (uint32_t i = 0; i < n; i++) {
        Valor clave = inicio[2 * i], valor = inicio[2 * i + 1];
        if (clave.etiqueta != T_OBJ || clave.v.obj->tipo != O_TEXTO) {
            ACTUALIZAR_IP();
            error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                     "la clave de un diccionario debe ser texto");
        }
        dicto_poner(d, (Texto *)clave.v.obj, valor);
    }
    vm->sp -= 2 * n;
    PUSH(de_objeto((Obj *)d));
    quizas_recolectar();
    SIGUIENTE();
}
L_ITER_INIT: {
    uint32_t slot = LEER_U32();
    Valor iterable = POP();
    Lista *l = NULL;
    Dicto *dicto_origen = NULL;
    if (iterable.etiqueta == T_OBJ && iterable.v.obj->tipo == O_LISTA) {
        l = (Lista *)iterable.v.obj;
    } else if (iterable.etiqueta == T_OBJ && iterable.v.obj->tipo == O_TEXTO) {
        Texto *t = (Texto *)iterable.v.obj;
        l = nueva_lista(t->largo ? t->largo : 1);
        for (uint32_t i = 0; i < t->largo; i++) lista_agregar(l, de_texto(nuevo_texto_largo(t->datos + i, 1)));
    } else if (iterable.etiqueta == T_OBJ && iterable.v.obj->tipo == O_DICTO) {
        Dicto *d = (Dicto *)iterable.v.obj;
        dicto_origen = d;
        l = nueva_lista(d->largo ? d->largo : 1);
        for (uint32_t i = 0; i < d->largo; i++) lista_agregar(l, de_texto(d->entradas[i].clave));
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
    it->dicto = dicto_origen;
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

L_ITER_NEXT_PAR: {
    uint32_t slot_iter = LEER_U32();
    uint32_t slot_a = LEER_U32();
    uint32_t slot_b = LEER_U32();
    int32_t relativo = LEER_I32();
    Iter *it = (Iter *)base[slot_iter].v.obj;
    if (it->indice >= it->lista->largo) {
        ip = ip + relativo;
        SIGUIENTE();
    }
    uint32_t idx = it->indice++;
    Valor elemento = it->lista->elementos[idx];
    if (it->dicto) {
        base[slot_a] = elemento;  /* la clave (las claves son la secuencia) */
        Valor *v = dicto_buscar(it->dicto, (Texto *)elemento.v.obj);
        base[slot_b] = v ? *v : de_nulo();
    } else {
        base[slot_a] = de_entero((int64_t)idx);
        base[slot_b] = elemento;
    }
    SIGUIENTE();
}
L_ITER_NEXT_PAR_CELDA: {
    uint32_t slot_iter = LEER_U32();
    uint32_t slot_a = LEER_U32();
    uint32_t slot_b = LEER_U32();
    uint32_t mascara = LEER_U32();
    int32_t relativo = LEER_I32();
    Iter *it = (Iter *)base[slot_iter].v.obj;
    if (it->indice >= it->lista->largo) {
        ip = ip + relativo;
        SIGUIENTE();
    }
    uint32_t idx = it->indice++;
    Valor elemento = it->lista->elementos[idx];
    if (it->dicto) {
        base[slot_a] = elemento;
        Valor *v = dicto_buscar(it->dicto, (Texto *)elemento.v.obj);
        base[slot_b] = v ? *v : de_nulo();
    } else {
        base[slot_a] = de_entero((int64_t)idx);
        base[slot_b] = elemento;
    }
    if (mascara & 1) base[slot_a] = de_objeto((Obj *)nueva_celda(base[slot_a]));
    if (mascara & 2) base[slot_b] = de_objeto((Obj *)nueva_celda(base[slot_b]));
    SIGUIENTE();
}
L_DESESTRUCTURAR: {
    uint32_t n = LEER_U32();
    Valor v = POP();
    int linea = (int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1);
    if (v.etiqueta != T_OBJ || v.v.obj->tipo != O_LISTA) {
        char texto[512];
        texto_de(v, texto, sizeof(texto));
        error_en(linea, "la desestructuración '[a, b] = ...' espera una lista, no '%s'", texto);
    }
    Lista *l = (Lista *)v.v.obj;
    if (l->largo != n)
        error_en(linea, "la desestructuración esperaba %u valor(es) y recibió %u", n, l->largo);
    for (uint32_t i = 0; i < n; i++) PUSH(l->elementos[i]);
    SIGUIENTE();
}

L_VERIFICAR_TIPO: {
    Texto *tipo = marco->funcion->const_s[LEER_U32()];
    Texto *nombre = marco->funcion->const_s[LEER_U32()];
    Valor v = vm->sp[-1];
    if (!cumple_tipo(v, tipo)) {
        char valor_txt[512];
        texto_de(v, valor_txt, sizeof(valor_txt));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "la variable '%.*s' es de tipo %.*s y recibió %s ('%s')",
                 (int)nombre->largo, nombre->datos, (int)tipo->largo, tipo->datos,
                 nombre_tipo_jp(v), valor_txt);
    }
    SIGUIENTE();
}
L_VERIFICAR_ARG: {
    uint32_t slot = LEER_U32();
    Texto *tipo = marco->funcion->const_s[LEER_U32()];
    Texto *nombre = marco->funcion->const_s[LEER_U32()];
    Valor v = base[slot];
    if (!es_sin_valor(v) && !cumple_tipo(v, tipo)) {
        char valor_txt[512];
        texto_de(v, valor_txt, sizeof(valor_txt));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "el parámetro '%.*s' de '%.*s' es de tipo %.*s y recibió %s ('%s')",
                 (int)nombre->largo, nombre->datos,
                 (int)marco->funcion->nombre->largo, marco->funcion->nombre->datos,
                 (int)tipo->largo, tipo->datos, nombre_tipo_jp(v), valor_txt);
    }
    SIGUIENTE();
}
L_VERIFICAR_RET: {
    Texto *tipo = marco->funcion->const_s[LEER_U32()];
    Valor v = vm->sp[-1];
    if (!cumple_tipo(v, tipo)) {
        char valor_txt[512];
        texto_de(v, valor_txt, sizeof(valor_txt));
        error_en((int)linea_de((uint32_t)(ip - marco->funcion->codigo) - 1),
                 "la función '%.*s' debe devolver %.*s y devolvió %s ('%s')",
                 (int)marco->funcion->nombre->largo, marco->funcion->nombre->datos,
                 (int)tipo->largo, tipo->datos, nombre_tipo_jp(v), valor_txt);
    }
    SIGUIENTE();
}

L_EXPR_SENT: {
    vm->ultimo_valor = POP();
    SIGUIENTE();
}
L_FIN:
    return;
}

/* El 'intenta' vive aquí fuera del bucle: si algo falla en cualquier punto,
 * longjmp vuelve a este setjmp, se restaura el marco y se reentra al bucle
 * justo en el 'atrapa'. Así el bucle caliente no paga ningún setjmp. */
static void ejecutar(Funcion *principal) {
    /* marco del programa principal */
    Valor *base_principal = vm->sp;
    for (uint32_t i = 0; i < principal->n_slots; i++) *vm->sp++ = de_nulo();
    Marco *marco_principal = vm->marco + 1;
    marco_principal->funcion = principal;
    marco_principal->base = base_principal;
    marco_principal->ip = principal->codigo;
    marco_principal->upvalues = NULL;
    marco_principal->n_upvalues = 0;
    marco_principal->n_manejadores = 0;

    /* marca de agua para el recolector: el marco del programa es el actual */
    vm->marco = marco_principal;
    vm->pc_inicio = 0;
    vm->piso_marco = vm->marcos - 1;
    vm->n_niveles = 0;

    uint32_t nivel = vm->n_niveles;
    vm->niveles[nivel].piso = vm->marcos - 1;
    vm->n_niveles = nivel + 1;

    for (;;) {
        if (setjmp(vm->niveles[nivel].salto) != 0) {
            vm->n_niveles = nivel;
            if (vm->n_manejadores == 0) return;   /* error sin 'intenta' */
            Maneja *m = &vm->manejadores[vm->n_manejadores - 1];
            if (m->marco <= vm->niveles[nivel].piso) return;  /* no puede ser */
            vm->n_manejadores -= 1;
            vm->marco = m->marco;
            vm->sp = m->sp;
            vm->pc_inicio = m->pc;
            vm->piso_marco = vm->niveles[nivel].piso;
            vm->n_niveles = nivel + 1;
            continue;
        }
        bucle(vm->pc_inicio);
        vm->n_niveles = nivel;
        return;
    }
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
    instalar_nativa("sigmoide", 1, nativa_sigmoide);
    instalar_nativa("producto_punto", 2, nativa_producto_punto);
    instalar_nativa("promedio", 1, nativa_promedio);
    instalar_nativa("mediana", 1, nativa_mediana);
    instalar_nativa("norma", 1, nativa_norma);
    instalar_nativa("distancia", 2, nativa_distancia);
    instalar_nativa("softmax", 1, nativa_softmax);
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
    instalar_nativa("claves", 1, nativa_claves);
    instalar_nativa("valores", 1, nativa_valores);
    instalar_nativa("elementos", 1, nativa_elementos);
    instalar_nativa("tiene", 2, nativa_tiene);
    instalar_nativa("separar", -1, nativa_separar);
    instalar_nativa("reemplazar", 3, nativa_reemplazar);
    instalar_nativa("subtexto", -1, nativa_subtexto);
    instalar_nativa("letra", 2, nativa_letra);
    instalar_nativa("empezar_con", 2, nativa_empezar_con);
    instalar_nativa("terminar_con", 2, nativa_terminar_con);
    instalar_nativa("buscar", 2, nativa_buscar);
    instalar_nativa("repetir", 2, nativa_repetir);
    instalar_nativa("indice_de", 2, nativa_indice_de);
    instalar_nativa("insertar", 3, nativa_insertar);
    instalar_nativa("quitar", -1, nativa_quitar);
    instalar_nativa("eliminar", 2, nativa_eliminar);
    instalar_nativa("esperar", -1, nativa_esperar);
    instalar_nativa("leer_archivo", 1, nativa_leer_archivo);
    instalar_nativa("escribir_archivo", 2, nativa_escribir_archivo);
    instalar_nativa("agregar_archivo", 2, nativa_agregar_archivo);
    instalar_nativa("existe_archivo", 1, nativa_existe_archivo);
    instalar_nativa("tamano_archivo", 1, nativa_tamano_archivo);
    instalar_nativa("lista_archivos", 1, nativa_lista_archivos);
    instalar_nativa("json_leer", 1, nativa_json_leer);
    instalar_nativa("json_texto", 1, nativa_json_texto);
    instalar_nativa("mapear", 2, nativa_mapear);
    instalar_nativa("filtrar", 2, nativa_filtrar);
    instalar_nativa("reducir", -1, nativa_reducir);
    instalar_nativa("para_cada", 2, nativa_para_cada);
    instalar_nativa("ordenar", -1, nativa_ordenar);

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
