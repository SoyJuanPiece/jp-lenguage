; Resaltado de sintaxis de JP.
;
; Los nombres de nodo salen de grammar.js (ver src/node-types.json). Las
; reglas generales van al final: en tree-sitter gana la captura más
; específica, así que `(identificador) @variable` no pisa a un parámetro ni
; a una clave de diccionario.

; ---------- comentarios ----------
(comentario) @comment

; ---------- palabras clave ----------
[
  "var"
  "variable"
  "fun"
  "funcion"
  "función"
  "retorna"
  "devuelve"
  "si"
  "sino"
  "mientras"
  "para"
  "en"
  "elegir"
  "caso"
  "intenta"
  "atrapa"
  "finalmente"
  "lanzar"
  "importar"
  "como"
  "clase"
  "hereda"
  "romper"
  "continuar"
  "paso"
] @keyword

[
  "y"
  "o"
  "no"
] @keyword.operator

; ---------- literales ----------
(numero) @number
(cadena_simple) @string
(cadena_interpolada) @string
(booleano) @constant.builtin
(nulo) @constant.builtin

; ---------- tipos ----------
(tipo) @type.builtin
(declaracion_clase nombre: (identificador) @type)
(declaracion_clase padre: (identificador) @type)

; ---------- funciones ----------
(declaracion_funcion nombre: (identificador) @function)
(funcion_anonima) @function
(_ funcion: (identificador) @function.call)

(parametro nombre: (identificador) @variable.parameter)

; ---------- variables y propiedades ----------
(declaracion_var nombre: (identificador) @variable)
(declaracion_var nombre: (lista (identificador) @variable))

(_ objetivo: (identificador) @variable)
(_ objetivo: (lista (identificador) @variable))

(sentencia_para variable: (identificador) @variable)
(sentencia_para valor: (identificador) @variable)

(sentencia_intenta error: (identificador) @variable)

(_ clave: (identificador) @property)
(par clave: (identificador) @property)

(sentencia_importar alias: (identificador) @module)
(sentencia_importar ruta: (cadena_simple) @string.special)
(sentencia_importar ruta: (cadena_interpolada) @string.special)

; ---------- operadores y puntuación ----------
[
  "="
  "+="
  "-="
  "*="
  "/="
  "%="
  "+"
  "-"
  "*"
  "/"
  "%"
  "**"
  "=="
  "!="
  "<"
  ">"
  "<="
  ">="
  ".."
  "??"
  "?."
] @operator

[
  "."
  ","
  ":"
  ";"
] @punctuation.delimiter

[
  "("
  ")"
  "["
  "]"
  "{"
  "}"
] @punctuation.bracket

; ---------- genérico (siempre al final) ----------
(identificador) @variable
