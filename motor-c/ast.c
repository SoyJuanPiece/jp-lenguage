/* Arena y volcado del AST de JP. */

#include "ast.h"

#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

void *jp_arena_reservar(JpArena *arena, size_t bytes) {
    void *memoria = calloc(1, bytes ? bytes : 1);
    if (!memoria) return NULL;
    if (arena->n >= arena->capacidad) {
        int nueva = arena->capacidad ? arena->capacidad * 2 : 64;
        void **datos = (void **)realloc(arena->datos, (size_t)nueva * sizeof(void *));
        if (!datos) {
            free(memoria);
            return NULL;
        }
        arena->datos = datos;
        arena->capacidad = nueva;
    }
    arena->datos[arena->n++] = memoria;
    return memoria;
}

char *jp_arena_copiar(JpArena *arena, const char *texto, size_t largo) {
    char *copia = (char *)jp_arena_reservar(arena, largo + 1);
    if (!copia) return NULL;
    if (largo) memcpy(copia, texto, largo);
    copia[largo] = '\0';
    return copia;
}

char *jp_arena_texto(JpArena *arena, const char *texto) {
    if (!texto) return NULL;
    return jp_arena_copiar(arena, texto, strlen(texto));
}

void jp_arena_liberar(JpArena *arena) {
    for (int i = 0; i < arena->n; i++) free(arena->datos[i]);
    free(arena->datos);
    arena->datos = NULL;
    arena->n = 0;
    arena->capacidad = 0;
}

JpNodo *jp_nodo_nuevo(JpArena *arena, JpNodoTipo tipo, int linea) {
    JpNodo *nodo = (JpNodo *)jp_arena_reservar(arena, sizeof(JpNodo));
    if (!nodo) return NULL;
    nodo->tipo = tipo;
    nodo->linea = linea;
    return nodo;
}

void jp_nodos_agregar(JpArena *arena, JpNodos *lista, JpNodo *nodo) {
    (void)arena;
    if (lista->n >= lista->capacidad) {
        int nueva = lista->capacidad ? lista->capacidad * 2 : 8;
        JpNodo **datos = (JpNodo **)realloc(lista->datos, (size_t)nueva * sizeof(JpNodo *));
        if (!datos) return;
        lista->datos = datos;
        lista->capacidad = nueva;
    }
    lista->datos[lista->n++] = nodo;
}

/* ------------------------------------------------------------ volcado */

static const char *NOMBRES_NODO[] = {
    "PROGRAMA", "BLOQUE", "EXPRESION",
    "DECLVAR", "DECLLISTA", "ASIGNA", "ASIGNALISTA",
    "ASIGINDICE", "BINARIO", "UNARIO", "LLAMADA", "INDICE", "LISTA",
    "RANGO", "DICT", "INTERPOLACION", "FUNCION", "PARAM",
    "RETORNA", "ROMPER", "CONTINUAR", "LANZAR", "IMPORTAR", "CLASE",
    "SI", "MIENTRAS", "PARA", "ELEGIR", "CASO", "INTENTAR",
    "NUMERO", "CADENA", "BOOLEANO", "NULO", "VARIABLE",
};

static void indentar(FILE *salida, int nivel) {
    for (int i = 0; i < nivel; i++) fputs("  ", salida);
}

/* Cabecera de una línea: NOMBRE(detalle)@linea, con el detalle ya formateado. */
typedef struct {
    char texto[512];
    size_t usados;
} Detalle;

static void detalle_agregar(Detalle *d, const char *formato, ...) {
    va_list args;
    va_start(args, formato);
    int escrito = vsnprintf(d->texto + d->usados, sizeof d->texto - d->usados, formato, args);
    va_end(args);
    if (escrito > 0) {
        d->usados += (size_t)escrito;
        if (d->usados >= sizeof d->texto) d->usados = sizeof d->texto - 1;
    }
}

/* Añade un texto entre comillas al detalle, con el mismo escapado que volcar_texto. */
static void detalle_escapar(Detalle *d, const char *texto) {
    detalle_agregar(d, "\"");
    if (!texto) {
        detalle_agregar(d, "null\"");
        return;
    }
    for (const unsigned char *p = (const unsigned char *)texto; *p; p++) {
        switch (*p) {
            case '"': detalle_agregar(d, "\\\""); break;
            case '\\': detalle_agregar(d, "\\\\"); break;
            case '\n': detalle_agregar(d, "\\n"); break;
            case '\t': detalle_agregar(d, "\\t"); break;
            case '\r': detalle_agregar(d, "\\r"); break;
            default:
                if (*p < 0x20) {
                    detalle_agregar(d, "\\x%02x", *p);
                } else {
                    detalle_agregar(d, "%c", (char)*p);
                }
        }
    }
    detalle_agregar(d, "\"");
}

static void volcar_nodo(const JpNodo *nodo, FILE *salida, int nivel);

static void volcar_hijos(const JpNodo *nodo, FILE *salida, int nivel) {
    for (int i = 0; i < nodo->hijos.n; i++) {
        volcar_nodo(nodo->hijos.datos[i], salida, nivel + 1);
    }
}

static void volcar_nodo(const JpNodo *nodo, FILE *salida, int nivel) {
    if (!nodo) {
        indentar(salida, nivel);
        fputs("(null)\n", salida);
        return;
    }
    Detalle d;
    memset(&d, 0, sizeof d);
    const char *detalle = d.texto;

    switch (nodo->tipo) {
        case N_DECLARACION_VAR:
            detalle_agregar(&d, "(%s", nodo->nombre ? nodo->nombre : "");
            if (nodo->tipo_anotado) detalle_agregar(&d, ",tipo=%s", nodo->tipo_anotado);
            detalle_agregar(&d, ")");
            break;
        case N_VARIABLE:
            detalle_agregar(&d, "(%s)", nodo->nombre ? nodo->nombre : "");
            break;
        case N_ASIGNACION:
            detalle_agregar(&d, "(%s)", nodo->nombre ? nodo->nombre : "");
            break;
        case N_DECLARACION_LISTA:
        case N_ASIGNACION_LISTA:
            detalle_agregar(&d, "(");
            for (int i = 0; i < nodo->hijos.n; i++) {
                if (i) detalle_agregar(&d, ",");
                detalle_agregar(&d, "%s", nodo->hijos.datos[i]->texto ? nodo->hijos.datos[i]->texto : "");
            }
            detalle_agregar(&d, ")");
            break;
        case N_BINARIO:
        case N_UNARIO:
            detalle_agregar(&d, "(%s)", nodo->texto ? nodo->texto : "");
            break;
        case N_LLAMADA:
        case N_INDICE:
            detalle_agregar(&d, "(seguro=%d)", nodo->seguro ? 1 : 0);
            break;
        case N_LISTA:
        case N_INTERPOLACION:
            detalle_agregar(&d, "(%d)", nodo->hijos.n);
            break;
        case N_DICCIONARIO:
            /* los hijos van intercalados: clave, valor, clave, valor... */
            detalle_agregar(&d, "(%d)", nodo->hijos.n / 2);
            break;
        case N_RANGO:
            detalle_agregar(&d, "(paso=%d)", nodo->paso ? 1 : 0);
            break;
        case N_FUNCION:
            detalle_agregar(&d, "(");
            detalle_escapar(&d, nodo->nombre);
            detalle_agregar(&d, ",%d)", nodo->params.n);
            break;
        case N_PARAMETRO:
            detalle_agregar(&d, "(%s,%s%s)", nodo->nombre ? nodo->nombre : "",
                            nodo->tipo_anotado ? nodo->tipo_anotado : "-",
                            nodo->valor ? ",defecto" : "");
            break;
        case N_NUMERO:
            if (nodo->es_entero) {
                detalle_agregar(&d, "(int:%lld)", nodo->entero);
            } else {
                detalle_agregar(&d, "(double:%.17g)", nodo->decimal);
            }
            break;
        case N_CADENA:
            detalle_agregar(&d, "(");
            detalle_escapar(&d, nodo->texto);
            detalle_agregar(&d, ")");
            break;
        case N_BOOLEANO:
            detalle_agregar(&d, "(%d)", nodo->booleano ? 1 : 0);
            break;
        case N_CLASE:
            detalle_agregar(&d, "(%s,%s)", nodo->nombre ? nodo->nombre : "",
                            nodo->texto ? nodo->texto : "-");
            break;
        case N_PARA:
            detalle_agregar(&d, "(%s,%s)", nodo->nombre ? nodo->nombre : "",
                            nodo->texto ? nodo->texto : "-");
            break;
        case N_IMPORTAR:
            detalle_agregar(&d, "(%s,%s)", nodo->texto ? nodo->texto : "",
                            nodo->nombre ? nodo->nombre : "-");
            break;
        case N_INTENTAR:
            detalle_agregar(&d, "(%s)", nodo->texto ? nodo->texto : "-");
            break;
        case N_CASO:
            detalle_agregar(&d, "(%d)", nodo->hijos.n);
            break;
        default:
            break;
    }

    indentar(salida, nivel);
    fputs(NOMBRES_NODO[nodo->tipo], salida);
    fputs(detalle, salida);
    fprintf(salida, "@%d\n", nodo->linea);

    switch (nodo->tipo) {
        case N_PROGRAMA:
        case N_BLOQUE:
        case N_CLASE:
            volcar_hijos(nodo, salida, nivel);
            break;
        case N_EXPRESION:
            volcar_nodo(nodo->expresion, salida, nivel + 1);
            break;
        case N_DECLARACION_VAR:
            volcar_nodo(nodo->inicializador, salida, nivel + 1);
            break;
        case N_DECLARACION_LISTA:
        case N_ASIGNACION_LISTA:
            volcar_nodo(nodo->tipo == N_DECLARACION_LISTA ? nodo->inicializador : nodo->valor,
                        salida, nivel + 1);
            break;
        case N_ASIGNACION:
            volcar_nodo(nodo->valor, salida, nivel + 1);
            break;
        case N_ASIGNAR_INDICE:
            volcar_nodo(nodo->objeto, salida, nivel + 1);
            volcar_nodo(nodo->indice, salida, nivel + 1);
            volcar_nodo(nodo->valor, salida, nivel + 1);
            break;
        case N_BINARIO:
            volcar_nodo(nodo->izq, salida, nivel + 1);
            volcar_nodo(nodo->der, salida, nivel + 1);
            break;
        case N_UNARIO:
            volcar_nodo(nodo->operando, salida, nivel + 1);
            break;
        case N_LLAMADA:
            volcar_nodo(nodo->callee, salida, nivel + 1);
            volcar_hijos(nodo, salida, nivel);
            break;
        case N_INDICE:
            volcar_nodo(nodo->objeto, salida, nivel + 1);
            volcar_nodo(nodo->indice, salida, nivel + 1);
            break;
        case N_LISTA:
        case N_DICCIONARIO:
        case N_INTERPOLACION:
            volcar_hijos(nodo, salida, nivel);
            break;
        case N_RANGO:
            volcar_nodo(nodo->izq, salida, nivel + 1);
            volcar_nodo(nodo->der, salida, nivel + 1);
            if (nodo->paso) volcar_nodo(nodo->paso, salida, nivel + 1);
            break;
        case N_FUNCION:
            for (int i = 0; i < nodo->params.n; i++) {
                volcar_nodo(nodo->params.datos[i], salida, nivel + 1);
            }
            volcar_nodo(nodo->cuerpo, salida, nivel + 1);
            break;
        case N_PARAMETRO:
            if (nodo->valor) volcar_nodo(nodo->valor, salida, nivel + 1);
            break;
        case N_RETORNA:
        case N_LANZAR:
            if (nodo->valor) volcar_nodo(nodo->valor, salida, nivel + 1);
            break;
        case N_SI:
            volcar_nodo(nodo->condicion, salida, nivel + 1);
            volcar_nodo(nodo->entonces, salida, nivel + 1);
            if (nodo->sino) volcar_nodo(nodo->sino, salida, nivel + 1);
            break;
        case N_MIENTRAS:
            volcar_nodo(nodo->condicion, salida, nivel + 1);
            volcar_nodo(nodo->cuerpo, salida, nivel + 1);
            break;
        case N_PARA:
            volcar_nodo(nodo->iterable, salida, nivel + 1);
            volcar_nodo(nodo->cuerpo, salida, nivel + 1);
            break;
        case N_ELEGIR:
            volcar_nodo(nodo->expresion, salida, nivel + 1);
            volcar_hijos(nodo, salida, nivel);
            if (nodo->sino) volcar_nodo(nodo->sino, salida, nivel + 1);
            break;
        case N_CASO:
            volcar_hijos(nodo, salida, nivel);
            volcar_nodo(nodo->cuerpo, salida, nivel + 1);
            break;
        case N_INTENTAR:
            volcar_nodo(nodo->cuerpo, salida, nivel + 1);
            if (nodo->captura) volcar_nodo(nodo->captura, salida, nivel + 1);
            if (nodo->finalmente) volcar_nodo(nodo->finalmente, salida, nivel + 1);
            break;
        default:
            break;
    }
}

void jp_ast_volcar(const JpNodo *raiz, FILE *salida) {
    volcar_nodo(raiz, salida, 0);
}
