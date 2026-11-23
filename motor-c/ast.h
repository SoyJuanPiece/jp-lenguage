/* AST de JP en C: el mismo árbol que produce `jp/parser.py`.
 *
 * Un solo tipo de nodo con todos los campos (etiquetado por `tipo`), y un
 * arena que libera todo de golpe. Es el port de `jp/arbol.py` sin las clases
 * de Python: el compilador y los volcados de depuración leen los campos por
 * nombre.
 */

#ifndef JP_AST_H
#define JP_AST_H

#include <stddef.h>
#include <stdio.h>

typedef enum {
    N_PROGRAMA, N_BLOQUE, N_EXPRESION,
    N_DECLARACION_VAR, N_DECLARACION_LISTA, N_ASIGNACION, N_ASIGNACION_LISTA,
    N_ASIGNAR_INDICE, N_BINARIO, N_UNARIO, N_LLAMADA, N_INDICE, N_LISTA,
    N_RANGO, N_DICCIONARIO, N_INTERPOLACION, N_FUNCION, N_PARAMETRO,
    N_RETORNA, N_ROMPER, N_CONTINUAR, N_LANZAR, N_IMPORTAR, N_CLASE,
    N_SI, N_MIENTRAS, N_PARA, N_ELEGIR, N_CASO, N_INTENTAR,
    N_NUMERO, N_CADENA, N_BOOLEANO, N_NULO, N_VARIABLE
} JpNodoTipo;

typedef struct JpNodo JpNodo;

typedef struct {
    JpNodo **datos;
    int n;
    int capacidad;
} JpNodos;

struct JpNodo {
    JpNodoTipo tipo;
    int linea;

    /* literales */
    int es_entero;       /* 1 si el número es entero (int de Python) */
    long long entero;
    double decimal;
    int booleano;

    /* nombres y textos */
    char *nombre;        /* variable, declaración, función, clase, alias */
    char *texto;         /* cadena, operador, ruta, nombre del error, padre */
    char *tipo_anotado;  /* 'variable x: numero' / parámetro anotado */

    JpNodos hijos;       /* sentencias, elementos, argumentos, partes, métodos */
    JpNodos params;      /* parámetros (N_PARAMETRO) de una función */

    JpNodo *izq, *der, *paso, *operando;
    JpNodo *objeto, *indice, *valor, *callee, *inicializador;
    JpNodo *condicion, *entonces, *sino, *cuerpo, *iterable;
    JpNodo *captura, *finalmente, *expresion;

    int seguro;          /* '?.' / '?.' sobre una llamada */
};

/* Arena: todos los nodos y textos de un programa, liberables de una vez. */
typedef struct {
    void **datos;
    int n;
    int capacidad;
} JpArena;

void *jp_arena_reservar(JpArena *arena, size_t bytes);
char *jp_arena_texto(JpArena *arena, const char *texto);
char *jp_arena_copiar(JpArena *arena, const char *texto, size_t largo);
void jp_arena_liberar(JpArena *arena);

JpNodo *jp_nodo_nuevo(JpArena *arena, JpNodoTipo tipo, int linea);
void jp_nodos_agregar(JpArena *arena, JpNodos *lista, JpNodo *nodo);

/* Volcado canónico del árbol (para comparar con el de Python). */
void jp_ast_volcar(const JpNodo *raiz, FILE *salida);

#endif /* JP_AST_H */
