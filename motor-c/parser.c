/* Parser de JP en C: descenso recursivo, port fiel de `jp/parser.py`.
 *
 * Niveles de precedencia (de menor a mayor):
 *   asignacion < '??' < 'o' < 'y' < igualdad < comparacion < termino < factor
 *   < unario < potencia < llamada < primario
 *
 * Igual que en Python, el parser pliega constantes al vuelo (2 + 3 -> 5,
 * "a" + "b" -> "ab"), porque el bytecode generado después debe ser idéntico.
 */

#include "parser.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lexer.h"

typedef struct {
    JpArena *arena;
    JpTokens *tokens;
    size_t pos;
    char *error;
    size_t error_largo;
} Parser;

/* ---------------------------------------------------------- utilidades */

static JpToken *actual(Parser *p) { return &p->tokens->datos[p->pos]; }

static JpToken *avanzar(Parser *p) {
    JpToken *token = actual(p);
    if (token->tipo != T_FIN_DE_ARCHIVO) p->pos++;
    return token;
}

static JpToken *coincide(Parser *p, JpTokenType tipo) {
    if (actual(p)->tipo == tipo) return avanzar(p);
    return NULL;
}

static const char *texto_o_vacio(const char *texto) { return texto ? texto : ""; }

/* repr() de Python para una cadena: comillas simples salvo que el texto tenga
 * comillas simples y ninguna doble. Es lo que sale en los mensajes de error. */
static void repr_python(const char *texto, char *salida, size_t largo) {
    if (!salida || largo == 0) return;
    const char *s = texto_o_vacio(texto);
    char comilla = '\'';
    if (strchr(s, '\'') && !strchr(s, '"')) comilla = '"';
    size_t usado = 0;
    if (usado + 1 < largo) salida[usado++] = comilla;
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        const char *trozo = NULL;
        char temporal[8];
        switch (*p) {
            case '\\': trozo = "\\\\"; break;
            case '\n': trozo = "\\n"; break;
            case '\r': trozo = "\\r"; break;
            case '\t': trozo = "\\t"; break;
            default:
                if (*p == (unsigned char)comilla) {
                    temporal[0] = '\\';
                    temporal[1] = comilla;
                    temporal[2] = '\0';
                    trozo = temporal;
                } else if (*p < 0x20 || *p == 0x7f) {
                    snprintf(temporal, sizeof temporal, "\\x%02x", *p);
                    trozo = temporal;
                }
        }
        if (trozo) {
            size_t n = strlen(trozo);
            if (usado + n < largo) {
                memcpy(salida + usado, trozo, n);
                usado += n;
            }
        } else if (usado + 1 < largo) {
            salida[usado++] = (char)*p;
        }
    }
    if (usado + 1 < largo) salida[usado++] = comilla;
    salida[usado < largo ? usado : largo - 1] = '\0';
}

static void fallar(Parser *p, int linea, int columna, const char *formato, ...) {
    if (!p->error || !p->error_largo) return;
    char mensaje[512];
    va_list args;
    va_start(args, formato);
    vsnprintf(mensaje, sizeof mensaje, formato, args);
    va_end(args);
    snprintf(p->error, p->error_largo, "%s|%d|%d", mensaje, linea, columna);
}

/* "{mensaje}, pero se encontró {lexema!r}" con la línea y columna actuales. */
static void fallar_aqui(Parser *p, const char *mensaje) {
    JpToken *token = actual(p);
    char representado[256];
    repr_python(token->lexema, representado, sizeof representado);
    fallar(p, token->linea, token->columna, "%s, pero se encontró %s", mensaje, representado);
}

static JpToken *esperar(Parser *p, JpTokenType tipo, const char *mensaje) {
    if (actual(p)->tipo == tipo) return avanzar(p);
    fallar_aqui(p, mensaje);
    return NULL;
}

static JpNodo *nodo(Parser *p, JpNodoTipo tipo, int linea) {
    return jp_nodo_nuevo(p->arena, tipo, linea);
}

static char *copiar(Parser *p, const char *texto) {
    return texto ? jp_arena_texto(p->arena, texto) : NULL;
}

static JpNodo *nodo_cadena(Parser *p, const char *texto, int linea) {
    JpNodo *n = nodo(p, N_CADENA, linea);
    if (n) n->texto = copiar(p, texto_o_vacio(texto));
    return n;
}

static JpNodo *nodo_variable(Parser *p, const char *nombre, int linea) {
    JpNodo *n = nodo(p, N_VARIABLE, linea);
    if (n) n->nombre = copiar(p, texto_o_vacio(nombre));
    return n;
}

/* --------------------------------------------------------- expresiones */

static JpNodo *expresion(Parser *p);
static JpNodo *asignacion(Parser *p);
static JpNodo *unario(Parser *p);
static JpNodo *bloque(Parser *p);
static int parametros(Parser *p, JpNodos *destino, const char *tras_que, int linea);
static int tipo_anotado(Parser *p, char **destino);

typedef struct {
    int es_entero;
    long long entero;
    double decimal;
} Numero;

static int numero_de_nodo(const JpNodo *n, Numero *salida) {
    if (!n || n->tipo != N_NUMERO) return 0;
    salida->es_entero = n->es_entero;
    salida->entero = n->entero;
    salida->decimal = n->decimal;
    return 1;
}

static JpNodo *nodo_numero(Parser *p, Numero valor, int linea) {
    JpNodo *n = nodo(p, N_NUMERO, linea);
    if (!n) return NULL;
    n->es_entero = valor.es_entero;
    n->entero = valor.entero;
    n->decimal = valor.decimal;
    return n;
}

static long long modulo_entero(long long a, long long b) {
    long long r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) r += b;
    return r;
}

static double modulo_real(double a, double b) {
    double r = fmod(a, b);
    if (r != 0 && ((r < 0) != (b < 0))) r += b;
    return r;
}

/* Potencia entera con detección de desbordamiento (0 = no cabe en int64). */
static int potencia_entera(long long base, long long exponente, long long *salida) {
    const __int128 MAXIMO = 9223372036854775807LL;
    const __int128 MINIMO = -9223372036854775807LL - 1;
    __int128 acumulado = 1;
    __int128 factor = base;
    long long e = exponente;
    while (e > 0) {
        if (e & 1) {
            acumulado *= factor;
            if (acumulado > MAXIMO || acumulado < MINIMO) return 0;
        }
        e >>= 1;
        if (e) {
            factor *= factor;
            if (factor > MAXIMO || factor < MINIMO) return 0;
        }
    }
    *salida = (long long)acumulado;
    return 1;
}

/* Plegado de constantes, igual que `_plegar` de jp/parser.py. */
static JpNodo *plegar(Parser *p, const char *operador, JpNodo *izq, JpNodo *der, int linea) {
    Numero a, b;
    if (numero_de_nodo(izq, &a) && numero_de_nodo(der, &b)) {
        Numero resultado;
        resultado.es_entero = a.es_entero && b.es_entero;
        int plegado = 0;
        if (strcmp(operador, "+") == 0) {
            if (resultado.es_entero) {
                __int128 suma = (__int128)a.entero + b.entero;
                if (suma <= 9223372036854775807LL && suma >= -9223372036854775807LL - 1) {
                    resultado.entero = (long long)suma;
                    plegado = 1;
                }
            } else {
                resultado.decimal = (a.es_entero ? (double)a.entero : a.decimal) +
                                    (b.es_entero ? (double)b.entero : b.decimal);
                plegado = 1;
            }
        } else if (strcmp(operador, "-") == 0) {
            if (resultado.es_entero) {
                __int128 resta = (__int128)a.entero - b.entero;
                if (resta <= 9223372036854775807LL && resta >= -9223372036854775807LL - 1) {
                    resultado.entero = (long long)resta;
                    plegado = 1;
                }
            } else {
                resultado.decimal = (a.es_entero ? (double)a.entero : a.decimal) -
                                    (b.es_entero ? (double)b.entero : b.decimal);
                plegado = 1;
            }
        } else if (strcmp(operador, "*") == 0) {
            if (resultado.es_entero) {
                __int128 producto = (__int128)a.entero * b.entero;
                if (producto <= 9223372036854775807LL && producto >= -9223372036854775807LL - 1) {
                    resultado.entero = (long long)producto;
                    plegado = 1;
                }
            } else {
                resultado.decimal = (a.es_entero ? (double)a.entero : a.decimal) *
                                    (b.es_entero ? (double)b.entero : b.decimal);
                plegado = 1;
            }
        } else if (strcmp(operador, "/") == 0) {
            double divisor = b.es_entero ? (double)b.entero : b.decimal;
            if (divisor != 0) {
                if (resultado.es_entero && b.entero != 0 && a.entero % b.entero == 0) {
                    resultado.entero = a.entero / b.entero;
                } else {
                    resultado.es_entero = 0;
                    resultado.decimal = (a.es_entero ? (double)a.entero : a.decimal) / divisor;
                }
                plegado = 1;
            }
        } else if (strcmp(operador, "%") == 0) {
            double divisor = b.es_entero ? (double)b.entero : b.decimal;
            if (divisor != 0) {
                if (resultado.es_entero) {
                    resultado.entero = modulo_entero(a.entero, b.entero);
                } else {
                    resultado.es_entero = 0;
                    resultado.decimal = modulo_real(a.es_entero ? (double)a.entero : a.decimal, divisor);
                }
                plegado = 1;
            }
        } else if (strcmp(operador, "**") == 0) {
            if (resultado.es_entero && b.entero >= 0) {
                long long valor = 0;
                if (potencia_entera(a.entero, b.entero, &valor)) {
                    resultado.entero = valor;
                    plegado = 1;
                }
            } else {
                double base = a.es_entero ? (double)a.entero : a.decimal;
                double exponente = b.es_entero ? (double)b.entero : b.decimal;
                if (!(base == 0 && exponente < 0)) {
                    resultado.es_entero = 0;
                    resultado.decimal = pow(base, exponente);
                    plegado = 1;
                }
            }
        }
        if (plegado) return nodo_numero(p, resultado, linea);
    }

    if (strcmp(operador, "+") == 0 && izq->tipo == N_CADENA && der->tipo == N_CADENA) {
        size_t largos = strlen(texto_o_vacio(izq->texto)) + strlen(texto_o_vacio(der->texto));
        char *unido = (char *)jp_arena_reservar(p->arena, largos + 1);
        if (unido) {
            strcpy(unido, texto_o_vacio(izq->texto));
            strcat(unido, texto_o_vacio(der->texto));
            JpNodo *n = nodo(p, N_CADENA, linea);
            if (n) {
                n->texto = unido;
                return n;
            }
        }
    }

    JpNodo *n = nodo(p, N_BINARIO, linea);
    if (!n) return NULL;
    n->texto = copiar(p, operador);
    n->izq = izq;
    n->der = der;
    return n;
}

static JpNodo *primario(Parser *p);

static int argumentos(Parser *p, JpNodos *destino, int *linea_cierre) {
    if (actual(p)->tipo != T_PAREN_DER) {
        while (1) {
            JpNodo *argumento = expresion(p);
            if (!argumento) return 0;
            jp_nodos_agregar(p->arena, destino, argumento);
            if (!coincide(p, T_COMA)) break;
        }
    }
    JpToken *parentesis = esperar(p, T_PAREN_DER, "se esperaba ')' tras los argumentos");
    if (!parentesis) return 0;
    if (linea_cierre) *linea_cierre = parentesis->linea;
    return 1;
}

static JpNodo *interpolacion(Parser *p, JpToken *token) {
    JpNodo *n = nodo(p, N_INTERPOLACION, token->linea);
    if (!n) return NULL;
    jp_nodos_agregar(p->arena, &n->hijos, nodo_cadena(p, token->literal, token->linea));
    while (1) {
        JpNodo *parte = expresion(p);
        if (!parte) return NULL;
        jp_nodos_agregar(p->arena, &n->hijos, parte);
        JpToken *medio = avanzar(p);
        if (medio->tipo == T_CADENA_FIN) {
            jp_nodos_agregar(p->arena, &n->hijos, nodo_cadena(p, medio->literal, medio->linea));
            break;
        }
        if (medio->tipo != T_CADENA_MEDIO) {
            fallar(p, medio->linea, medio->columna, "interpolación mal formada: falta el '}'");
            return NULL;
        }
        jp_nodos_agregar(p->arena, &n->hijos, nodo_cadena(p, medio->literal, medio->linea));
    }
    return n;
}

/* ¿Es un nombre que puede usarse como clave ('d.no', '{si: 1}')? */
static int es_clave_valida(JpTokenType tipo) {
    return tipo == T_IDENTIFICADOR || tipo == T_SI || tipo == T_EN || tipo == T_Y ||
           tipo == T_O || tipo == T_NO;
}

static JpNodo *primario(Parser *p) {
    JpToken *token = avanzar(p);
    switch (token->tipo) {
        case T_CADENA_INI:
            return interpolacion(p, token);
        case T_NUMERO: {
            Numero valor;
            if (token->es_entero) {
                valor.es_entero = 1;
                valor.entero = strtoll(token->lexema, NULL, 10);
                valor.decimal = 0;
            } else {
                valor.es_entero = 0;
                valor.entero = 0;
                valor.decimal = token->numero;
            }
            return nodo_numero(p, valor, token->linea);
        }
        case T_CADENA:
            return nodo_cadena(p, token->literal, token->linea);
        case T_VERDADERO:
        case T_FALSO: {
            JpNodo *n = nodo(p, N_BOOLEANO, token->linea);
            if (n) n->booleano = token->tipo == T_VERDADERO;
            return n;
        }
        case T_NULO:
            return nodo(p, N_NULO, token->linea);
        case T_IDENTIFICADOR:
            return nodo_variable(p, token->lexema, token->linea);
        case T_FUN: {
            JpNodo *n = nodo(p, N_FUNCION, token->linea);
            if (!n) return NULL;
            n->nombre = copiar(p, "");
            if (!parametros(p, &n->params, "'funcion'", n->linea)) return NULL;
            if (coincide(p, T_DOSPUNTOS)) {
                if (!tipo_anotado(p, &n->texto)) return NULL;
            }
            if (!esperar(p, T_LLAVE_IZQ, "se esperaba '{' antes del cuerpo de la función")) return NULL;
            n->cuerpo = bloque(p);
            return n->cuerpo ? n : NULL;
        }
        case T_CORCHETE_IZQ: {
            JpNodo *n = nodo(p, N_LISTA, token->linea);
            if (!n) return NULL;
            if (actual(p)->tipo != T_CORCHETE_DER) {
                while (1) {
                    JpNodo *elemento = expresion(p);
                    if (!elemento) return NULL;
                    jp_nodos_agregar(p->arena, &n->hijos, elemento);
                    if (!coincide(p, T_COMA)) break;
                }
            }
            if (!esperar(p, T_CORCHETE_DER, "se esperaba ']' tras la lista")) return NULL;
            return n;
        }
        case T_LLAVE_IZQ: {
            JpNodo *n = nodo(p, N_DICCIONARIO, token->linea);
            if (!n) return NULL;
            if (actual(p)->tipo != T_LLAVE_DER) {
                while (1) {
                    JpToken *clave_token = actual(p);
                    JpNodo *clave = NULL;
                    if (es_clave_valida(clave_token->tipo)) {
                        avanzar(p);
                        clave = nodo_cadena(p, clave_token->lexema, clave_token->linea);
                    } else if (clave_token->tipo == T_CADENA) {
                        avanzar(p);
                        clave = nodo_cadena(p, clave_token->literal, clave_token->linea);
                    } else {
                        fallar(p, clave_token->linea, clave_token->columna,
                               "las claves de un diccionario son nombres o cadenas, ej: {nombre: \"Ana\"}");
                        return NULL;
                    }
                    if (!esperar(p, T_DOSPUNTOS, "se esperaba ':' entre la clave y el valor")) return NULL;
                    JpNodo *valor = expresion(p);
                    if (!valor) return NULL;
                    jp_nodos_agregar(p->arena, &n->hijos, clave);
                    jp_nodos_agregar(p->arena, &n->hijos, valor);
                    if (!coincide(p, T_COMA)) break;
                }
            }
            if (!esperar(p, T_LLAVE_DER, "se esperaba '}' para cerrar el diccionario")) return NULL;
            return n;
        }
        case T_PAREN_IZQ: {
            JpNodo *expr = expresion(p);
            if (!expr) return NULL;
            if (!esperar(p, T_PAREN_DER, "se esperaba ')' tras la expresión")) return NULL;
            return expr;
        }
        default: {
            char representado[256];
            if (token->tipo == T_FIN_DE_ARCHIVO) {
                fallar(p, token->linea, token->columna,
                       "se esperaba una expresión, pero se encontró fin del archivo");
            } else {
                repr_python(token->lexema, representado, sizeof representado);
                fallar(p, token->linea, token->columna,
                       "se esperaba una expresión, pero se encontró %s", representado);
            }
            return NULL;
        }
    }
}

/* ¿Viene '[a, b] ='? (patrón de nombres seguido de asignación). */
static int es_patron_desestructuracion(Parser *p) {
    size_t i = p->pos + 1;
    size_t total = p->tokens->n;
    JpTokenType tipo_en = T_FIN_DE_ARCHIVO;
    if (i < total && p->tokens->datos[i].tipo != T_IDENTIFICADOR) return 0;
    i += 1;
    while (i < total && p->tokens->datos[i].tipo == T_COMA) {
        if (i + 1 >= total || p->tokens->datos[i + 1].tipo != T_IDENTIFICADOR) return 0;
        i += 2;
    }
    if (i >= total || p->tokens->datos[i].tipo != T_CORCHETE_DER) return 0;
    tipo_en = (i + 1 < total) ? p->tokens->datos[i + 1].tipo : T_FIN_DE_ARCHIVO;
    return tipo_en == T_IGUAL;
}

static JpNodo *llamada(Parser *p) {
    JpNodo *expr = primario(p);
    if (!expr) return NULL;
    int cadena_segura = 0;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo == T_INTERROGACION_PUNTO) {
            avanzar(p);
            cadena_segura = 1;
            if (coincide(p, T_PAREN_IZQ)) {
                JpNodo *n = nodo(p, N_LLAMADA, token->linea);
                if (!n) return NULL;
                n->seguro = 1;
                n->callee = expr;
                if (!argumentos(p, &n->hijos, &n->linea)) return NULL;
                expr = n;
            } else if (coincide(p, T_CORCHETE_IZQ)) {
                JpNodo *indice = expresion(p);
                if (!indice) return NULL;
                JpToken *cierre = esperar(p, T_CORCHETE_DER, "se esperaba ']' tras el índice");
                if (!cierre) return NULL;
                JpNodo *n = nodo(p, N_INDICE, cierre->linea);
                if (!n) return NULL;
                n->seguro = 1;
                n->objeto = expr;
                n->indice = indice;
                expr = n;
            } else {
                JpToken *clave = avanzar(p);
                if (!es_clave_valida(clave->tipo)) {
                    fallar(p, clave->linea, clave->columna, "después de '?.' va el nombre de la clave");
                    return NULL;
                }
                JpNodo *n = nodo(p, N_INDICE, clave->linea);
                if (!n) return NULL;
                n->seguro = 1;
                n->objeto = expr;
                n->indice = nodo_cadena(p, clave->lexema, clave->linea);
                expr = n;
            }
        } else if (token->tipo == T_PAREN_IZQ) {
            avanzar(p);
            JpNodo *n = nodo(p, N_LLAMADA, token->linea);
            if (!n) return NULL;
            n->seguro = cadena_segura;
            n->callee = expr;
            if (!argumentos(p, &n->hijos, &n->linea)) return NULL;
            expr = n;
        } else if (token->tipo == T_CORCHETE_IZQ &&
                   token->linea != p->tokens->datos[p->pos - 1].linea &&
                   es_patron_desestructuracion(p)) {
            break; /* '[a, b] = ...' en otra línea es la sentencia siguiente */
        } else if (token->tipo == T_CORCHETE_IZQ) {
            avanzar(p);
            JpNodo *indice = expresion(p);
            if (!indice) return NULL;
            JpToken *cierre = esperar(p, T_CORCHETE_DER, "se esperaba ']' tras el índice");
            if (!cierre) return NULL;
            JpNodo *n = nodo(p, N_INDICE, cierre->linea);
            if (!n) return NULL;
            n->seguro = cadena_segura;
            n->objeto = expr;
            n->indice = indice;
            expr = n;
        } else if (token->tipo == T_PUNTO) {
            avanzar(p);
            JpToken *clave = avanzar(p);
            if (!es_clave_valida(clave->tipo)) {
                fallar(p, clave->linea, clave->columna, "después de '.' va el nombre de la clave");
                return NULL;
            }
            JpNodo *n = nodo(p, N_INDICE, clave->linea);
            if (!n) return NULL;
            n->seguro = cadena_segura;
            n->objeto = expr;
            n->indice = nodo_cadena(p, clave->lexema, clave->linea);
            expr = n;
        } else {
            break;
        }
    }
    return expr;
}

static JpNodo *potencia(Parser *p) {
    JpNodo *expr = llamada(p);
    if (!expr) return NULL;
    JpToken *token = coincide(p, T_POTENCIA);
    if (!token) return expr;
    JpNodo *derecha = unario(p); /* derecha-asociativa, admite exponente negativo */
    if (!derecha) return NULL;
    return plegar(p, "**", expr, derecha, token->linea);
}

static JpNodo *unario(Parser *p) {
    JpToken *token = actual(p);
    if (token->tipo == T_NO || token->tipo == T_MENOS) {
        avanzar(p);
        JpNodo *operando = unario(p);
        if (!operando) return NULL;
        if (token->tipo == T_MENOS && operando->tipo == N_NUMERO) {
            Numero valor;
            numero_de_nodo(operando, &valor);
            if (valor.es_entero) {
                valor.entero = -valor.entero;
            } else {
                valor.decimal = -valor.decimal;
            }
            return nodo_numero(p, valor, token->linea);
        }
        JpNodo *n = nodo(p, N_UNARIO, token->linea);
        if (!n) return NULL;
        n->texto = copiar(p, token->tipo == T_MENOS ? "-" : "no");
        n->operando = operando;
        return n;
    }
    return potencia(p);
}

static JpNodo *factor(Parser *p) {
    JpNodo *expr = unario(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_POR && token->tipo != T_ENTRE && token->tipo != T_MODULO) break;
        avanzar(p);
        JpNodo *derecha = unario(p);
        if (!derecha) return NULL;
        expr = plegar(p, token->lexema, expr, derecha, token->linea);
        if (!expr) return NULL;
    }
    return expr;
}

static JpNodo *termino(Parser *p) {
    JpNodo *expr = factor(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_MAS && token->tipo != T_MENOS) break;
        avanzar(p);
        JpNodo *derecha = factor(p);
        if (!derecha) return NULL;
        expr = plegar(p, token->lexema, expr, derecha, token->linea);
        if (!expr) return NULL;
    }
    return expr;
}

static JpNodo *comparacion(Parser *p) {
    JpNodo *expr = termino(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_MENOR && token->tipo != T_MAYOR &&
            token->tipo != T_MENOR_IGUAL && token->tipo != T_MAYOR_IGUAL) {
            break;
        }
        avanzar(p);
        JpNodo *derecha = termino(p);
        if (!derecha) return NULL;
        JpNodo *n = nodo(p, N_BINARIO, token->linea);
        if (!n) return NULL;
        n->texto = copiar(p, token->lexema);
        n->izq = expr;
        n->der = derecha;
        expr = n;
    }
    return expr;
}

static JpNodo *igualdad(Parser *p) {
    JpNodo *expr = comparacion(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_IGUAL_IGUAL && token->tipo != T_DIFERENTE) break;
        avanzar(p);
        JpNodo *derecha = comparacion(p);
        if (!derecha) return NULL;
        JpNodo *n = nodo(p, N_BINARIO, token->linea);
        if (!n) return NULL;
        n->texto = copiar(p, token->lexema);
        n->izq = expr;
        n->der = derecha;
        expr = n;
    }
    return expr;
}

static JpNodo *conjuncion(Parser *p) {
    JpNodo *expr = igualdad(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_Y) break;
        avanzar(p);
        JpNodo *derecha = igualdad(p);
        if (!derecha) return NULL;
        JpNodo *n = nodo(p, N_BINARIO, token->linea);
        if (!n) return NULL;
        n->texto = copiar(p, "y");
        n->izq = expr;
        n->der = derecha;
        expr = n;
    }
    return expr;
}

static JpNodo *disyuncion(Parser *p) {
    JpNodo *expr = conjuncion(p);
    if (!expr) return NULL;
    while (1) {
        JpToken *token = actual(p);
        if (token->tipo != T_O) break;
        avanzar(p);
        JpNodo *derecha = conjuncion(p);
        if (!derecha) return NULL;
        JpNodo *n = nodo(p, N_BINARIO, token->linea);
        if (!n) return NULL;
        n->texto = copiar(p, "o");
        n->izq = expr;
        n->der = derecha;
        expr = n;
    }
    return expr;
}

static JpNodo *por_defecto(Parser *p) {
    JpNodo *expr = disyuncion(p);
    if (!expr) return NULL;
    JpToken *token = coincide(p, T_DOBLE_INTERROGACION);
    if (!token) return expr;
    JpNodo *derecha = por_defecto(p); /* asocia a la derecha */
    if (!derecha) return NULL;
    JpNodo *n = nodo(p, N_BINARIO, token->linea);
    if (!n) return NULL;
    n->texto = copiar(p, "??");
    n->izq = expr;
    n->der = derecha;
    return n;
}

static JpNodo *rango(Parser *p) {
    JpNodo *expr = por_defecto(p);
    if (!expr) return NULL;
    JpToken *token = coincide(p, T_PUNTO_PUNTO);
    if (!token) return expr;
    JpNodo *derecha = por_defecto(p);
    if (!derecha) return NULL;
    JpNodo *paso = NULL;
    if (actual(p)->tipo == T_IDENTIFICADOR && actual(p)->lexema &&
        strcmp(actual(p)->lexema, "paso") == 0) {
        avanzar(p);
        paso = por_defecto(p);
        if (!paso) return NULL;
    }
    JpNodo *n = nodo(p, N_RANGO, token->linea);
    if (!n) return NULL;
    n->izq = expr;
    n->der = derecha;
    n->paso = paso;
    return n;
}

static JpNodo *asignacion(Parser *p) {
    JpNodo *expr = rango(p);
    if (!expr) return NULL;
    JpToken *token = actual(p);
    if (token->tipo != T_IGUAL && token->tipo != T_MAS_IGUAL && token->tipo != T_MENOS_IGUAL &&
        token->tipo != T_POR_IGUAL && token->tipo != T_ENTRE_IGUAL && token->tipo != T_MODULO_IGUAL) {
        return expr;
    }
    avanzar(p);
    JpNodo *valor = asignacion(p);
    if (!valor) return NULL;
    if (token->tipo != T_IGUAL) {
        const char *operador = "+";
        if (token->tipo == T_MENOS_IGUAL) operador = "-";
        else if (token->tipo == T_POR_IGUAL) operador = "*";
        else if (token->tipo == T_ENTRE_IGUAL) operador = "/";
        else if (token->tipo == T_MODULO_IGUAL) operador = "%";
        JpNodo *binario = nodo(p, N_BINARIO, token->linea);
        if (!binario) return NULL;
        binario->texto = copiar(p, operador);
        binario->izq = expr;
        binario->der = valor;
        valor = binario;
    }
    if (expr->tipo == N_LISTA && expr->hijos.n > 0) {
        int todas_variables = 1;
        for (int i = 0; i < expr->hijos.n; i++) {
            if (expr->hijos.datos[i]->tipo != N_VARIABLE) {
                todas_variables = 0;
                break;
            }
        }
        if (todas_variables) {
            JpNodo *n = nodo(p, N_ASIGNACION_LISTA, expr->linea);
            if (!n) return NULL;
            for (int i = 0; i < expr->hijos.n; i++) {
                jp_nodos_agregar(p->arena, &n->hijos,
                                 nodo_cadena(p, expr->hijos.datos[i]->nombre,
                                             expr->hijos.datos[i]->linea));
            }
            n->valor = valor;
            return n;
        }
    }
    if (expr->tipo == N_VARIABLE) {
        JpNodo *n = nodo(p, N_ASIGNACION, expr->linea);
        if (!n) return NULL;
        n->nombre = expr->nombre;
        n->valor = valor;
        return n;
    }
    if (expr->tipo == N_INDICE) {
        if (expr->seguro) {
            fallar(p, token->linea, token->columna,
                   "no se puede asignar a un acceso seguro '?.': quita el '?' para asignar");
            return NULL;
        }
        JpNodo *n = nodo(p, N_ASIGNAR_INDICE, expr->linea);
        if (!n) return NULL;
        n->objeto = expr->objeto;
        n->indice = expr->indice;
        n->valor = valor;
        return n;
    }
    fallar(p, token->linea, token->columna,
           "el objetivo de %s debe ser una variable, lista[i] o d.clave",
           token->lexema ? token->lexema : "");
    return NULL;
}

static JpNodo *expresion(Parser *p) { return asignacion(p); }

/* ----------------------------------------------------------- sentencias */

static JpNodo *sentencia(Parser *p);
static JpNodo *bloque(Parser *p);

static int tipo_anotado(Parser *p, char **destino) {
    static const char *TIPOS[] = {
        "numero", "entero", "texto", "booleano", "lista", "diccionario",
        "funcion", "nulo", "cualquiera",
    };
    JpToken *token = esperar(
        p, T_IDENTIFICADOR,
        "se esperaba un tipo: numero, entero, texto, booleano, lista, diccionario, funcion, nulo o cualquiera");
    if (!token) return 0;
    char normalizado[64];
    snprintf(normalizado, sizeof normalizado, "%s", token->lexema ? token->lexema : "");
    if (strcmp(normalizado, "número") == 0) snprintf(normalizado, sizeof normalizado, "numero");
    for (size_t i = 0; i < sizeof TIPOS / sizeof TIPOS[0]; i++) {
        if (strcmp(normalizado, TIPOS[i]) == 0) {
            if (destino) *destino = copiar(p, normalizado);
            return 1;
        }
    }
    fallar(p, token->linea, token->columna,
           "tipo desconocido '%s': usa numero, entero, texto, booleano, "
           "lista, diccionario, funcion, nulo o cualquiera",
           token->lexema ? token->lexema : "");
    return 0;
}

static int parametros(Parser *p, JpNodos *destino, const char *tras_que, int linea) {
    char mensaje[256];
    snprintf(mensaje, sizeof mensaje, "se esperaba '(' tras %s", tras_que);
    if (!esperar(p, T_PAREN_IZQ, mensaje)) return 0;
    int ya_hay_defecto = 0;
    if (actual(p)->tipo != T_PAREN_DER) {
        while (1) {
            JpToken *parametro = esperar(p, T_IDENTIFICADOR, "se esperaba un nombre de parámetro");
            if (!parametro) return 0;
            JpNodo *n = nodo(p, N_PARAMETRO, linea);
            if (!n) return 0;
            n->nombre = copiar(p, parametro->lexema);
            if (coincide(p, T_DOSPUNTOS)) {
                if (!tipo_anotado(p, &n->tipo_anotado)) return 0;
            }
            if (coincide(p, T_IGUAL)) {
                n->valor = expresion(p);
                if (!n->valor) return 0;
                ya_hay_defecto = 1;
            } else if (ya_hay_defecto) {
                fallar(p, parametro->linea, parametro->columna,
                       "el parámetro '%s' necesita un valor por defecto: "
                       "tras el primer 'parametro = valor', todos deben llevarlo",
                       parametro->lexema ? parametro->lexema : "");
                return 0;
            }
            jp_nodos_agregar(p->arena, destino, n);
            if (!coincide(p, T_COMA)) break;
        }
    }
    return esperar(p, T_PAREN_DER, "se esperaba ')' tras los parámetros") != NULL;
}

static JpNodo *sentencia_fun(Parser *p) {
    JpToken *token = esperar(p, T_IDENTIFICADOR, "se esperaba el nombre de la función");
    if (!token) return NULL;
    JpNodo *n = nodo(p, N_FUNCION, token->linea);
    if (!n) return NULL;
    n->nombre = copiar(p, token->lexema);
    if (!parametros(p, &n->params, "el nombre de la función", n->linea)) return NULL;
    if (coincide(p, T_DOSPUNTOS)) {
        if (!tipo_anotado(p, &n->texto)) return NULL;
    }
    if (!esperar(p, T_LLAVE_IZQ, "se esperaba '{' antes del cuerpo de la función")) return NULL;
    n->cuerpo = bloque(p);
    return n->cuerpo ? n : NULL;
}

static JpNodo *cuerpo_sentencia(Parser *p, const char *que) {
    if (coincide(p, T_LLAVE_IZQ)) return bloque(p);
    if (coincide(p, T_DOSPUNTOS)) {
        JpNodo *unica = sentencia(p);
        if (!unica) return NULL;
        JpNodo *n = nodo(p, N_BLOQUE, 0);
        if (!n) return NULL;
        jp_nodos_agregar(p->arena, &n->hijos, unica);
        return n;
    }
    char mensaje[256];
    snprintf(mensaje, sizeof mensaje,
             "se esperaba '{' (varias sentencias) o ':' (una sola) %s", que);
    fallar_aqui(p, mensaje);
    return NULL;
}

static JpNodo *condicion(Parser *p, const char *palabra) {
    int en_parentesis = coincide(p, T_PAREN_IZQ) != NULL;
    JpNodo *expr = expresion(p);
    if (!expr) return NULL;
    if (en_parentesis) {
        char mensaje[128];
        snprintf(mensaje, sizeof mensaje, "se esperaba ')' tras la condición de '%s'", palabra);
        if (!esperar(p, T_PAREN_DER, mensaje)) return NULL;
    }
    return expr;
}

static JpNodo *sentencia_si(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_SI, token->linea);
    if (!n) return NULL;
    n->condicion = condicion(p, "si");
    if (!n->condicion) return NULL;
    n->entonces = cuerpo_sentencia(p, "tras la condición");
    if (!n->entonces) return NULL;
    if (coincide(p, T_SINO)) {
        if (coincide(p, T_SI)) {
            JpNodo *anidado = sentencia_si(p);
            if (!anidado) return NULL;
            JpNodo *envoltorio = nodo(p, N_BLOQUE, 0);
            if (!envoltorio) return NULL;
            jp_nodos_agregar(p->arena, &envoltorio->hijos, anidado);
            n->sino = envoltorio;
        } else {
            n->sino = cuerpo_sentencia(p, "tras la condición");
            if (!n->sino) return NULL;
        }
    }
    return n;
}

static JpNodo *sentencia_mientras(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_MIENTRAS, token->linea);
    if (!n) return NULL;
    n->condicion = condicion(p, "mientras");
    if (!n->condicion) return NULL;
    n->cuerpo = cuerpo_sentencia(p, "tras la condición");
    return n->cuerpo ? n : NULL;
}

static JpNodo *sentencia_para(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_PARA, token->linea);
    if (!n) return NULL;
    int en_parentesis = coincide(p, T_PAREN_IZQ) != NULL;
    JpToken *variable = esperar(p, T_IDENTIFICADOR, "se esperaba la variable: 'para i en ...'");
    if (!variable) return NULL;
    n->nombre = copiar(p, variable->lexema);
    if (coincide(p, T_COMA)) {
        JpToken *segunda = esperar(p, T_IDENTIFICADOR,
                                   "se esperaba el segundo nombre: 'para i, valor en ...'");
        if (!segunda) return NULL;
        n->texto = copiar(p, segunda->lexema);
    }
    if (!esperar(p, T_EN, "se esperaba 'en' (ej: 'para i en 1..10')")) return NULL;
    n->iterable = expresion(p);
    if (!n->iterable) return NULL;
    if (en_parentesis) {
        if (!esperar(p, T_PAREN_DER, "se esperaba ')' tras el 'para'")) return NULL;
    }
    n->cuerpo = cuerpo_sentencia(p, "tras la condición");
    return n->cuerpo ? n : NULL;
}

static JpNodo *sentencia_elegir(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_ELEGIR, token->linea);
    if (!n) return NULL;
    n->expresion = expresion(p);
    if (!n->expresion) return NULL;
    if (!esperar(p, T_LLAVE_IZQ, "se esperaba '{' tras el valor de 'elegir'")) return NULL;
    while (actual(p)->tipo != T_LLAVE_DER && actual(p)->tipo != T_FIN_DE_ARCHIVO) {
        if (coincide(p, T_CASO)) {
            JpNodo *caso = nodo(p, N_CASO, actual(p)->linea);
            if (!caso) return NULL;
            JpNodo *valor = expresion(p);
            if (!valor) return NULL;
            jp_nodos_agregar(p->arena, &caso->hijos, valor);
            while (coincide(p, T_COMA)) {
                valor = expresion(p);
                if (!valor) return NULL;
                jp_nodos_agregar(p->arena, &caso->hijos, valor);
            }
            caso->cuerpo = cuerpo_sentencia(p, "tras 'caso'");
            if (!caso->cuerpo) return NULL;
            jp_nodos_agregar(p->arena, &n->hijos, caso);
            continue;
        }
        if (coincide(p, T_SINO)) {
            n->sino = cuerpo_sentencia(p, "tras 'sino'");
            if (!n->sino) return NULL;
            break; /* 'sino' cierra el elegir */
        }
        fallar_aqui(p, "se esperaba 'caso' o 'sino' dentro de 'elegir'");
        return NULL;
    }
    if (!esperar(p, T_LLAVE_DER, "se esperaba '}' para cerrar el 'elegir'")) return NULL;
    return n;
}

static JpNodo *sentencia_intenta(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_INTENTAR, token->linea);
    if (!n) return NULL;
    if (!esperar(p, T_LLAVE_IZQ, "se esperaba '{' tras 'intenta'")) return NULL;
    n->cuerpo = bloque(p);
    if (!n->cuerpo) return NULL;
    if (coincide(p, T_ATRAPA)) {
        if (actual(p)->tipo == T_IDENTIFICADOR) {
            n->texto = copiar(p, avanzar(p)->lexema);
        }
        n->captura = cuerpo_sentencia(p, "tras 'atrapa'");
        if (!n->captura) return NULL;
    }
    if (coincide(p, T_FINALMENTE)) {
        n->finalmente = cuerpo_sentencia(p, "tras 'finalmente'");
        if (!n->finalmente) return NULL;
    }
    if (!n->captura && !n->finalmente) {
        fallar(p, token->linea, token->columna,
               "se esperaba 'atrapa' o 'finalmente' tras el bloque de 'intenta' "
               "(así: intenta { ... } atrapa error { ... })");
        return NULL;
    }
    return n;
}

static JpNodo *sentencia_retorna(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_RETORNA, token->linea);
    if (!n) return NULL;
    JpTokenType tipo = token->tipo;
    if (tipo != T_PUNTO_Y_COMA && tipo != T_LLAVE_DER && tipo != T_FIN_DE_ARCHIVO) {
        n->valor = expresion(p);
        if (!n->valor) return NULL;
    }
    return n;
}

static JpNodo *sentencia_lanzar(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_LANZAR, token->linea);
    if (!n) return NULL;
    n->expresion = expresion(p);
    if (!n->expresion) return NULL;
    n->valor = n->expresion;
    return n;
}

static JpNodo *sentencia_importar(Parser *p) {
    JpToken *token = actual(p);
    JpToken *ruta_token = avanzar(p);
    if (ruta_token->tipo != T_CADENA) {
        fallar(p, ruta_token->linea, ruta_token->columna,
               "importar espera la ruta entre comillas: importar \"utilidades.jp\"");
        return NULL;
    }
    JpNodo *n = nodo(p, N_IMPORTAR, token->linea);
    if (!n) return NULL;
    n->texto = copiar(p, texto_o_vacio(ruta_token->literal));
    if (actual(p)->tipo == T_IDENTIFICADOR && actual(p)->lexema &&
        strcmp(actual(p)->lexema, "como") == 0) {
        avanzar(p);
        JpToken *alias = esperar(p, T_IDENTIFICADOR, "se esperaba un nombre tras 'como'");
        if (!alias) return NULL;
        n->nombre = copiar(p, alias->lexema);
    }
    return n;
}

static JpNodo *sentencia_clase(Parser *p) {
    JpToken *token = actual(p);
    JpToken *nombre = esperar(p, T_IDENTIFICADOR,
                              "se esperaba el nombre de la clase: 'clase Persona { ... }'");
    if (!nombre) return NULL;
    JpNodo *n = nodo(p, N_CLASE, token->linea);
    if (!n) return NULL;
    n->nombre = copiar(p, nombre->lexema);
    if (coincide(p, T_HEREDA)) {
        JpToken *padre = esperar(p, T_IDENTIFICADOR, "se esperaba la clase madre tras 'hereda'");
        if (!padre) return NULL;
        n->texto = copiar(p, padre->lexema);
    }
    if (!esperar(p, T_LLAVE_IZQ, "se esperaba '{' tras el nombre de la clase")) return NULL;
    while (actual(p)->tipo != T_LLAVE_DER && actual(p)->tipo != T_FIN_DE_ARCHIVO) {
        while (coincide(p, T_PUNTO_Y_COMA)) {
        }
        if (actual(p)->tipo == T_LLAVE_DER) break;
        if (!coincide(p, T_FUN)) {
            fallar_aqui(p, "dentro de una clase solo van métodos: 'funcion nombre(...) { ... }'");
            return NULL;
        }
        JpNodo *metodo = sentencia_fun(p);
        if (!metodo) return NULL;
        jp_nodos_agregar(p->arena, &n->hijos, metodo);
    }
    if (!esperar(p, T_LLAVE_DER, "se esperaba '}' para cerrar la clase")) return NULL;
    return n;
}

static JpNodo *sentencia_var(Parser *p) {
    if (coincide(p, T_CORCHETE_IZQ)) {
        JpNodos nombres = {0};
        while (1) {
            JpToken *nombre = esperar(p, T_IDENTIFICADOR,
                                      "se esperaba un nombre dentro de '[...]'");
            if (!nombre) return NULL;
            jp_nodos_agregar(p->arena, &nombres, nodo_cadena(p, nombre->lexema, nombre->linea));
            if (!coincide(p, T_COMA)) break;
        }
        JpToken *cierre = esperar(p, T_CORCHETE_DER, "se esperaba ']' tras los nombres");
        if (!cierre) return NULL;
        if (!esperar(p, T_IGUAL, "se esperaba '=' tras 'variable [a, b]' (ej: variable [a, b] = [1, 2])")) {
            return NULL;
        }
        JpNodo *n = nodo(p, N_DECLARACION_LISTA, cierre->linea);
        if (!n) return NULL;
        n->hijos = nombres;
        n->inicializador = expresion(p);
        return n->inicializador ? n : NULL;
    }
    JpToken *token = esperar(p, T_IDENTIFICADOR, "se esperaba un nombre de variable");
    if (!token) return NULL;
    JpNodo *n = nodo(p, N_DECLARACION_VAR, token->linea);
    if (!n) return NULL;
    n->nombre = copiar(p, token->lexema);
    if (coincide(p, T_DOSPUNTOS)) {
        if (!tipo_anotado(p, &n->tipo_anotado)) return NULL;
    }
    if (coincide(p, T_IGUAL)) {
        n->inicializador = expresion(p);
        if (!n->inicializador) return NULL;
    }
    return n;
}

static JpNodo *sentencia_desestructuracion(Parser *p) {
    JpToken *inicio = avanzar(p); /* '[' */
    JpNodos nombres = {0};
    while (1) {
        JpToken *nombre = esperar(p, T_IDENTIFICADOR, "se esperaba un nombre");
        if (!nombre) return NULL;
        jp_nodos_agregar(p->arena, &nombres, nodo_cadena(p, nombre->lexema, nombre->linea));
        if (!coincide(p, T_COMA)) break;
    }
    if (!esperar(p, T_CORCHETE_DER, "se esperaba ']'")) return NULL;
    if (!esperar(p, T_IGUAL, "se esperaba '='")) return NULL;
    JpNodo *valor = expresion(p);
    if (!valor) return NULL;
    JpNodo *n = nodo(p, N_ASIGNACION_LISTA, inicio->linea);
    if (!n) return NULL;
    n->hijos = nombres;
    n->valor = valor;
    JpNodo *envoltorio = nodo(p, N_EXPRESION, inicio->linea);
    if (!envoltorio) return NULL;
    envoltorio->expresion = n;
    return envoltorio;
}

static JpNodo *sentencia_expresion(Parser *p) {
    JpToken *token = actual(p);
    JpNodo *n = nodo(p, N_EXPRESION, token->linea);
    if (!n) return NULL;
    n->expresion = expresion(p);
    return n->expresion ? n : NULL;
}

static JpNodo *sentencia(Parser *p) {
    JpNodo *resultado = NULL;
    if (coincide(p, T_VAR)) {
        resultado = sentencia_var(p);
    } else if (coincide(p, T_FUN)) {
        resultado = sentencia_fun(p);
    } else if (coincide(p, T_RETORNA)) {
        resultado = sentencia_retorna(p);
    } else if (actual(p)->tipo == T_ROMPER) {
        JpToken *token = avanzar(p);
        resultado = nodo(p, N_ROMPER, token->linea);
    } else if (actual(p)->tipo == T_CONTINUAR) {
        JpToken *token = avanzar(p);
        resultado = nodo(p, N_CONTINUAR, token->linea);
    } else if (coincide(p, T_SI)) {
        resultado = sentencia_si(p);
    } else if (coincide(p, T_ELEGIR)) {
        resultado = sentencia_elegir(p);
    } else if (coincide(p, T_INTENTA)) {
        resultado = sentencia_intenta(p);
    } else if (coincide(p, T_LANZAR)) {
        resultado = sentencia_lanzar(p);
    } else if (coincide(p, T_IMPORTAR)) {
        resultado = sentencia_importar(p);
    } else if (coincide(p, T_CLASE)) {
        resultado = sentencia_clase(p);
    } else if (coincide(p, T_MIENTRAS)) {
        resultado = sentencia_mientras(p);
    } else if (coincide(p, T_PARA)) {
        resultado = sentencia_para(p);
    } else if (coincide(p, T_LLAVE_IZQ)) {
        resultado = bloque(p);
    } else if (actual(p)->tipo == T_CORCHETE_IZQ && es_patron_desestructuracion(p)) {
        resultado = sentencia_desestructuracion(p);
    } else {
        resultado = sentencia_expresion(p);
    }
    if (!resultado) return NULL;
    /* punto y coma opcional al final de cada sentencia */
    while (coincide(p, T_PUNTO_Y_COMA)) {
    }
    return resultado;
}

static JpNodo *bloque(Parser *p) {
    JpNodo *n = nodo(p, N_BLOQUE, 0);
    if (!n) return NULL;
    while (actual(p)->tipo != T_LLAVE_DER && actual(p)->tipo != T_FIN_DE_ARCHIVO) {
        JpNodo *hijo = sentencia(p);
        if (!hijo) return NULL;
        jp_nodos_agregar(p->arena, &n->hijos, hijo);
    }
    if (!esperar(p, T_LLAVE_DER, "se esperaba '}' para cerrar el bloque")) return NULL;
    return n;
}

static JpNodo *parsear(Parser *p) {
    JpNodo *programa = nodo(p, N_PROGRAMA, 0);
    if (!programa) return NULL;
    while (actual(p)->tipo != T_FIN_DE_ARCHIVO) {
        JpNodo *hijo = sentencia(p);
        if (!hijo) return NULL;
        jp_nodos_agregar(p->arena, &programa->hijos, hijo);
    }
    return programa;
}

/* ------------------------------------------------------------- público */

int jp_parsear(const char *fuente, size_t largo, JpPrograma *salida,
               char *error, size_t error_largo) {
    memset(salida, 0, sizeof *salida);
    JpTokens tokens = {0};
    char error_lexico[512];
    if (!jp_tokenizar(fuente, largo, &tokens, error_lexico, sizeof error_lexico)) {
        if (error && error_largo) snprintf(error, error_largo, "%s", error_lexico);
        return 0;
    }
    Parser p;
    memset(&p, 0, sizeof p);
    p.arena = &salida->arena;
    p.tokens = &tokens;
    p.error = error;
    p.error_largo = error_largo;
    JpNodo *raiz = parsear(&p);
    jp_tokens_liberar(&tokens);
    if (!raiz) {
        jp_arena_liberar(&salida->arena);
        return 0;
    }
    salida->raiz = raiz;
    return 1;
}

void jp_programa_liberar(JpPrograma *programa) {
    if (!programa) return;
    jp_arena_liberar(&programa->arena);
    programa->raiz = NULL;
}
