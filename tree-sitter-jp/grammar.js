/**
 * Gramática tree-sitter de JP.
 *
 * Se deriva de `jp/lexer.py` y `jp/parser.py`, no de la documentación.
 *
 * Decisiones de diseño (y por qué):
 *
 *  - La cascada de precedencias del parser (`_rango` → `_por_defecto` → `_o`
 *    → …) se aplana en UNA regla con `prec`. El árbol resultante es el mismo
 *    para resaltar y plegar, y el autómata LR pasa de miles de estados a
 *    cientos. Una cascada de doce reglas ocultas no terminaba de generarse
 *    en Windows (se quedaba sin memoria).
 *
 *  - Las cadenas son tokens opacos. JP interpola con `{expresión}` dentro de
 *    las comillas dobles, pero modelar eso sin un *external scanner* mete al
 *    analizador léxico dentro de la expresión y multiplica los estados. Aquí
 *    la cadena entera se resalta como texto; el interior de `{...}` no se
 *    resalta por separado (pendiente: external scanner).
 *
 *  - La asignación es una sentencia, no un nivel de expresión.
 */

const PREC = {
  O: 1,
  Y: 2,
  IGUALDAD: 3,
  COMPARACION: 4,
  SUMA: 5,
  PRODUCTO: 6,
  POTENCIA: 7,
  UNARIO: 8,
  RANGO: 9,
  COALESCE: 10,
  POSTFIJO: 11,
};

const coma1 = (regla) => seq(regla, repeat(seq(',', regla)));

module.exports = grammar({
  name: 'jp',

  // El ';' es opcional en todas partes (el parser lo consume al final de cada
  // sentencia), así que aquí es un extra.
  extras: ($) => [/\s/, $.comentario, ';'],

  word: ($) => $.identificador,

  conflicts: ($) => [
    // `retorna` sin valor seguido de otra sentencia: JP se queda con la
    // expresión, y tree-sitter también prefiere shift.
    [$.sentencia_retorna],
    // Dangling else: `si a { } si b { } sino { }` cuelga del `si` interno.
    [$.sentencia_si],
    // `intenta` anidado en una línea: `finalmente` es del más interno.
    [$.sentencia_intenta],
  ],

  rules: {
    fuente: ($) => repeat($._sentencia),

    comentario: (_) => token(seq('#', /.*/)),

    // ---------- léxico ----------

    // El lexer de JP acepta cualquier letra Unicode (isalpha) y '_'.
    identificador: (_) => /(\p{L}|_)(\p{L}|\p{N}|_)*/,

    numero: (_) => token(seq(/[0-9]+/, optional(/\.[0-9]+/))),

    // Comillas simples: literal puro. Comillas dobles: pueden interpolar.
    cadena: ($) => choice($.cadena_simple, $.cadena_interpolada),
    cadena_simple: (_) => token(seq("'", repeat(choice(/[^'\\]/, /\\./)), "'")),
    cadena_interpolada: (_) => token(seq('"', repeat(choice(/[^"\\]/, /\\./)), '"')),

    booleano: (_) => choice('verdadero', 'falso'),
    nulo: (_) => 'nulo',

    // Los tipos anotables de `_TIPOS_ANOTABLES` en jp/parser.py.
    tipo: (_) => choice(
      'numero', 'entero', 'texto', 'booleano', 'lista', 'diccionario',
      'funcion', 'nulo', 'cualquiera',
    ),

    // ---------- sentencias ----------

    _sentencia: ($) => choice(
      $.declaracion_var,
      $.declaracion_funcion,
      $.declaracion_clase,
      $.sentencia_asignacion,
      $.sentencia_retorna,
      $.sentencia_romper,
      $.sentencia_continuar,
      $.sentencia_si,
      $.sentencia_elegir,
      $.sentencia_intenta,
      $.sentencia_lanzar,
      $.sentencia_importar,
      $.sentencia_mientras,
      $.sentencia_para,
      $.sentencia_expresion,
    ),

    // `variable x = 1`, `var x: numero`, `variable [a, b] = [1, 2]`
    declaracion_var: ($) => seq(
      choice('var', 'variable'),
      field('nombre', choice($.identificador, $.lista)),
      optional(seq(':', field('tipo', $.tipo))),
      optional(seq('=', field('valor', $._expresion))),
    ),

    // `fun nombre(a, b = 1): tipo { ... }`
    declaracion_funcion: ($) => seq(
      choice('fun', 'funcion', 'función'),
      field('nombre', $.identificador),
      field('parametros', $.parametros),
      optional(seq(':', field('tipo_retorno', $.tipo))),
      field('cuerpo', $.bloque),
    ),

    parametros: ($) => seq('(', optional(coma1($.parametro)), ')'),

    parametro: ($) => seq(
      field('nombre', $.identificador),
      optional(seq(':', field('tipo', $.tipo))),
      optional(seq('=', field('defecto', $._expresion))),
    ),

    declaracion_clase: ($) => seq(
      'clase',
      field('nombre', $.identificador),
      optional(seq('hereda', field('padre', $.identificador))),
      '{',
      repeat($.declaracion_funcion),
      '}',
    ),

    // `x = 1`, `x += 1`, `d.clave = 1`, `lista[i] = 1`, `[a, b] = [b, a]`
    //
    // `prec.dynamic` porque JP no separa sentencias: tras `imprime(x)` una
    // línea que empieza por `[a, b] =` podría leerse como un índice de la
    // llamada anterior. Con GLR se prueban las dos y gana la asignación.
    sentencia_asignacion: ($) => prec.dynamic(1, seq(
      field('objetivo', $._expresion),
      field('operador', choice('=', '+=', '-=', '*=', '/=', '%=')),
      field('valor', $._expresion),
    )),

    sentencia_retorna: ($) => seq(choice('retorna', 'devuelve'), optional($._expresion)),

    sentencia_romper: (_) => 'romper',
    sentencia_continuar: (_) => 'continuar',

    sentencia_lanzar: ($) => seq('lanzar', $._expresion),

    sentencia_importar: ($) => seq(
      'importar',
      field('ruta', $.cadena),
      optional(seq('como', field('alias', $.identificador))),
    ),

    sentencia_si: ($) => seq(
      'si',
      field('condicion', $._expresion),
      field('cuerpo', $._cuerpo),
      optional(seq('sino', choice($.sentencia_si, field('sino', $._cuerpo)))),
    ),

    sentencia_mientras: ($) => seq(
      'mientras',
      field('condicion', $._expresion),
      field('cuerpo', $._cuerpo),
    ),

    // `para i en 1..10`, `para i, v en lista`, con paréntesis opcionales.
    sentencia_para: ($) => seq(
      'para',
      optional('('),
      field('variable', $.identificador),
      optional(seq(',', field('valor', $.identificador))),
      'en',
      field('iterable', $._expresion),
      optional(')'),
      field('cuerpo', $._cuerpo),
    ),

    sentencia_elegir: ($) => seq(
      'elegir',
      field('valor', $._expresion),
      '{',
      repeat(choice($.caso, $.caso_sino)),
      '}',
    ),

    caso: ($) => seq('caso', field('valores', coma1($._expresion)), field('cuerpo', $._cuerpo)),
    caso_sino: ($) => seq('sino', field('cuerpo', $._cuerpo)),

    sentencia_intenta: ($) => seq(
      'intenta',
      field('cuerpo', $.bloque),
      optional(seq('atrapa', optional(field('error', $.identificador)), field('captura', $._cuerpo))),
      optional(seq('finalmente', field('finalmente', $._cuerpo))),
    ),

    _cuerpo: ($) => choice($.bloque, seq(':', $._sentencia)),

    bloque: ($) => seq('{', repeat($._sentencia), '}'),

    sentencia_expresion: ($) => $._expresion,

    // ---------- expresiones ----------

    _expresion: ($) => choice(
      prec.left(PREC.O, seq($._expresion, 'o', $._expresion)),
      prec.left(PREC.Y, seq($._expresion, 'y', $._expresion)),
      prec.left(PREC.IGUALDAD, seq($._expresion, choice('==', '!='), $._expresion)),
      prec.left(PREC.COMPARACION, seq($._expresion, choice('<', '>', '<=', '>='), $._expresion)),
      prec.left(PREC.SUMA, seq($._expresion, choice('+', '-'), $._expresion)),
      prec.left(PREC.PRODUCTO, seq($._expresion, choice('*', '/', '%'), $._expresion)),
      // '**' asocia a la derecha y liga más que el menos unario: -2 ** 2 = -4.
      prec.right(PREC.POTENCIA, seq($._expresion, '**', $._expresion)),
      // Rango inclusivo con paso opcional: `1..10 paso 2`.
      prec.left(PREC.RANGO, seq($._expresion, '..', $._expresion, optional(seq('paso', $._expresion)))),
      // `a ?? b`: asocia a la derecha.
      prec.right(PREC.COALESCE, seq($._expresion, '??', $._expresion)),
      prec(PREC.UNARIO, seq(choice('no', '-'), $._expresion)),
      prec.left(PREC.POSTFIJO, seq(field('funcion', $._expresion), field('argumentos', $.argumentos))),
      prec.left(PREC.POSTFIJO, seq($._expresion, '?.', $.argumentos)),
      // Precedencia negativa a propósito: JP no separa sentencias con
      // saltos de línea, así que tras `imprime(x)` una línea que empieza por `[a, b] =`
      // se leía como un índice de la llamada anterior y daba ERROR. Con el
      // índice por debajo de la reducción de sentencia, `[a, b] = ...`
      // empieza sentencia nueva y `lista[0]` sigue funcionando.
      prec.left(-1, seq($._expresion, '[', $._expresion, ']')),
      prec.left(PREC.POSTFIJO, seq($._expresion, choice('.', '?.'), field('clave', $.identificador))),
      $._primario,
    ),

    argumentos: ($) => seq('(', optional(coma1($._expresion)), ')'),

    _primario: ($) => choice(
      $.identificador,
      $.numero,
      $.cadena,
      $.booleano,
      $.nulo,
      $.lista,
      $.diccionario,
      $.funcion_anonima,
      seq('(', $._expresion, ')'),
    ),

    // `mapear(lista, funcion(x) { devuelve x * 2 })`
    funcion_anonima: ($) => seq(
      choice('fun', 'funcion', 'función'),
      field('parametros', $.parametros),
      optional(seq(':', field('tipo_retorno', $.tipo))),
      field('cuerpo', $.bloque),
    ),

    lista: ($) => seq('[', optional(coma1($._expresion)), ']'),

    diccionario: ($) => seq('{', optional(coma1($.par)), '}'),

    par: ($) => seq(
      field('clave', choice($.identificador, $.cadena)),
      ':',
      field('valor', $._expresion),
    ),
  },
});
