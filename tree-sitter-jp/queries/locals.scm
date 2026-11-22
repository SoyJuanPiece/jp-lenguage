; Ámbitos y definiciones locales de JP (para resaltar referencias y
; detectar sombreados en el editor).

; ---------- ámbitos ----------
(declaracion_funcion) @local.scope
(funcion_anonima) @local.scope
(bloque) @local.scope

; ---------- definiciones ----------
(parametro nombre: (identificador) @local.definition)
(declaracion_var nombre: (identificador) @local.definition)
(declaracion_var nombre: (lista (identificador) @local.definition))
(declaracion_funcion nombre: (identificador) @local.definition)
(declaracion_clase nombre: (identificador) @local.definition)
(sentencia_para variable: (identificador) @local.definition)
(sentencia_para valor: (identificador) @local.definition)
(sentencia_importar alias: (identificador) @local.definition)
(sentencia_intenta error: (identificador) @local.definition)

; ---------- referencias ----------
(identificador) @local.reference
