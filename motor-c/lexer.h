/* Lexer de JP en C: la primera pieza del frontend nativo.
 *
 * Es un port fiel de `jp/lexer.py`, tipo de token por tipo de token, para que
 * `jpvm` pueda leer un `.jp` sin Python. El contrato es el mismo: misma
 * secuencia de tokens, mismos lexemas, mismas líneas y columnas, y los mismos
 * mensajes de error. `herramientas/lexer_paridad.py` compara ambos lexers
 * sobre todos los `.jp` del repositorio; si divergen, el CI avisa.
 *
 * Diferencias conocidas (deliberadas, documentadas):
 *  - Los dígitos y letras no ASCII se aceptan como letras de identificador
 *    (Python usa isalpha/isalnum y reconoce dígitos Unicode como números).
 *    En la práctica los identificadores de JP son latinos y los números
 *    árabes/índicos no aparecen en el código.
 */

#ifndef JP_LEXER_H
#define JP_LEXER_H

#include <stddef.h>

typedef enum {
    /* Signos de un carácter */
    T_PAREN_IZQ, T_PAREN_DER, T_LLAVE_IZQ, T_LLAVE_DER,
    T_CORCHETE_IZQ, T_CORCHETE_DER, T_COMA, T_PUNTO_Y_COMA, T_DOSPUNTOS,
    T_MAS, T_MENOS, T_POR, T_ENTRE, T_MODULO, T_PUNTO, T_IGUAL, T_MENOR, T_MAYOR,
    /* Signos de dos caracteres */
    T_IGUAL_IGUAL, T_DIFERENTE, T_MENOR_IGUAL, T_MAYOR_IGUAL, T_PUNTO_PUNTO,
    T_POTENCIA, T_DOBLE_INTERROGACION, T_INTERROGACION_PUNTO,
    T_MAS_IGUAL, T_MENOS_IGUAL, T_POR_IGUAL, T_ENTRE_IGUAL, T_MODULO_IGUAL,
    /* Literales */
    T_NUMERO, T_CADENA, T_CADENA_INI, T_CADENA_MEDIO, T_CADENA_FIN, T_IDENTIFICADOR,
    /* Palabras clave */
    T_VAR, T_FUN, T_RETORNA, T_SI, T_SINO, T_MIENTRAS, T_PARA, T_EN,
    T_VERDADERO, T_FALSO, T_NULO, T_Y, T_O, T_NO, T_ROMPER, T_CONTINUAR,
    T_ELEGIR, T_CASO, T_INTENTA, T_ATRAPA, T_FINALMENTE, T_LANZAR,
    T_IMPORTAR, T_CLASE, T_HEREDA,
    /* Especiales */
    T_FIN_DE_ARCHIVO
} JpTokenType;

typedef struct {
    JpTokenType tipo;
    char *lexema;    /* texto fuente exacto del token (UTF-8, terminado en NUL) */
    char *literal;   /* literal interpretado: texto de cadena, nombre de
                        identificador, "1"/"0" para verdadero/falso, o NULL */
    int linea;
    int columna;
    int es_entero;   /* 1 si es un número sin parte decimal */
    double numero;   /* valor de T_NUMERO */
} JpToken;

typedef struct {
    JpToken *datos;
    size_t n;
    size_t capacidad;
} JpTokens;

/* Nombre del token tal como lo nombra `jp/tokens.py` (para los volcados). */
const char *jp_token_nombre(JpTokenType tipo);

/* Tokeniza `fuente` (UTF-8, `largo` bytes). Devuelve 1 si todo fue bien y 0 si
 * hubo un error léxico; en ese caso escribe el mensaje en `error`. */
int jp_tokenizar(const char *fuente, size_t largo, JpTokens *salida,
                 char *error, size_t error_largo);

void jp_tokens_liberar(JpTokens *tokens);

#endif /* JP_LEXER_H */
