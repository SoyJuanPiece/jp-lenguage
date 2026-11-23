/* Compilador de JP a bytecode (.jpb): port de `jp/compilar_nativo.py`.
 *
 * Genera exactamente el mismo blob que el compilador de Python: mismo orden
 * de funciones, mismos slots, mismas celdas y upvalues, misma tabla de
 * cadenas. `herramientas/jpb_paridad.py` compara ambos blobs byte a byte.
 *
 * El formato lo consume `motor-c/jpvm.c`; su encabezado lo documenta.
 */

#include "compilar.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "parser.h"

/* ------------------------------------------------------------- opcodes */

enum {
    OP_NOP = 0,
    OP_CONST_I = 1, OP_CONST_D = 2, OP_CONST_S = 3,
    OP_NULO = 4, OP_VERDADERO = 5, OP_FALSO = 6,
    OP_GET_LOCAL = 7, OP_SET_LOCAL = 8, OP_GET_CELDA = 9, OP_SET_CELDA = 10,
    OP_GET_GLOBAL = 11, OP_SET_GLOBAL = 12, OP_DECL_GLOBAL = 13,
    OP_GET_UPVAL = 14, OP_SET_UPVAL = 15,
    OP_POP = 16, OP_DUP = 17,
    OP_SUMA = 18, OP_RESTA = 19, OP_MULT = 20, OP_DIV = 21, OP_MOD = 22,
    OP_POT = 23, OP_NEG = 24, OP_NO = 25, OP_IGUAL = 26, OP_DIF = 27,
    OP_MENOR = 28, OP_MAYOR = 29, OP_MENOR_IG = 30, OP_MAYOR_IG = 31,
    OP_SALTO = 32, OP_SALTO_FALSO = 33, OP_SALTO_FALSO_MANTENER = 34,
    OP_SALTO_VERDAD_MANTENER = 35, OP_IMPRIMIR = 36, OP_LLAMAR = 37,
    OP_RETORNAR = 38, OP_RETORNAR_NULO = 39, OP_LISTA = 40, OP_RANGO = 41,
    OP_INDICE = 42, OP_INDICE_ASIG = 43, OP_CIERRE = 44, OP_CELDA = 45,
    OP_ITER_INIT = 46, OP_ITER_NEXT = 47, OP_ITER_NEXT_CELDA = 48,
    OP_EXPR_SENT = 49, OP_FIN = 50, OP_DICT = 51, OP_MANEJAR = 52,
    OP_FIN_MANEJAR = 53, OP_ERROR_EN = 54, OP_SALTO_NO_NULO_MANTENER = 55,
    OP_CREAR_CLASE = 56, OP_DEFECTOS = 57, OP_SALTAR_SI_HAY_VALOR = 58,
    OP_ITER_NEXT_PAR = 59, OP_ITER_NEXT_PAR_CELDA = 60, OP_DESESTRUCTURAR = 61,
    OP_VERIFICAR_TIPO = 62, OP_VERIFICAR_ARG = 63, OP_VERIFICAR_RET = 64,
    OP_IMPORTAR = 65, OP_LANZAR = 66, OP_RELANZAR = 67,
};

#define VERSION_FORMATO 2

/* ------------------------------------------------- conjunto de nombres */

typedef struct {
    const char **datos;
    int n;
    int capacidad;
} Nombres;

static int nombres_tiene(const Nombres *conjunto, const char *nombre) {
    if (!nombre) return 0;
    for (int i = 0; i < conjunto->n; i++) {
        if (strcmp(conjunto->datos[i], nombre) == 0) return 1;
    }
    return 0;
}

static void nombres_agregar(Nombres *conjunto, const char *nombre) {
    if (!nombre || nombres_tiene(conjunto, nombre)) return;
    if (conjunto->n >= conjunto->capacidad) {
        int nueva = conjunto->capacidad ? conjunto->capacidad * 2 : 8;
        const char **datos = (const char **)realloc(conjunto->datos, (size_t)nueva * sizeof(char *));
        if (!datos) return;
        conjunto->datos = datos;
        conjunto->capacidad = nueva;
    }
    conjunto->datos[conjunto->n++] = nombre;
}

static void nombres_liberar(Nombres *conjunto) {
    free(conjunto->datos);
    conjunto->datos = NULL;
    conjunto->n = 0;
    conjunto->capacidad = 0;
}

/* ------------------------------------------------------- estructuras */

typedef struct {
    const char *nombre;
    int slot;
} EntradaAmbito;

typedef struct {
    EntradaAmbito *datos;
    int n;
    int capacidad;
} Ambito;

typedef struct {
    int es_local;
    int indice;
} Upvalue;

typedef struct {
    const char *nombre;
    int aridad;
    int modulo;

    int *palabras;
    int n_palabras;
    int capacidad_palabras;

    int *lineas_pc;
    int *lineas_numero;
    int n_lineas;
    int capacidad_lineas;

    int slots;
    unsigned char *celdas;
    int capacidad_celdas;

    Upvalue *upvalues;
    int n_upvalues;
    int capacidad_upvalues;

    const char **const_s;
    int n_const_s;
    int capacidad_const_s;

    Ambito *ambitos;
    int n_ambitos;
    int capacidad_ambitos;

    Nombres capturadas;
} Funcion;

typedef struct {
    const char *nombre;
    int indice;
} Global;

typedef struct {
    const char *nombre;
    const char *fuente;
    const char *directorio;
    int funcion;
    Global *globales;
    int n_globales;
    int capacidad_globales;
    Nombres declarados;
} Modulo;

typedef struct {
    int inicio;
    int *saltos;
    int n_saltos;
    int capacidad_saltos;
    int marca_intentos;
} Iterador;

typedef struct {
    JpArena arena;
    Funcion **funciones;
    int n_funciones;
    int capacidad_funciones;
    Funcion **pila;
    int n_pila;
    int capacidad_pila;
    Modulo *modulos;
    int n_modulos;
    int capacidad_modulos;
    int modulo_actual;
    const char **ids_rutas;
    int *ids_indices;
    int n_ids;
    int capacidad_ids;
    const char **importando;
    int n_importando;
    int capacidad_importando;
    Funcion **principales;
    int n_principales;
    int capacidad_principales;
    Iterador *iteradores;
    int n_iteradores;
    int capacidad_iteradores;
    const JpNodo **intentos;
    int n_intentos;
    int capacidad_intentos;
    JpPrograma **programas;
    int n_programas;
    int capacidad_programas;
    const char *retorno_esperado;
    const char *directorio_base;
    const char *fuente;
    const char *nombre_programa;
    char *error;
    size_t error_largo;
    int fallo;
} Compilador;

static void fallar(Compilador *c, int linea, const char *formato, ...) {
    if (c->fallo) return;
    c->fallo = 1;
    if (!c->error || !c->error_largo) return;
    char mensaje[512];
    va_list args;
    va_start(args, formato);
    vsnprintf(mensaje, sizeof mensaje, formato, args);
    va_end(args);
    snprintf(c->error, c->error_largo, "%s|%d|0", mensaje, linea);
}

static void *reservar(Compilador *c, size_t bytes) { return jp_arena_reservar(&c->arena, bytes); }

static char *copia_texto(Compilador *c, const char *texto) {
    return texto ? jp_arena_texto(&c->arena, texto) : NULL;
}

/* ------------------------------------------------------------ emisión */

static void palabra(Funcion *f, int valor) {
    if (f->n_palabras >= f->capacidad_palabras) {
        int nueva = f->capacidad_palabras ? f->capacidad_palabras * 2 : 64;
        int *datos = (int *)realloc(f->palabras, (size_t)nueva * sizeof(int));
        if (!datos) return;
        f->palabras = datos;
        f->capacidad_palabras = nueva;
    }
    f->palabras[f->n_palabras++] = valor;
}

static void anotar_linea(Funcion *f, int pc, int linea) {
    if (f->n_lineas >= f->capacidad_lineas) {
        int nueva = f->capacidad_lineas ? f->capacidad_lineas * 2 : 32;
        int *pcs = (int *)realloc(f->lineas_pc, (size_t)nueva * sizeof(int));
        if (!pcs) return;
        f->lineas_pc = pcs;
        int *numeros = (int *)realloc(f->lineas_numero, (size_t)nueva * sizeof(int));
        if (!numeros) return;
        f->lineas_numero = numeros;
        f->capacidad_lineas = nueva;
    }
    f->lineas_pc[f->n_lineas] = pc;
    f->lineas_numero[f->n_lineas] = linea;
    f->n_lineas++;
}

static int cadena_constante(Funcion *f, const char *texto) {
    if (!texto) texto = "";
    for (int i = 0; i < f->n_const_s; i++) {
        if (strcmp(f->const_s[i], texto) == 0) return i;
    }
    if (f->n_const_s >= f->capacidad_const_s) {
        int nueva = f->capacidad_const_s ? f->capacidad_const_s * 2 : 8;
        const char **datos = (const char **)realloc(f->const_s, (size_t)nueva * sizeof(char *));
        if (!datos) return 0;
        f->const_s = datos;
        f->capacidad_const_s = nueva;
    }
    f->const_s[f->n_const_s] = texto;
    return f->n_const_s++;
}

/* Emite `op` con los operandos que describe `formato`:
 *   i=int  q=int64 (dos palabras)  d=double (dos palabras)  s=cadena */
static int emitir_formato(Funcion *f, int op, int linea, const char *formato, ...) {
    int pc = f->n_palabras;
    anotar_linea(f, pc, linea);
    palabra(f, op);
    va_list args;
    va_start(args, formato);
    for (const char *p = formato; *p; p++) {
        if (*p == 'i') {
            palabra(f, va_arg(args, int));
        } else if (*p == 's') {
            palabra(f, cadena_constante(f, va_arg(args, const char *)));
        } else if (*p == 'q') {
            unsigned long long crudo = (unsigned long long)va_arg(args, long long);
            palabra(f, (int)(crudo & 0xFFFFFFFFull));
            palabra(f, (int)((crudo >> 32) & 0xFFFFFFFFull));
        } else if (*p == 'd') {
            double valor = va_arg(args, double);
            unsigned long long crudo = 0;
            memcpy(&crudo, &valor, sizeof crudo);
            palabra(f, (int)(crudo & 0xFFFFFFFFull));
            palabra(f, (int)((crudo >> 32) & 0xFFFFFFFFull));
        }
    }
    va_end(args);
    return pc;
}

static int emitir(Funcion *f, int op, int linea) { return emitir_formato(f, op, linea, ""); }
static int emitir_i(Funcion *f, int op, int a, int linea) { return emitir_formato(f, op, linea, "i", a); }
static int emitir_ii(Funcion *f, int op, int a, int b, int linea) {
    return emitir_formato(f, op, linea, "ii", a, b);
}
static int emitir_iii(Funcion *f, int op, int a, int b, int c3, int linea) {
    return emitir_formato(f, op, linea, "iii", a, b, c3);
}
static int emitir_iiii(Funcion *f, int op, int a, int b, int c3, int d, int linea) {
    return emitir_formato(f, op, linea, "iiii", a, b, c3, d);
}
static int emitir_iiiii(Funcion *f, int op, int a, int b, int c3, int d, int e, int linea) {
    return emitir_formato(f, op, linea, "iiiii", a, b, c3, d, e);
}
static int emitir_s(Funcion *f, int op, const char *texto, int linea) {
    return emitir_formato(f, op, linea, "s", texto);
}
static int emitir_ss(Funcion *f, int op, const char *a, const char *b, int linea) {
    return emitir_formato(f, op, linea, "ss", a, b);
}
static int emitir_iss(Funcion *f, int op, int a, const char *b, const char *c3, int linea) {
    return emitir_formato(f, op, linea, "iss", a, b, c3);
}

static int emitir_salto(Funcion *f, int op, int linea) {
    emitir_i(f, op, 0, linea);
    return f->n_palabras - 1;
}

static void parchar(Funcion *f, int hueco, int destino) {
    f->palabras[hueco] = destino - (hueco + 1);
}

static void parchar_aqui(Funcion *f, int hueco) { parchar(f, hueco, f->n_palabras); }

static void salto_a(Funcion *f, int destino, int linea) {
    emitir_i(f, OP_SALTO, 0, linea);
    parchar(f, f->n_palabras - 1, destino);
}

/* ------------------------------------------------------------- ámbitos */

static void asegurar_celdas(Funcion *f) {
    if (f->slots <= f->capacidad_celdas) return;
    int nueva = f->capacidad_celdas ? f->capacidad_celdas : 8;
    while (nueva < f->slots) nueva *= 2;
    unsigned char *datos = (unsigned char *)realloc(f->celdas, (size_t)nueva);
    if (!datos) return;
    memset(datos + f->capacidad_celdas, 0, (size_t)(nueva - f->capacidad_celdas));
    f->celdas = datos;
    f->capacidad_celdas = nueva;
}

static void abrir_ambito(Funcion *f) {
    if (f->n_ambitos >= f->capacidad_ambitos) {
        int nueva = f->capacidad_ambitos ? f->capacidad_ambitos * 2 : 4;
        Ambito *datos = (Ambito *)realloc(f->ambitos, (size_t)nueva * sizeof(Ambito));
        if (!datos) return;
        memset(datos + f->capacidad_ambitos, 0, (size_t)(nueva - f->capacidad_ambitos) * sizeof(Ambito));
        f->ambitos = datos;
        f->capacidad_ambitos = nueva;
    }
    f->ambitos[f->n_ambitos].n = 0;
    f->n_ambitos++;
}

static void cerrar_ambito(Funcion *f) {
    if (f->n_ambitos > 1) f->n_ambitos--;
}

static int declarar(Funcion *f, const char *nombre) {
    int slot = f->slots++;
    asegurar_celdas(f);
    f->celdas[slot] = (unsigned char)(nombres_tiene(&f->capturadas, nombre) ? 1 : 0);
    Ambito *ambito = &f->ambitos[f->n_ambitos - 1];
    if (ambito->n >= ambito->capacidad) {
        int nueva = ambito->capacidad ? ambito->capacidad * 2 : 8;
        EntradaAmbito *datos = (EntradaAmbito *)realloc(ambito->datos, (size_t)nueva * sizeof(EntradaAmbito));
        if (!datos) return slot;
        ambito->datos = datos;
        ambito->capacidad = nueva;
    }
    ambito->datos[ambito->n].nombre = nombre;
    ambito->datos[ambito->n].slot = slot;
    ambito->n++;
    return slot;
}

static int reservar_slot(Funcion *f) {
    int slot = f->slots++;
    asegurar_celdas(f);
    f->celdas[slot] = 0;
    return slot;
}

static int buscar_local(const Funcion *f, const char *nombre, int *slot, int *es_celda) {
    for (int i = f->n_ambitos - 1; i >= 0; i--) {
        const Ambito *ambito = &f->ambitos[i];
        for (int j = ambito->n - 1; j >= 0; j--) {
            if (strcmp(ambito->datos[j].nombre, nombre) == 0) {
                *slot = ambito->datos[j].slot;
                *es_celda = f->celdas[*slot];
                return 1;
            }
        }
    }
    return 0;
}

/* --------------------------------------------- recorrido y análisis del AST */

static void empujar(const JpNodo *nodo, const JpNodo ***pila, int *n, int *capacidad) {
    if (!nodo) return;
    if (*n >= *capacidad) {
        int nueva = *capacidad ? *capacidad * 2 : 32;
        const JpNodo **datos = (const JpNodo **)realloc((void *)*pila, (size_t)nueva * sizeof(JpNodo *));
        if (!datos) return;
        *pila = datos;
        *capacidad = nueva;
    }
    (*pila)[(*n)++] = nodo;
}

static void empujar_hijos(const JpNodo *nodo, const JpNodo ***pila, int *n, int *capacidad) {
    if (!nodo) return;
    for (int i = 0; i < nodo->hijos.n; i++) empujar(nodo->hijos.datos[i], pila, n, capacidad);
    switch (nodo->tipo) {
        case N_EXPRESION: empujar(nodo->expresion, pila, n, capacidad); break;
        case N_DECLARACION_VAR: empujar(nodo->inicializador, pila, n, capacidad); break;
        case N_DECLARACION_LISTA: empujar(nodo->inicializador, pila, n, capacidad); break;
        case N_ASIGNACION: empujar(nodo->valor, pila, n, capacidad); break;
        case N_ASIGNACION_LISTA: empujar(nodo->valor, pila, n, capacidad); break;
        case N_ASIGNAR_INDICE:
            empujar(nodo->objeto, pila, n, capacidad);
            empujar(nodo->indice, pila, n, capacidad);
            empujar(nodo->valor, pila, n, capacidad);
            break;
        case N_BINARIO:
            empujar(nodo->izq, pila, n, capacidad);
            empujar(nodo->der, pila, n, capacidad);
            break;
        case N_UNARIO: empujar(nodo->operando, pila, n, capacidad); break;
        case N_LLAMADA: empujar(nodo->callee, pila, n, capacidad); break;
        case N_INDICE:
            empujar(nodo->objeto, pila, n, capacidad);
            empujar(nodo->indice, pila, n, capacidad);
            break;
        case N_RANGO:
            empujar(nodo->izq, pila, n, capacidad);
            empujar(nodo->der, pila, n, capacidad);
            empujar(nodo->paso, pila, n, capacidad);
            break;
        case N_FUNCION:
            for (int i = 0; i < nodo->params.n; i++) empujar(nodo->params.datos[i]->valor, pila, n, capacidad);
            empujar(nodo->cuerpo, pila, n, capacidad);
            break;
        case N_PARAMETRO: empujar(nodo->valor, pila, n, capacidad); break;
        case N_RETORNA: empujar(nodo->valor, pila, n, capacidad); break;
        case N_LANZAR: empujar(nodo->expresion, pila, n, capacidad); break;
        case N_SI:
            empujar(nodo->condicion, pila, n, capacidad);
            empujar(nodo->entonces, pila, n, capacidad);
            empujar(nodo->sino, pila, n, capacidad);
            break;
        case N_MIENTRAS:
            empujar(nodo->condicion, pila, n, capacidad);
            empujar(nodo->cuerpo, pila, n, capacidad);
            break;
        case N_PARA:
            empujar(nodo->iterable, pila, n, capacidad);
            empujar(nodo->cuerpo, pila, n, capacidad);
            break;
        case N_ELEGIR:
            empujar(nodo->expresion, pila, n, capacidad);
            empujar(nodo->sino, pila, n, capacidad);
            break;
        case N_CASO: empujar(nodo->cuerpo, pila, n, capacidad); break;
        case N_INTENTAR:
            empujar(nodo->cuerpo, pila, n, capacidad);
            empujar(nodo->captura, pila, n, capacidad);
            empujar(nodo->finalmente, pila, n, capacidad);
            break;
        default:
            break;
    }
}

typedef void (*Visitante)(const JpNodo *nodo, void *contexto);

static void caminar(const JpNodo *raiz, Visitante visitar, void *contexto) {
    if (!raiz) return;
    const JpNodo **pila = NULL;
    int n = 0, capacidad = 0;
    empujar(raiz, &pila, &n, &capacidad);
    while (n > 0) {
        const JpNodo *actual = pila[--n];
        visitar(actual, contexto);
        empujar_hijos(actual, &pila, &n, &capacidad);
    }
    free((void *)pila);
}

static void nombres_declarados(const JpNodo *nodo, Nombres *destino) {
    const JpNodo **pila = NULL;
    int n = 0, capacidad = 0;
    empujar_hijos(nodo, &pila, &n, &capacidad);
    while (n > 0) {
        const JpNodo *actual = pila[--n];
        if (actual->tipo == N_FUNCION) continue;
        if (actual->tipo == N_DECLARACION_VAR) {
            nombres_agregar(destino, actual->nombre);
        } else if (actual->tipo == N_DECLARACION_LISTA) {
            for (int i = 0; i < actual->hijos.n; i++) nombres_agregar(destino, actual->hijos.datos[i]->texto);
        } else if (actual->tipo == N_PARA) {
            nombres_agregar(destino, actual->nombre);
            nombres_agregar(destino, actual->texto);
        } else if (actual->tipo == N_INTENTAR) {
            nombres_agregar(destino, actual->texto);
        } else if (actual->tipo == N_BLOQUE || actual->tipo == N_PROGRAMA) {
            for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
            continue;
        }
        empujar_hijos(actual, &pila, &n, &capacidad);
    }
    free((void *)pila);
}

static void nombres_usados(const JpNodo *nodo, Nombres *destino) {
    const JpNodo **pila = NULL;
    int n = 0, capacidad = 0;
    empujar(nodo, &pila, &n, &capacidad);
    while (n > 0) {
        const JpNodo *actual = pila[--n];
        if (!actual) continue;
        switch (actual->tipo) {
            case N_VARIABLE:
                nombres_agregar(destino, actual->nombre);
                break;
            case N_ASIGNACION:
                nombres_agregar(destino, actual->nombre);
                empujar(actual->valor, &pila, &n, &capacidad);
                break;
            case N_DECLARACION_VAR:
                nombres_agregar(destino, actual->nombre);
                empujar(actual->inicializador, &pila, &n, &capacidad);
                break;
            case N_ASIGNAR_INDICE:
                empujar(actual->objeto, &pila, &n, &capacidad);
                empujar(actual->indice, &pila, &n, &capacidad);
                empujar(actual->valor, &pila, &n, &capacidad);
                break;
            case N_BINARIO:
                empujar(actual->izq, &pila, &n, &capacidad);
                empujar(actual->der, &pila, &n, &capacidad);
                break;
            case N_UNARIO:
                empujar(actual->operando, &pila, &n, &capacidad);
                break;
            case N_LLAMADA:
                empujar(actual->callee, &pila, &n, &capacidad);
                for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
                break;
            case N_INDICE:
                empujar(actual->objeto, &pila, &n, &capacidad);
                empujar(actual->indice, &pila, &n, &capacidad);
                break;
            case N_LISTA:
            case N_DICCIONARIO:
            case N_INTERPOLACION:
                for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
                break;
            case N_RANGO:
                empujar(actual->izq, &pila, &n, &capacidad);
                empujar(actual->der, &pila, &n, &capacidad);
                empujar(actual->paso, &pila, &n, &capacidad);
                break;
            case N_EXPRESION:
                empujar(actual->expresion, &pila, &n, &capacidad);
                break;
            case N_BLOQUE:
            case N_PROGRAMA:
                for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
                break;
            case N_SI:
                empujar(actual->condicion, &pila, &n, &capacidad);
                empujar(actual->entonces, &pila, &n, &capacidad);
                empujar(actual->sino, &pila, &n, &capacidad);
                break;
            case N_MIENTRAS:
                empujar(actual->condicion, &pila, &n, &capacidad);
                empujar(actual->cuerpo, &pila, &n, &capacidad);
                break;
            case N_PARA:
                empujar(actual->iterable, &pila, &n, &capacidad);
                empujar(actual->cuerpo, &pila, &n, &capacidad);
                nombres_agregar(destino, actual->nombre);
                break;
            case N_ELEGIR:
                empujar(actual->expresion, &pila, &n, &capacidad);
                for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
                empujar(actual->sino, &pila, &n, &capacidad);
                break;
            case N_CASO:
                for (int i = 0; i < actual->hijos.n; i++) empujar(actual->hijos.datos[i], &pila, &n, &capacidad);
                empujar(actual->cuerpo, &pila, &n, &capacidad);
                break;
            case N_INTENTAR:
                empujar(actual->cuerpo, &pila, &n, &capacidad);
                empujar(actual->captura, &pila, &n, &capacidad);
                nombres_agregar(destino, actual->texto);
                break;
            case N_FUNCION:
                empujar(actual->cuerpo, &pila, &n, &capacidad);
                break;
            case N_RETORNA:
                empujar(actual->valor, &pila, &n, &capacidad);
                break;
            default:
                break;
        }
    }
    free((void *)pila);
}

/* --------------------------------------------------- ayudas del compilador */

static Funcion *actual(Compilador *c) { return c->pila[c->n_pila - 1]; }
static Modulo *modulo_de(Compilador *c) { return &c->modulos[c->modulo_actual]; }

static int es_principal(const Compilador *c, const Funcion *f) {
    for (int i = 0; i < c->n_principales; i++) {
        if (c->principales[i] == f) return 1;
    }
    return 0;
}

static int es_nivel_global(Compilador *c, Funcion *f) {
    return es_principal(c, f) && f->n_ambitos == 1;
}

static int global_de(Compilador *c, const char *nombre) {
    Modulo *modulo = modulo_de(c);
    for (int i = 0; i < modulo->n_globales; i++) {
        if (strcmp(modulo->globales[i].nombre, nombre) == 0) return modulo->globales[i].indice;
    }
    if (modulo->n_globales >= modulo->capacidad_globales) {
        int nueva = modulo->capacidad_globales ? modulo->capacidad_globales * 2 : 8;
        Global *datos = (Global *)realloc(modulo->globales, (size_t)nueva * sizeof(Global));
        if (!datos) return 0;
        modulo->globales = datos;
        modulo->capacidad_globales = nueva;
    }
    int indice = modulo->n_globales;
    modulo->globales[modulo->n_globales].nombre = nombre;
    modulo->globales[modulo->n_globales].indice = indice;
    modulo->n_globales++;
    return indice;
}

static Funcion *nueva_funcion(Compilador *c, const char *nombre, int aridad, const Nombres *capturadas) {
    Funcion *f = (Funcion *)reservar(c, sizeof(Funcion));
    if (!f) return NULL;
    f->nombre = copia_texto(c, nombre ? nombre : "");
    f->aridad = aridad;
    if (capturadas) {
        for (int i = 0; i < capturadas->n; i++) nombres_agregar(&f->capturadas, capturadas->datos[i]);
    }
    abrir_ambito(f);
    return f;
}

static int crear_upvalue(Compilador *c, Funcion *funcion, const char *nombre) {
    int posicion = -1;
    for (int i = 0; i < c->n_pila; i++) {
        if (c->pila[i] == funcion) {
            posicion = i;
            break;
        }
    }
    if (posicion <= 0) {
        fallar(c, 0, "no encuentro la variable '%s' para la closure", nombre);
        return 0;
    }
    Funcion *padre = c->pila[posicion - 1];
    int slot = 0, es_celda = 0;
    Upvalue descripcion;
    if (buscar_local(padre, nombre, &slot, &es_celda)) {
        padre->celdas[slot] = 1; /* seguro: ya venía premarcado */
        descripcion.es_local = 1;
        descripcion.indice = slot;
    } else {
        descripcion.es_local = 0;
        descripcion.indice = crear_upvalue(c, padre, nombre);
    }
    for (int i = 0; i < funcion->n_upvalues; i++) {
        if (funcion->upvalues[i].es_local == descripcion.es_local &&
            funcion->upvalues[i].indice == descripcion.indice) {
            return i;
        }
    }
    if (funcion->n_upvalues >= funcion->capacidad_upvalues) {
        int nueva = funcion->capacidad_upvalues ? funcion->capacidad_upvalues * 2 : 8;
        Upvalue *datos = (Upvalue *)realloc(funcion->upvalues, (size_t)nueva * sizeof(Upvalue));
        if (!datos) return 0;
        funcion->upvalues = datos;
        funcion->capacidad_upvalues = nueva;
    }
    funcion->upvalues[funcion->n_upvalues] = descripcion;
    return funcion->n_upvalues++;
}

/* 0 = local, 1 = celda, 2 = upval, 3 = global */
static int resolver(Compilador *c, const char *nombre, int *indice) {
    for (int nivel = 0; nivel < c->n_pila; nivel++) {
        Funcion *funcion = c->pila[c->n_pila - 1 - nivel];
        int slot = 0, es_celda = 0;
        if (!buscar_local(funcion, nombre, &slot, &es_celda)) continue;
        if (nivel == 0) {
            *indice = slot;
            return es_celda ? 1 : 0;
        }
        *indice = crear_upvalue(c, c->pila[c->n_pila - 1], nombre);
        return 2;
    }
    *indice = global_de(c, nombre);
    return 3;
}

/* ------------------------------ intentos e iteradores */

static void empujar_intento(Compilador *c, const JpNodo *finalmente) {
    if (c->n_intentos >= c->capacidad_intentos) {
        int nueva = c->capacidad_intentos ? c->capacidad_intentos * 2 : 8;
        const JpNodo **datos = (const JpNodo **)realloc((void *)c->intentos, (size_t)nueva * sizeof(JpNodo *));
        if (!datos) return;
        c->intentos = datos;
        c->capacidad_intentos = nueva;
    }
    c->intentos[c->n_intentos++] = finalmente;
}

static void empujar_iterador(Compilador *c, int inicio, int marca_intentos) {
    if (c->n_iteradores >= c->capacidad_iteradores) {
        int nueva = c->capacidad_iteradores ? c->capacidad_iteradores * 2 : 4;
        Iterador *datos = (Iterador *)realloc(c->iteradores, (size_t)nueva * sizeof(Iterador));
        if (!datos) return;
        memset(datos + c->capacidad_iteradores, 0, (size_t)(nueva - c->capacidad_iteradores) * sizeof(Iterador));
        c->iteradores = datos;
        c->capacidad_iteradores = nueva;
    }
    Iterador *iterador = &c->iteradores[c->n_iteradores++];
    memset(iterador, 0, sizeof *iterador);
    iterador->inicio = inicio;
    iterador->marca_intentos = marca_intentos;
}

static void saltos_romper_agregar(Iterador *iterador, int hueco) {
    if (iterador->n_saltos >= iterador->capacidad_saltos) {
        int nueva = iterador->capacidad_saltos ? iterador->capacidad_saltos * 2 : 4;
        int *datos = (int *)realloc(iterador->saltos, (size_t)nueva * sizeof(int));
        if (!datos) return;
        iterador->saltos = datos;
        iterador->capacidad_saltos = nueva;
    }
    iterador->saltos[iterador->n_saltos++] = hueco;
}

/* Cierra los 'intenta' abiertos sobre `hasta`, ejecutando su 'finalmente'. */
static void emitir_cierre_intentos(Compilador *c, int hasta, int linea);

/* ------------------------------ cierre de intentos */

static int compilar_bloque(Compilador *c, const JpNodos *sentencias, int ambito_nuevo);
static int compilar_sentencia(Compilador *c, const JpNodo *nodo);
static int compilar_expresion(Compilador *c, const JpNodo *nodo);
static int compilar_funcion(Compilador *c, const JpNodo *nodo, int *indice_salida);

static void emitir_cierre_intentos(Compilador *c, int hasta, int linea) {
    Funcion *f = actual(c);
    int total = c->n_intentos - hasta;
    if (total <= 0) return;
    const JpNodo **objetivos = (const JpNodo **)malloc((size_t)total * sizeof(JpNodo *));
    if (!objetivos) return;
    for (int i = 0; i < total; i++) objetivos[i] = c->intentos[hasta + i];
    c->n_intentos = hasta;
    for (int i = total - 1; i >= 0; i--) {
        emitir(f, OP_FIN_MANEJAR, linea);
        if (objetivos[i]) compilar_bloque(c, &objetivos[i]->hijos, 1);
    }
    for (int i = 0; i < total; i++) empujar_intento(c, objetivos[i]);
    free((void *)objetivos);
}

/* ------------------------------ usados / capturadas */

static void usados_de_funcion(const JpNodo *funcion, Nombres *destino);

static void visitar_variables(const JpNodo *nodo, void *contexto) {
    Nombres *usados = (Nombres *)contexto;
    if (nodo->tipo == N_VARIABLE) nombres_agregar(usados, nodo->nombre);
    else if (nodo->tipo == N_FUNCION) usados_de_funcion(nodo, usados);
}

static void visitar_funciones_usadas(const JpNodo *nodo, void *contexto) {
    Nombres *usados = (Nombres *)contexto;
    if (nodo->tipo == N_FUNCION) usados_de_funcion(nodo, usados);
}

static void usados_de_funcion(const JpNodo *funcion, Nombres *destino) {
    nombres_usados(funcion->cuerpo, destino);
    for (int i = 0; i < funcion->params.n; i++) {
        const JpNodo *defecto = funcion->params.datos[i]->valor;
        if (defecto) caminar(defecto, visitar_variables, destino);
    }
}

static void capturadas_por_anidadas(const JpNodo *cuerpo, Nombres *destino) {
    if (!cuerpo) return;
    Nombres aqui = {0};
    nombres_declarados(cuerpo, &aqui);
    Nombres usados = {0};
    caminar(cuerpo, visitar_funciones_usadas, &usados);
    for (int i = 0; i < usados.n; i++) {
        if (nombres_tiene(&aqui, usados.datos[i])) nombres_agregar(destino, usados.datos[i]);
    }
    nombres_liberar(&aqui);
    nombres_liberar(&usados);
}

/* ------------------------------ utilidades de rutas */

static const char *unir_ruta(Compilador *c, const char *base, const char *ruta) {
    if (!ruta) ruta = "";
    int absoluta = ruta[0] == '/' || ruta[0] == '\\' ||
                   (ruta[0] && ruta[1] == ':');
    if (absoluta || !base || !*base || (strcmp(base, ".") == 0)) {
        return copia_texto(c, ruta);
    }
    size_t largo_base = strlen(base);
    size_t largo_ruta = strlen(ruta);
    char *unida = (char *)jp_arena_reservar(&c->arena, largo_base + largo_ruta + 2);
    if (!unida) return NULL;
    memcpy(unida, base, largo_base);
    size_t usado = largo_base;
    if (unida[usado - 1] != '/' && unida[usado - 1] != '\\') unida[usado++] = '/';
    memcpy(unida + usado, ruta, largo_ruta);
    unida[usado + largo_ruta] = '\0';
    return unida;
}

static const char *direccionario_de(Compilador *c, const char *ruta) {
    if (!ruta || !*ruta) return copia_texto(c, ".");
    size_t corte = 0;
    for (size_t i = 0; ruta[i]; i++) {
        if (ruta[i] == '/' || ruta[i] == '\\') corte = i;
    }
    if (corte == 0) return copia_texto(c, ".");
    return jp_arena_copiar(&c->arena, ruta, corte);
}

static const char *nombre_base(const char *ruta) {
    const char *ultimo = ruta;
    for (const char *p = ruta; *p; p++) {
        if (*p == '/' || *p == '\\') ultimo = p + 1;
    }
    return ultimo;
}

static char *leer_texto(const char *ruta, size_t *largo) {
    FILE *archivo = fopen(ruta, "rb");
    if (!archivo) return NULL;
    if (fseek(archivo, 0, SEEK_END) != 0) {
        fclose(archivo);
        return NULL;
    }
    long tamano = ftell(archivo);
    if (tamano < 0) {
        fclose(archivo);
        return NULL;
    }
    rewind(archivo);
    char *datos = (char *)malloc((size_t)tamano + 1);
    if (!datos) {
        fclose(archivo);
        return NULL;
    }
    size_t leidos = fread(datos, 1, (size_t)tamano, archivo);
    fclose(archivo);
    datos[leidos] = '\0';
    *largo = leidos;
    return datos;
}

/* ------------------------------ declaraciones */

static int ligar_nombre(Compilador *c, const char *nombre, int linea) {
    Funcion *f = actual(c);
    if (es_nivel_global(c, f)) {
        nombres_agregar(&modulo_de(c)->declarados, nombre);
        emitir_i(f, OP_DECL_GLOBAL, global_de(c, nombre), linea);
        emitir(f, OP_POP, linea);
        return !c->fallo;
    }
    int slot = declarar(f, nombre);
    emitir_i(f, OP_SET_LOCAL, slot, linea);
    if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
    emitir(f, OP_POP, linea);
    return !c->fallo;
}

static int guardar_desestructurado(Compilador *c, const JpNodos *nombres, int linea, int declarar_nuevos) {
    Funcion *f = actual(c);
    for (int i = nombres->n - 1; i >= 0; i--) {
        const char *nombre = nombres->datos[i]->texto;
        if (declarar_nuevos) {
            if (es_nivel_global(c, f)) {
                nombres_agregar(&modulo_de(c)->declarados, nombre);
                emitir_i(f, OP_DECL_GLOBAL, global_de(c, nombre), linea);
                emitir(f, OP_POP, linea);
                continue;
            }
            int slot = declarar(f, nombre);
            emitir_i(f, OP_SET_LOCAL, slot, linea);
            if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
            emitir(f, OP_POP, linea);
            continue;
        }
        int indice = 0;
        int donde = resolver(c, nombre, &indice);
        if (donde == 0) emitir_i(f, OP_SET_LOCAL, indice, linea);
        else if (donde == 1) emitir_i(f, OP_SET_CELDA, indice, linea);
        else if (donde == 2) emitir_i(f, OP_SET_UPVAL, indice, linea);
        else emitir_i(f, OP_SET_GLOBAL, indice, linea);
        emitir(f, OP_POP, linea);
    }
    return !c->fallo;
}

static int declarar_variable(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int linea = nodo->linea;
    if (es_nivel_global(c, f)) {
        if (nodo->inicializador) {
            if (!compilar_expresion(c, nodo->inicializador)) return 0;
        } else {
            emitir(f, OP_NULO, linea);
        }
        if (nodo->tipo_anotado) {
            emitir_ss(f, OP_VERIFICAR_TIPO, nodo->tipo_anotado, nodo->nombre, linea);
        }
        nombres_agregar(&modulo_de(c)->declarados, nodo->nombre);
        emitir_i(f, OP_DECL_GLOBAL, global_de(c, nodo->nombre), linea);
        emitir(f, OP_POP, linea);
        return !c->fallo;
    }
    int slot = declarar(f, nodo->nombre);
    if (nodo->inicializador) {
        if (!compilar_expresion(c, nodo->inicializador)) return 0;
    } else {
        emitir(f, OP_NULO, linea);
    }
    if (nodo->tipo_anotado) {
        emitir_ss(f, OP_VERIFICAR_TIPO, nodo->tipo_anotado, nodo->nombre, linea);
    }
    emitir_i(f, OP_SET_LOCAL, slot, linea);
    if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
    emitir(f, OP_POP, linea);
    return !c->fallo;
}

static int declarar_funcion(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int indice = 0;
    if (!compilar_funcion(c, nodo, &indice)) return 0;
    int linea = nodo->linea;
    if (es_nivel_global(c, f)) {
        nombres_agregar(&modulo_de(c)->declarados, nodo->nombre);
        emitir_i(f, OP_CIERRE, indice, linea);
        emitir_i(f, OP_DECL_GLOBAL, global_de(c, nodo->nombre), linea);
        emitir(f, OP_POP, linea);
        return !c->fallo;
    }
    int slot = declarar(f, nodo->nombre);
    emitir_i(f, OP_CIERRE, indice, linea);
    emitir_i(f, OP_SET_LOCAL, slot, linea);
    if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
    emitir(f, OP_POP, linea);
    return !c->fallo;
}

static int declarar_clase(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int linea = nodo->linea;
    int total = nodo->hijos.n;
    int *indices = (int *)malloc((size_t)(total ? total : 1) * sizeof(int));
    if (!indices) return 0;
    for (int i = 0; i < total; i++) {
        const JpNodo *metodo = nodo->hijos.datos[i];
        JpNodo *adaptado = jp_nodo_nuevo(&c->arena, N_FUNCION, metodo->linea);
        if (!adaptado) {
            free(indices);
            return 0;
        }
        adaptado->nombre = copia_texto(c, metodo->nombre);
        adaptado->texto = copia_texto(c, metodo->texto);
        adaptado->cuerpo = metodo->cuerpo;
        JpNodo *este = jp_nodo_nuevo(&c->arena, N_PARAMETRO, metodo->linea);
        if (!este) {
            free(indices);
            return 0;
        }
        este->nombre = copia_texto(c, "este");
        jp_nodos_agregar(&c->arena, &adaptado->params, este);
        for (int j = 0; j < metodo->params.n; j++) {
            jp_nodos_agregar(&c->arena, &adaptado->params, metodo->params.datos[j]);
        }
        if (!compilar_funcion(c, adaptado, &indices[i])) {
            free(indices);
            return 0;
        }
    }
    if (nodo->texto) {
        JpNodo *padre = jp_nodo_nuevo(&c->arena, N_VARIABLE, linea);
        if (padre) {
            padre->nombre = copia_texto(c, nodo->texto);
            if (!compilar_expresion(c, padre)) {
                free(indices);
                return 0;
            }
        }
    } else {
        emitir(f, OP_NULO, linea);
    }
    for (int i = 0; i < total; i++) emitir_i(f, OP_CIERRE, indices[i], linea);
    int pc = f->n_palabras;
    anotar_linea(f, pc, linea);
    palabra(f, OP_CREAR_CLASE);
    palabra(f, cadena_constante(f, nodo->nombre));
    palabra(f, total);
    for (int i = 0; i < total; i++) palabra(f, cadena_constante(f, nodo->hijos.datos[i]->nombre));
    if (es_nivel_global(c, f)) {
        nombres_agregar(&modulo_de(c)->declarados, nodo->nombre);
        emitir_i(f, OP_DECL_GLOBAL, global_de(c, nodo->nombre), linea);
        emitir(f, OP_POP, linea);
    } else {
        int slot = declarar(f, nodo->nombre);
        emitir_i(f, OP_SET_LOCAL, slot, linea);
        if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
        emitir(f, OP_POP, linea);
    }
    free(indices);
    return !c->fallo;
}

/* ------------------------------ bucles */

static int compilar_para(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int linea = nodo->linea;
    int slot_iter = reservar_slot(f);
    if (!compilar_expresion(c, nodo->iterable)) return 0;
    emitir_i(f, OP_ITER_INIT, slot_iter, linea);
    int inicio = f->n_palabras;
    empujar_iterador(c, inicio, c->n_intentos);
    abrir_ambito(f);
    int slot_var = declarar(f, nodo->nombre);
    if (nodo->texto) {
        int slot_var2 = declarar(f, nodo->texto);
        if (f->celdas[slot_var] || f->celdas[slot_var2]) {
            int mascara = (f->celdas[slot_var] ? 1 : 0) | (f->celdas[slot_var2] ? 2 : 0);
            emitir_iiiii(f, OP_ITER_NEXT_PAR_CELDA, slot_iter, slot_var, slot_var2, mascara, 0, linea);
        } else {
            emitir_iiii(f, OP_ITER_NEXT_PAR, slot_iter, slot_var, slot_var2, 0, linea);
        }
    } else {
        int op = f->celdas[slot_var] ? OP_ITER_NEXT_CELDA : OP_ITER_NEXT;
        emitir_iii(f, op, slot_iter, slot_var, 0, linea);
    }
    int hueco = f->n_palabras - 1;
    if (!compilar_bloque(c, &nodo->cuerpo->hijos, 0)) return 0;
    Iterador *iterador = c->n_iteradores ? &c->iteradores[c->n_iteradores - 1] : NULL;
    int inicio_guardado = iterador ? iterador->inicio : inicio;
    int n_saltos = iterador ? iterador->n_saltos : 0;
    int *saltos = NULL;
    if (n_saltos) {
        saltos = (int *)malloc((size_t)n_saltos * sizeof(int));
        for (int i = 0; i < n_saltos; i++) saltos[i] = iterador->saltos[i];
    }
    if (c->n_iteradores > 0) {
        free(c->iteradores[c->n_iteradores - 1].saltos);
        c->n_iteradores--;
    }
    salto_a(f, inicio_guardado, linea);
    parchar_aqui(f, hueco);
    for (int i = 0; i < n_saltos; i++) parchar_aqui(f, saltos[i]);
    free(saltos);
    cerrar_ambito(f);
    return !c->fallo;
}

/* ------------------------------ módulos */

static int compilar_modulo(Compilador *c, const JpNodo *nodo) {
    int linea = nodo->linea;
    const char *ruta_texto = nodo->texto ? nodo->texto : "";
    if (ruta_texto[0] == '@') {
        fallar(c, linea, "no se pudo resolver '%s': los paquetes con @ aún no están en el motor en C",
               ruta_texto);
        return -1;
    }
    const char *base = modulo_de(c)->directorio ? modulo_de(c)->directorio : c->directorio_base;
    const char *ruta = unir_ruta(c, base, ruta_texto);
    if (!ruta) {
        fallar(c, linea, "sin memoria al resolver '%s'", ruta_texto);
        return -1;
    }
    for (int i = 0; i < c->n_importando; i++) {
        if (strcmp(c->importando[i], ruta) == 0) {
            fallar(c, linea, "importación circular detectada: '%s' ya se está importando", ruta_texto);
            return -1;
        }
    }
    for (int i = 0; i < c->n_ids; i++) {
        if (strcmp(c->ids_rutas[i], ruta) == 0) return c->ids_indices[i];
    }
    size_t largo_fuente = 0;
    char *fuente_modulo = leer_texto(ruta, &largo_fuente);
    if (!fuente_modulo) {
        fallar(c, linea, "no se encontró el módulo '%s' (buscado en %s)", ruta_texto, ruta);
        return -1;
    }
    JpPrograma *programa = (JpPrograma *)calloc(1, sizeof(JpPrograma));
    char error_parseo[512];
    if (!programa || !jp_parsear(fuente_modulo, largo_fuente, programa, error_parseo, sizeof error_parseo)) {
        fallar(c, linea, "error en el módulo '%s': %s", ruta_texto, error_parseo);
        free(fuente_modulo);
        free(programa);
        return -1;
    }
    if (c->n_programas >= c->capacidad_programas) {
        int nueva = c->capacidad_programas ? c->capacidad_programas * 2 : 4;
        JpPrograma **datos = (JpPrograma **)realloc((void *)c->programas, (size_t)nueva * sizeof(JpPrograma *));
        if (!datos) {
            jp_programa_liberar(programa);
            free(programa);
            free(fuente_modulo);
            return -1;
        }
        c->programas = datos;
        c->capacidad_programas = nueva;
    }
    c->programas[c->n_programas++] = programa;

    if (c->n_modulos >= c->capacidad_modulos) {
        int nueva = c->capacidad_modulos ? c->capacidad_modulos * 2 : 4;
        Modulo *datos = (Modulo *)realloc(c->modulos, (size_t)nueva * sizeof(Modulo));
        if (!datos) {
            free(fuente_modulo);
            return -1;
        }
        memset(datos + c->capacidad_modulos, 0, (size_t)(nueva - c->capacidad_modulos) * sizeof(Modulo));
        c->modulos = datos;
        c->capacidad_modulos = nueva;
    }
    int indice = c->n_modulos;
    Modulo *estado = &c->modulos[c->n_modulos++];
    memset(estado, 0, sizeof *estado);
    estado->nombre = copia_texto(c, ruta_texto);
    estado->fuente = copia_texto(c, fuente_modulo);
    free(fuente_modulo);
    estado->directorio = direccionario_de(c, ruta);

    if (c->n_ids >= c->capacidad_ids) {
        int nueva = c->capacidad_ids ? c->capacidad_ids * 2 : 4;
        const char **rutas = (const char **)realloc((void *)c->ids_rutas, (size_t)nueva * sizeof(char *));
        if (!rutas) return -1;
        c->ids_rutas = rutas;
        int *indices = (int *)realloc(c->ids_indices, (size_t)nueva * sizeof(int));
        if (!indices) return -1;
        c->ids_indices = indices;
        c->capacidad_ids = nueva;
    }
    c->ids_rutas[c->n_ids] = ruta;
    c->ids_indices[c->n_ids] = indice;
    c->n_ids++;

    Nombres capturadas = {0};
    capturadas_por_anidadas(programa->raiz, &capturadas);
    char nombre_funcion[512];
    snprintf(nombre_funcion, sizeof nombre_funcion, "<módulo %s>", nombre_base(ruta));
    Funcion *funcion = nueva_funcion(c, nombre_funcion, 0, &capturadas);
    nombres_liberar(&capturadas);
    if (!funcion) return -1;
    funcion->modulo = indice;
    estado->funcion = c->n_funciones;
    if (c->n_funciones >= c->capacidad_funciones) {
        int nueva = c->capacidad_funciones ? c->capacidad_funciones * 2 : 8;
        Funcion **datos = (Funcion **)realloc((void *)c->funciones, (size_t)nueva * sizeof(Funcion *));
        if (!datos) return -1;
        c->funciones = datos;
        c->capacidad_funciones = nueva;
    }
    c->funciones[c->n_funciones++] = funcion;
    if (c->n_principales >= c->capacidad_principales) {
        int nueva = c->capacidad_principales ? c->capacidad_principales * 2 : 4;
        Funcion **datos = (Funcion **)realloc((void *)c->principales, (size_t)nueva * sizeof(Funcion *));
        if (!datos) return -1;
        c->principales = datos;
        c->capacidad_principales = nueva;
    }
    c->principales[c->n_principales++] = funcion;

    int anterior = c->modulo_actual;
    c->modulo_actual = indice;
    if (c->n_importando >= c->capacidad_importando) {
        int nueva = c->capacidad_importando ? c->capacidad_importando * 2 : 4;
        const char **datos = (const char **)realloc((void *)c->importando, (size_t)nueva * sizeof(char *));
        if (!datos) return -1;
        c->importando = datos;
        c->capacidad_importando = nueva;
    }
    c->importando[c->n_importando++] = ruta;
    c->pila[c->n_pila++] = funcion;
    int ok = compilar_bloque(c, &programa->raiz->hijos, 0);
    c->n_pila--;
    c->n_importando--;
    c->modulo_actual = anterior;
    if (!ok) return -1;
    emitir(funcion, OP_RETORNAR_NULO, 0);
    return indice;
}

static int sentencia_importar(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int linea = nodo->linea;
    int indice = compilar_modulo(c, nodo);
    if (indice < 0) return 0;
    Modulo *modulo = &c->modulos[indice];
    emitir_i(f, OP_IMPORTAR, indice, linea);
    if (nodo->nombre) return ligar_nombre(c, nodo->nombre, linea);
    for (int i = 0; i < modulo->n_globales; i++) {
        const char *nombre = modulo->globales[i].nombre;
        if (!nombres_tiene(&modulo->declarados, nombre)) continue;
        emitir(f, OP_DUP, linea);
        emitir_s(f, OP_CONST_S, nombre, linea);
        emitir(f, OP_INDICE, linea);
        if (!ligar_nombre(c, nombre, linea)) return 0;
    }
    emitir(f, OP_POP, linea);
    return !c->fallo;
}
/* ------------------------------ sentencias */

static int compilar_sentencia(Compilador *c, const JpNodo *nodo) {
    if (!nodo) return 0;
    Funcion *f = actual(c);
    int linea = nodo->linea;

    switch (nodo->tipo) {
        case N_PROGRAMA:
            return compilar_bloque(c, &nodo->hijos, 0);

        case N_DECLARACION_VAR:
            return declarar_variable(c, nodo);

        case N_FUNCION:
            return declarar_funcion(c, nodo);

        case N_IMPORTAR:
            return sentencia_importar(c, nodo);

        case N_CLASE:
            return declarar_clase(c, nodo);

        case N_LANZAR:
            if (!compilar_expresion(c, nodo->expresion)) return 0;
            emitir(f, OP_LANZAR, linea);
            return !c->fallo;

        case N_DECLARACION_LISTA:
            if (!compilar_expresion(c, nodo->inicializador)) return 0;
            emitir_i(f, OP_DESESTRUCTURAR, nodo->hijos.n, linea);
            return guardar_desestructurado(c, &nodo->hijos, linea, 1);

        case N_EXPRESION:
            if (!compilar_expresion(c, nodo->expresion)) return 0;
            emitir(f, OP_EXPR_SENT, linea);
            return !c->fallo;

        case N_BLOQUE:
            return compilar_bloque(c, &nodo->hijos, 1);

        case N_SI: {
            if (!compilar_expresion(c, nodo->condicion)) return 0;
            int salto_sino = emitir_salto(f, OP_SALTO_FALSO, linea);
            if (!compilar_bloque(c, &nodo->entonces->hijos, 1)) return 0;
            if (nodo->sino) {
                int salto_fin = emitir_salto(f, OP_SALTO, linea);
                parchar_aqui(f, salto_sino);
                if (!compilar_bloque(c, &nodo->sino->hijos, 1)) return 0;
                parchar_aqui(f, salto_fin);
            } else {
                parchar_aqui(f, salto_sino);
            }
            return !c->fallo;
        }

        case N_MIENTRAS: {
            int inicio = f->n_palabras;
            if (!compilar_expresion(c, nodo->condicion)) return 0;
            int salto_fin = emitir_salto(f, OP_SALTO_FALSO, linea);
            empujar_iterador(c, inicio, c->n_intentos);
            if (!compilar_bloque(c, &nodo->cuerpo->hijos, 1)) return 0;
            Iterador *iterador = c->n_iteradores ? &c->iteradores[c->n_iteradores - 1] : NULL;
            int inicio_guardado = iterador ? iterador->inicio : inicio;
            int n_saltos = iterador ? iterador->n_saltos : 0;
            int *saltos = NULL;
            if (n_saltos) {
                saltos = (int *)malloc((size_t)n_saltos * sizeof(int));
                for (int i = 0; i < n_saltos; i++) saltos[i] = iterador->saltos[i];
            }
            if (c->n_iteradores > 0) {
                free(c->iteradores[c->n_iteradores - 1].saltos);
                c->n_iteradores--;
            }
            salto_a(f, inicio_guardado, linea);
            parchar_aqui(f, salto_fin);
            for (int i = 0; i < n_saltos; i++) parchar_aqui(f, saltos[i]);
            free(saltos);
            return !c->fallo;
        }

        case N_PARA:
            return compilar_para(c, nodo);

        case N_RETORNA:
            if (nodo->valor) {
                if (!compilar_expresion(c, nodo->valor)) return 0;
            } else if (c->retorno_esperado) {
                emitir(f, OP_NULO, linea);
            }
            emitir_cierre_intentos(c, 0, linea);
            if (c->retorno_esperado) {
                emitir_s(f, OP_VERIFICAR_RET, c->retorno_esperado, linea);
                emitir(f, OP_RETORNAR, linea);
            } else if (nodo->valor) {
                emitir(f, OP_RETORNAR, linea);
            } else {
                emitir(f, OP_RETORNAR_NULO, linea);
            }
            return !c->fallo;

        case N_ROMPER: {
            if (!c->n_iteradores) {
                fallar(c, linea, "'romper' fuera de un bucle");
                return 0;
            }
            Iterador *iterador = &c->iteradores[c->n_iteradores - 1];
            emitir_cierre_intentos(c, iterador->marca_intentos, linea);
            int hueco = emitir_salto(f, OP_SALTO, linea);
            saltos_romper_agregar(iterador, hueco);
            return !c->fallo;
        }

        case N_CONTINUAR: {
            if (!c->n_iteradores) {
                fallar(c, linea, "'continuar' fuera de un bucle");
                return 0;
            }
            Iterador *iterador = &c->iteradores[c->n_iteradores - 1];
            emitir_cierre_intentos(c, iterador->marca_intentos, linea);
            salto_a(f, iterador->inicio, linea);
            return !c->fallo;
        }

        case N_DICCIONARIO: {
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
            }
            emitir_i(f, OP_DICT, nodo->hijos.n / 2, linea);
            return !c->fallo;
        }

        case N_ELEGIR: {
            if (!compilar_expresion(c, nodo->expresion)) return 0;
            int reservado = reservar_slot(f);
            emitir_i(f, OP_SET_LOCAL, reservado, linea);
            emitir(f, OP_POP, linea);
            int *saltos_fin = NULL;
            int n_saltos = 0, capacidad_saltos = 0;
            for (int i = 0; i < nodo->hijos.n; i++) {
                const JpNodo *caso = nodo->hijos.datos[i];
                int salto_cuerpo = 0;
                for (int j = 0; j < caso->hijos.n; j++) {
                    emitir_i(f, OP_GET_LOCAL, reservado, linea);
                    if (!compilar_expresion(c, caso->hijos.datos[j])) {
                        free(saltos_fin);
                        return 0;
                    }
                    emitir(f, OP_IGUAL, linea);
                    int hueco = emitir_salto(f, OP_SALTO_FALSO, linea);
                    if (j < caso->hijos.n - 1) continue;
                    salto_cuerpo = hueco;
                }
                if (!compilar_bloque(c, &caso->cuerpo->hijos, 1)) {
                    free(saltos_fin);
                    return 0;
                }
                if (n_saltos >= capacidad_saltos) {
                    int nueva = capacidad_saltos ? capacidad_saltos * 2 : 4;
                    int *datos = (int *)realloc(saltos_fin, (size_t)nueva * sizeof(int));
                    if (!datos) {
                        free(saltos_fin);
                        return 0;
                    }
                    saltos_fin = datos;
                    capacidad_saltos = nueva;
                }
                saltos_fin[n_saltos++] = emitir_salto(f, OP_SALTO, linea);
                parchar_aqui(f, salto_cuerpo);
            }
            if (nodo->sino && !compilar_bloque(c, &nodo->sino->hijos, 1)) {
                free(saltos_fin);
                return 0;
            }
            for (int i = 0; i < n_saltos; i++) parchar_aqui(f, saltos_fin[i]);
            free(saltos_fin);
            return !c->fallo;
        }

        case N_INTENTAR: {
            emitir_i(f, OP_MANEJAR, 0, linea);
            int hueco = f->n_palabras - 1;
            empujar_intento(c, nodo->finalmente);
            if (!compilar_bloque(c, &nodo->cuerpo->hijos, 1)) return 0;
            if (c->n_intentos > 0) c->n_intentos--;
            emitir(f, OP_FIN_MANEJAR, linea);
            if (nodo->finalmente && !compilar_bloque(c, &nodo->finalmente->hijos, 1)) return 0;
            int al_fin = emitir_salto(f, OP_SALTO, linea);
            parchar(f, hueco, f->n_palabras);
            if (!nodo->captura) {
                if (nodo->finalmente && !compilar_bloque(c, &nodo->finalmente->hijos, 1)) return 0;
                emitir(f, OP_RELANZAR, linea);
            } else {
                abrir_ambito(f);
                if (nodo->texto) {
                    int slot = declarar(f, nodo->texto);
                    emitir_i(f, OP_ERROR_EN, slot, linea);
                    if (f->celdas[slot]) emitir_i(f, OP_CELDA, slot, linea);
                }
                int hueco2 = -1;
                if (nodo->finalmente) {
                    emitir_i(f, OP_MANEJAR, 0, linea);
                    hueco2 = f->n_palabras - 1;
                    empujar_intento(c, nodo->finalmente);
                }
                if (!compilar_bloque(c, &nodo->captura->hijos, 0)) return 0;
                cerrar_ambito(f);
                if (nodo->finalmente) {
                    if (c->n_intentos > 0) c->n_intentos--;
                    emitir(f, OP_FIN_MANEJAR, linea);
                    if (!compilar_bloque(c, &nodo->finalmente->hijos, 1)) return 0;
                    int al_fin2 = emitir_salto(f, OP_SALTO, linea);
                    parchar(f, hueco2, f->n_palabras);
                    if (!compilar_bloque(c, &nodo->finalmente->hijos, 1)) return 0;
                    emitir(f, OP_RELANZAR, linea);
                    parchar_aqui(f, al_fin2);
                }
            }
            parchar_aqui(f, al_fin);
            return !c->fallo;
        }

        default:
            fallar(c, linea, "sentencia no soportada por el compilador en C (%d)", (int)nodo->tipo);
            return 0;
    }
}

/* ------------------------------ expresiones */

static int compilar_binario(Compilador *c, const JpNodo *nodo) {
    Funcion *f = actual(c);
    int linea = nodo->linea;
    const char *operador = nodo->texto ? nodo->texto : "";

    if (strcmp(operador, "y") == 0) {
        if (!compilar_expresion(c, nodo->izq)) return 0;
        int hueco = emitir_salto(f, OP_SALTO_FALSO_MANTENER, linea);
        emitir(f, OP_POP, linea);
        if (!compilar_expresion(c, nodo->der)) return 0;
        parchar_aqui(f, hueco);
        return !c->fallo;
    }
    if (strcmp(operador, "??") == 0) {
        if (!compilar_expresion(c, nodo->izq)) return 0;
        int hueco = emitir_salto(f, OP_SALTO_NO_NULO_MANTENER, linea);
        emitir(f, OP_POP, linea);
        if (!compilar_expresion(c, nodo->der)) return 0;
        parchar_aqui(f, hueco);
        return !c->fallo;
    }
    if (strcmp(operador, "o") == 0) {
        if (!compilar_expresion(c, nodo->izq)) return 0;
        int hueco = emitir_salto(f, OP_SALTO_VERDAD_MANTENER, linea);
        emitir(f, OP_POP, linea);
        if (!compilar_expresion(c, nodo->der)) return 0;
        parchar_aqui(f, hueco);
        return !c->fallo;
    }

    if (!compilar_expresion(c, nodo->izq)) return 0;
    if (!compilar_expresion(c, nodo->der)) return 0;

    int op = -1;
    if (strcmp(operador, "+") == 0) op = OP_SUMA;
    else if (strcmp(operador, "-") == 0) op = OP_RESTA;
    else if (strcmp(operador, "*") == 0) op = OP_MULT;
    else if (strcmp(operador, "/") == 0) op = OP_DIV;
    else if (strcmp(operador, "%") == 0) op = OP_MOD;
    else if (strcmp(operador, "**") == 0) op = OP_POT;
    else if (strcmp(operador, "==") == 0) op = OP_IGUAL;
    else if (strcmp(operador, "!=") == 0) op = OP_DIF;
    else if (strcmp(operador, "<") == 0) op = OP_MENOR;
    else if (strcmp(operador, ">") == 0) op = OP_MAYOR;
    else if (strcmp(operador, "<=") == 0) op = OP_MENOR_IG;
    else if (strcmp(operador, ">=") == 0) op = OP_MAYOR_IG;
    if (op < 0) {
        fallar(c, linea, "operador desconocido: %s", operador);
        return 0;
    }
    emitir(f, op, linea);
    return !c->fallo;
}

static int compilar_expresion(Compilador *c, const JpNodo *nodo) {
    if (!nodo) return 0;
    Funcion *f = actual(c);
    int linea = nodo->linea;

    switch (nodo->tipo) {
        case N_NUMERO:
            if (nodo->es_entero) emitir_formato(f, OP_CONST_I, linea, "q", (long long)nodo->entero);
            else emitir_formato(f, OP_CONST_D, linea, "d", nodo->decimal);
            return !c->fallo;

        case N_CADENA:
            emitir_s(f, OP_CONST_S, nodo->texto, linea);
            return !c->fallo;

        case N_BOOLEANO:
            emitir(f, nodo->booleano ? OP_VERDADERO : OP_FALSO, linea);
            return !c->fallo;

        case N_NULO:
            emitir(f, OP_NULO, linea);
            return !c->fallo;

        case N_VARIABLE: {
            int indice = 0;
            int donde = resolver(c, nodo->nombre, &indice);
            if (donde == 0) emitir_i(f, OP_GET_LOCAL, indice, linea);
            else if (donde == 1) emitir_i(f, OP_GET_CELDA, indice, linea);
            else if (donde == 2) emitir_i(f, OP_GET_UPVAL, indice, linea);
            else emitir_i(f, OP_GET_GLOBAL, indice, linea);
            return !c->fallo;
        }

        case N_ASIGNACION: {
            if (!compilar_expresion(c, nodo->valor)) return 0;
            int indice = 0;
            int donde = resolver(c, nodo->nombre, &indice);
            if (donde == 0) emitir_i(f, OP_SET_LOCAL, indice, linea);
            else if (donde == 1) emitir_i(f, OP_SET_CELDA, indice, linea);
            else if (donde == 2) emitir_i(f, OP_SET_UPVAL, indice, linea);
            else emitir_i(f, OP_SET_GLOBAL, indice, linea);
            return !c->fallo;
        }

        case N_BINARIO:
            return compilar_binario(c, nodo);

        case N_UNARIO:
            if (!compilar_expresion(c, nodo->operando)) return 0;
            if (nodo->texto && strcmp(nodo->texto, "-") == 0) emitir(f, OP_NEG, linea);
            else if (nodo->texto && strcmp(nodo->texto, "no") == 0) emitir(f, OP_NO, linea);
            else {
                fallar(c, linea, "operador unario desconocido: %s", nodo->texto ? nodo->texto : "");
                return 0;
            }
            return !c->fallo;

        case N_LLAMADA: {
            if (nodo->seguro) {
                if (!compilar_expresion(c, nodo->callee)) return 0;
                int a_cont = emitir_salto(f, OP_SALTO_NO_NULO_MANTENER, linea);
                int al_fin = emitir_salto(f, OP_SALTO, linea);
                parchar_aqui(f, a_cont);
                for (int i = 0; i < nodo->hijos.n; i++) {
                    if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
                }
                emitir_i(f, OP_LLAMAR, nodo->hijos.n, linea);
                parchar_aqui(f, al_fin);
                return !c->fallo;
            }
            if (!compilar_expresion(c, nodo->callee)) return 0;
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
            }
            emitir_i(f, OP_LLAMAR, nodo->hijos.n, linea);
            return !c->fallo;
        }

        case N_INDICE:
            if (nodo->seguro) {
                if (!compilar_expresion(c, nodo->objeto)) return 0;
                int a_cont = emitir_salto(f, OP_SALTO_NO_NULO_MANTENER, linea);
                int al_fin = emitir_salto(f, OP_SALTO, linea);
                parchar_aqui(f, a_cont);
                if (!compilar_expresion(c, nodo->indice)) return 0;
                emitir(f, OP_INDICE, linea);
                parchar_aqui(f, al_fin);
                return !c->fallo;
            }
            if (!compilar_expresion(c, nodo->objeto)) return 0;
            if (!compilar_expresion(c, nodo->indice)) return 0;
            emitir(f, OP_INDICE, linea);
            return !c->fallo;

        case N_LISTA:
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
            }
            emitir_i(f, OP_LISTA, nodo->hijos.n, linea);
            return !c->fallo;

        case N_RANGO:
            if (!compilar_expresion(c, nodo->izq)) return 0;
            if (!compilar_expresion(c, nodo->der)) return 0;
            if (!nodo->paso) {
                emitir_i(f, OP_RANGO, 0, linea);
            } else {
                if (!compilar_expresion(c, nodo->paso)) return 0;
                emitir_i(f, OP_RANGO, 1, linea);
            }
            return !c->fallo;

        case N_ASIGNAR_INDICE:
            if (!compilar_expresion(c, nodo->objeto)) return 0;
            if (!compilar_expresion(c, nodo->indice)) return 0;
            if (!compilar_expresion(c, nodo->valor)) return 0;
            emitir(f, OP_INDICE_ASIG, linea);
            return !c->fallo;

        case N_FUNCION: {
            int indice = 0;
            if (!compilar_funcion(c, nodo, &indice)) return 0;
            emitir_i(f, OP_CIERRE, indice, linea);
            return !c->fallo;
        }

        case N_ASIGNACION_LISTA:
            if (!compilar_expresion(c, nodo->valor)) return 0;
            emitir(f, OP_DUP, linea);
            emitir_i(f, OP_DESESTRUCTURAR, nodo->hijos.n, linea);
            return guardar_desestructurado(c, &nodo->hijos, linea, 0);

        case N_DICCIONARIO:
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
            }
            emitir_i(f, OP_DICT, nodo->hijos.n / 2, linea);
            return !c->fallo;

        case N_INTERPOLACION:
            if (nodo->hijos.n == 0) {
                emitir_s(f, OP_CONST_S, "", linea);
                return !c->fallo;
            }
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (!compilar_expresion(c, nodo->hijos.datos[i])) return 0;
                if (i) emitir(f, OP_SUMA, linea);
            }
            return !c->fallo;

        default:
            fallar(c, linea, "expresión no soportada por el compilador en C (%d)", (int)nodo->tipo);
            return 0;
    }
}

/* ------------------------------ funciones */

static int compilar_funcion(Compilador *c, const JpNodo *nodo, int *indice_salida) {
    Nombres usados = {0};
    caminar(nodo->cuerpo, visitar_funciones_usadas, &usados);
    for (int i = 0; i < nodo->params.n; i++) {
        const JpNodo *defecto = nodo->params.datos[i]->valor;
        if (defecto) caminar(defecto, visitar_funciones_usadas, &usados);
    }
    Nombres capturadas = {0};
    capturadas_por_anidadas(nodo->cuerpo, &capturadas);
    for (int i = 0; i < nodo->params.n; i++) {
        const char *nombre = nodo->params.datos[i]->nombre;
        if (nombres_tiene(&usados, nombre)) nombres_agregar(&capturadas, nombre);
    }
    nombres_liberar(&usados);

    const char *nombre = (nodo->nombre && nodo->nombre[0]) ? nodo->nombre : "<anónima>";
    Funcion *funcion = nueva_funcion(c, nombre, nodo->params.n, &capturadas);
    nombres_liberar(&capturadas);
    if (!funcion) return 0;
    funcion->modulo = c->modulo_actual;
    for (int i = 0; i < nodo->params.n; i++) declarar(funcion, nodo->params.datos[i]->nombre);

    if (c->n_funciones >= c->capacidad_funciones) {
        int nueva = c->capacidad_funciones ? c->capacidad_funciones * 2 : 8;
        Funcion **datos = (Funcion **)realloc((void *)c->funciones, (size_t)nueva * sizeof(Funcion *));
        if (!datos) return 0;
        c->funciones = datos;
        c->capacidad_funciones = nueva;
    }
    int indice = c->n_funciones;
    c->funciones[c->n_funciones++] = funcion;

    if (c->n_pila >= c->capacidad_pila) {
        int nueva = c->capacidad_pila ? c->capacidad_pila * 2 : 8;
        Funcion **datos = (Funcion **)realloc((void *)c->pila, (size_t)nueva * sizeof(Funcion *));
        if (!datos) return 0;
        c->pila = datos;
        c->capacidad_pila = nueva;
    }
    c->pila[c->n_pila++] = funcion;

    int tiene_defectos = 0;
    for (int i = 0; i < nodo->params.n; i++) {
        if (nodo->params.datos[i]->valor) tiene_defectos = 1;
    }
    if (tiene_defectos) {
        int requeridos = 0;
        for (int i = 0; i < nodo->params.n; i++) {
            if (!nodo->params.datos[i]->valor) requeridos++;
        }
        emitir_i(funcion, OP_DEFECTOS, requeridos, nodo->linea);
        for (int i = 0; i < nodo->params.n; i++) {
            const JpNodo *defecto = nodo->params.datos[i]->valor;
            if (!defecto) continue;
            emitir_ii(funcion, OP_SALTAR_SI_HAY_VALOR, i, 0, nodo->linea);
            int hueco = funcion->n_palabras - 1;
            if (!compilar_expresion(c, defecto)) return 0;
            emitir_i(funcion, OP_SET_LOCAL, i, nodo->linea);
            emitir(funcion, OP_POP, nodo->linea);
            parchar_aqui(funcion, hueco);
        }
    }
    for (int i = 0; i < nodo->params.n; i++) {
        const JpNodo *parametro = nodo->params.datos[i];
        if (parametro->tipo_anotado) {
            emitir_iss(funcion, OP_VERIFICAR_ARG, i, parametro->tipo_anotado, parametro->nombre,
                       nodo->linea);
        }
    }
    for (int slot = 0; slot < nodo->params.n; slot++) {
        if (funcion->celdas[slot]) emitir_i(funcion, OP_CELDA, slot, nodo->linea);
    }

    const char *retorno_anterior = c->retorno_esperado;
    c->retorno_esperado = nodo->texto;
    int ok = compilar_bloque(c, &nodo->cuerpo->hijos, 1);
    c->retorno_esperado = retorno_anterior;
    if (!ok) return 0;

    if (nodo->texto) {
        emitir(funcion, OP_NULO, nodo->linea);
        emitir_s(funcion, OP_VERIFICAR_RET, nodo->texto, nodo->linea);
        emitir(funcion, OP_RETORNAR, nodo->linea);
    } else {
        emitir(funcion, OP_RETORNAR_NULO, nodo->linea);
    }
    c->n_pila--;
    *indice_salida = indice;
    return 1;
}

static int compilar_bloque(Compilador *c, const JpNodos *sentencias, int ambito_nuevo) {
    Funcion *f = actual(c);
    if (ambito_nuevo) abrir_ambito(f);
    for (int i = 0; i < sentencias->n; i++) {
        if (!compilar_sentencia(c, sentencias->datos[i])) return 0;
    }
    if (ambito_nuevo) cerrar_ambito(f);
    return !c->fallo;
}

/* ------------------------------ empaquetado .jpb */

typedef struct {
    unsigned char *datos;
    size_t n;
    size_t capacidad;
} Bolsa;

static void bolsa_bytes(Bolsa *b, const void *datos, size_t n) {
    if (b->n + n > b->capacidad) {
        size_t nueva = b->capacidad ? b->capacidad : 1024;
        while (nueva < b->n + n) nueva *= 2;
        unsigned char *ampliada = (unsigned char *)realloc(b->datos, nueva);
        if (!ampliada) return;
        b->datos = ampliada;
        b->capacidad = nueva;
    }
    memcpy(b->datos + b->n, datos, n);
    b->n += n;
}

static void bolsa_u32(Bolsa *b, unsigned valor) {
    unsigned char bytes[4] = {
        (unsigned char)(valor & 0xFF),
        (unsigned char)((valor >> 8) & 0xFF),
        (unsigned char)((valor >> 16) & 0xFF),
        (unsigned char)((valor >> 24) & 0xFF),
    };
    bolsa_bytes(b, bytes, 4);
}

typedef struct {
    const char **textos;
    int n;
    int capacidad;
} TablaCadenas;

static int tabla_indice(TablaCadenas *tabla, const char *texto) {
    if (!texto) texto = "";
    for (int i = 0; i < tabla->n; i++) {
        if (strcmp(tabla->textos[i], texto) == 0) return i;
    }
    if (tabla->n >= tabla->capacidad) {
        int nueva = tabla->capacidad ? tabla->capacidad * 2 : 16;
        const char **datos = (const char **)realloc(tabla->textos, (size_t)nueva * sizeof(char *));
        if (!datos) return 0;
        tabla->textos = datos;
        tabla->capacidad = nueva;
    }
    tabla->textos[tabla->n] = texto;
    return tabla->n++;
}

static int empaquetar(Compilador *c, JpBlob *salida) {
    TablaCadenas tabla = {0};
    int total_globales = 0;
    int *bases = (int *)calloc((size_t)(c->n_modulos ? c->n_modulos : 1), sizeof(int));
    if (!bases) return 0;

    for (int i = 0; i < c->n_modulos; i++) {
        Modulo *modulo = &c->modulos[i];
        bases[i] = total_globales;
        total_globales += modulo->n_globales;
        for (int j = 0; j < modulo->n_globales; j++) tabla_indice(&tabla, modulo->globales[j].nombre);
    }
    for (int i = 0; i < c->n_modulos; i++) tabla_indice(&tabla, c->modulos[i].nombre);
    for (int i = 0; i < c->n_funciones; i++) {
        Funcion *funcion = c->funciones[i];
        tabla_indice(&tabla, funcion->nombre);
        for (int j = 0; j < funcion->n_const_s; j++) tabla_indice(&tabla, funcion->const_s[j]);
    }

    Bolsa b = {0};
    bolsa_bytes(&b, "JPB1", 4);
    bolsa_u32(&b, VERSION_FORMATO);
    bolsa_u32(&b, (unsigned)c->n_funciones);
    bolsa_u32(&b, (unsigned)tabla.n);
    bolsa_u32(&b, (unsigned)total_globales);
    bolsa_u32(&b, 0);

    for (int i = 0; i < tabla.n; i++) {
        const char *texto = tabla.textos[i] ? tabla.textos[i] : "";
        size_t largo = strlen(texto);
        bolsa_u32(&b, (unsigned)largo);
        bolsa_bytes(&b, texto, largo);
    }

    for (int i = 0; i < c->n_modulos; i++) {
        Modulo *modulo = &c->modulos[i];
        for (int j = 0; j < modulo->n_globales; j++) {
            bolsa_u32(&b, (unsigned)tabla_indice(&tabla, modulo->globales[j].nombre));
        }
    }

    for (int i = 0; i < c->n_funciones; i++) {
        Funcion *funcion = c->funciones[i];
        bolsa_u32(&b, (unsigned)tabla_indice(&tabla, funcion->nombre));
        bolsa_u32(&b, (unsigned)funcion->aridad);
        bolsa_u32(&b, (unsigned)funcion->modulo);
        bolsa_u32(&b, (unsigned)funcion->slots);
        for (int slot = 0; slot < funcion->slots; slot++) {
            unsigned char celda = funcion->celdas ? funcion->celdas[slot] : 0;
            bolsa_bytes(&b, &celda, 1);
        }
        bolsa_u32(&b, (unsigned)funcion->n_upvalues);
        for (int j = 0; j < funcion->n_upvalues; j++) {
            unsigned char es_local = (unsigned char)(funcion->upvalues[j].es_local ? 1 : 0);
            bolsa_bytes(&b, &es_local, 1);
            bolsa_u32(&b, (unsigned)funcion->upvalues[j].indice);
        }
        bolsa_u32(&b, 0); /* const_i: no se usa, los enteros van en línea */
        bolsa_u32(&b, 0); /* const_d */
        bolsa_u32(&b, (unsigned)funcion->n_const_s);
        for (int j = 0; j < funcion->n_const_s; j++) {
            bolsa_u32(&b, (unsigned)tabla_indice(&tabla, funcion->const_s[j]));
        }
        bolsa_u32(&b, (unsigned)funcion->n_palabras);
        for (int j = 0; j < funcion->n_palabras; j++) {
            bolsa_u32(&b, (unsigned)funcion->palabras[j]);
        }
        bolsa_u32(&b, (unsigned)funcion->n_lineas);
        for (int j = 0; j < funcion->n_lineas; j++) {
            bolsa_u32(&b, (unsigned)funcion->lineas_pc[j]);
            bolsa_u32(&b, (unsigned)funcion->lineas_numero[j]);
        }
    }

    bolsa_u32(&b, (unsigned)c->n_modulos);
    for (int i = 0; i < c->n_modulos; i++) {
        Modulo *modulo = &c->modulos[i];
        int exportados = 0;
        for (int j = 0; j < modulo->n_globales; j++) {
            if (nombres_tiene(&modulo->declarados, modulo->globales[j].nombre)) exportados++;
        }
        bolsa_u32(&b, (unsigned)tabla_indice(&tabla, modulo->nombre));
        bolsa_u32(&b, (unsigned)modulo->funcion);
        bolsa_u32(&b, (unsigned)bases[i]);
        bolsa_u32(&b, (unsigned)exportados);
        for (int j = 0; j < modulo->n_globales; j++) {
            if (!nombres_tiene(&modulo->declarados, modulo->globales[j].nombre)) continue;
            bolsa_u32(&b, (unsigned)tabla_indice(&tabla, modulo->globales[j].nombre));
            bolsa_u32(&b, (unsigned)modulo->globales[j].indice);
        }
        const char *fuente_modulo = modulo->fuente ? modulo->fuente : "";
        size_t largo = strlen(fuente_modulo);
        bolsa_u32(&b, (unsigned)largo);
        bolsa_bytes(&b, fuente_modulo, largo);
    }

    const char *fuente = c->fuente ? c->fuente : "";
    size_t largo_fuente = strlen(fuente);
    bolsa_u32(&b, (unsigned)largo_fuente);
    bolsa_bytes(&b, fuente, largo_fuente);

    free(tabla.textos);
    free(bases);
    salida->datos = b.datos;
    salida->largo = b.n;
    return 1;
}

/* ------------------------------ API pública */

static void liberar_funcion(Funcion *f) {
    if (!f) return;
    free(f->palabras);
    free(f->lineas_pc);
    free(f->lineas_numero);
    free(f->celdas);
    free(f->upvalues);
    free(f->const_s);
    for (int i = 0; i < f->n_ambitos; i++) free(f->ambitos[i].datos);
    free(f->ambitos);
    nombres_liberar(&f->capturadas);
}

static void liberar_compilador(Compilador *c) {
    for (int i = 0; i < c->n_funciones; i++) liberar_funcion(c->funciones[i]);
    free(c->funciones);
    free(c->pila);
    for (int i = 0; i < c->n_modulos; i++) {
        free(c->modulos[i].globales);
        nombres_liberar(&c->modulos[i].declarados);
    }
    free(c->modulos);
    free((void *)c->ids_rutas);
    free(c->ids_indices);
    free((void *)c->importando);
    free(c->principales);
    for (int i = 0; i < c->n_iteradores; i++) free(c->iteradores[i].saltos);
    free(c->iteradores);
    free((void *)c->intentos);
    for (int i = 0; i < c->n_programas; i++) {
        jp_programa_liberar(c->programas[i]);
        free(c->programas[i]);
    }
    free((void *)c->programas);
    jp_arena_liberar(&c->arena);
}

int jp_compilar(const char *fuente, size_t largo, const char *ruta, JpBlob *salida,
                char *error, size_t error_largo) {
    if (salida) {
        salida->datos = NULL;
        salida->largo = 0;
    }
    JpPrograma *programa = (JpPrograma *)calloc(1, sizeof(JpPrograma));
    if (!programa) return 0;
    if (!jp_parsear(fuente, largo, programa, error, error_largo)) {
        free(programa);
        return 0;
    }

    Compilador c;
    memset(&c, 0, sizeof c);
    c.error = error;
    c.error_largo = error_largo;
    c.fuente = fuente;
    c.nombre_programa = ruta ? ruta : "<código>";
    size_t largo_ruta = ruta ? strlen(ruta) : 0;
    if (largo_ruta >= 3 && strcmp(ruta + largo_ruta - 3, ".jp") == 0) {
        c.directorio_base = direccionario_de(&c, ruta);
    } else {
        c.directorio_base = copia_texto(&c, ".");
    }

    /* módulo 0: el programa */
    c.capacidad_modulos = 4;
    c.modulos = (Modulo *)calloc((size_t)c.capacidad_modulos, sizeof(Modulo));
    if (!c.modulos) {
        jp_programa_liberar(programa);
        free(programa);
        jp_arena_liberar(&c.arena);
        return 0;
    }
    Modulo *estado = &c.modulos[c.n_modulos++];
    estado->nombre = copia_texto(&c, c.nombre_programa);
    estado->fuente = fuente;
    estado->directorio = c.directorio_base;

    Nombres capturadas = {0};
    capturadas_por_anidadas(programa->raiz, &capturadas);
    Funcion *principal = nueva_funcion(&c, "<programa>", 0, &capturadas);
    nombres_liberar(&capturadas);
    if (!principal) {
        liberar_compilador(&c);
        jp_programa_liberar(programa);
        free(programa);
        return 0;
    }
    principal->modulo = 0;
    c.capacidad_funciones = 8;
    c.funciones = (Funcion **)calloc((size_t)c.capacidad_funciones, sizeof(Funcion *));
    c.capacidad_pila = 8;
    c.pila = (Funcion **)calloc((size_t)c.capacidad_pila, sizeof(Funcion *));
    c.capacidad_principales = 4;
    c.principales = (Funcion **)calloc((size_t)c.capacidad_principales, sizeof(Funcion *));
    if (!c.funciones || !c.pila || !c.principales) {
        liberar_compilador(&c);
        jp_programa_liberar(programa);
        free(programa);
        return 0;
    }
    c.funciones[c.n_funciones++] = principal;
    c.principales[c.n_principales++] = principal;
    c.pila[c.n_pila++] = principal;

    int ok = compilar_bloque(&c, &programa->raiz->hijos, 0);
    if (ok && !c.fallo) emitir(principal, OP_RETORNAR_NULO, 0);
    int empaquetado = 0;
    if (ok && !c.fallo) empaquetado = empaquetar(&c, salida);

    if (!ok || !empaquetado) {
        if (!c.fallo && error && error_largo) {
            snprintf(error, error_largo, "no se pudo compilar el programa|0|0");
        }
        if (salida) {
            free(salida->datos);
            salida->datos = NULL;
            salida->largo = 0;
        }
    }

    liberar_compilador(&c);
    jp_programa_liberar(programa);
    free(programa);
    return ok && empaquetado;
}

void jp_blob_liberar(JpBlob *blob) {
    if (!blob) return;
    free(blob->datos);
    blob->datos = NULL;
    blob->largo = 0;
}
