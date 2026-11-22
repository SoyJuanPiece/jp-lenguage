# JP en 20 minutos

Un recorrido por el lenguaje, de cero a clases, sin experiencia previa en
programación. Todos los bloques de esta página son programas completos: se
guardan en un archivo `.jp` y se ejecutan.

```bash
python -m jp programa.jp
```

Si prefieres probar sin escribir archivos:

```bash
python -m jp -c 'imprime("hola")'
```

---

## 1. Lo primero

```jp
imprime("Hola, mundo")
```

`imprime` muestra por pantalla. `muestra` hace exactamente lo mismo: el
lenguaje acepta las dos palabras porque mucha gente empieza escribiendo una u
otra.

## 2. Variables

```jp
variable nombre = "Ana"
var edad = 30
variable saldo: numero = 12.5
variable pendiente = nulo

imprime(nombre, edad, saldo, pendiente)
```

- `variable` y `var` son sinónimos.
- El tipo (`: numero`) es **opcional**: sirve para dejar claro qué esperas y
  para que el revisor avise si se lo pasas mal.
- `nulo` es la ausencia de valor, como `null` en otros lenguajes.

## 3. Texto

```jp
variable nombre = "Maturín"
variable edad = 30

imprime("Hola, {nombre}: tienes {edad} años")
imprime(longitud(nombre))
imprime(mayusculas(nombre))
```

Las comillas dobles permiten meter expresiones entre llaves: `{nombre}`,
`{edad * 2}`, `{saludar("Ana")}`. Las comillas simples son texto puro, sin
interpolación: `'esto es {literal}'`.

`longitud("Maturín")` da **7**, no 8: JP cuenta letras, no bytes. Y
`mayusculas("ñandú")` da `ÑANDÚ`.

## 4. Números y rangos

```jp
imprime(2 ** 10)
imprime(7 / 2)
imprime(7 % 2)

para i en 1..5 {
    imprime(i)
}

para i en 1..10 paso 3 {
    imprime(i)
}
```

`1..5` es un rango **inclusivo**: 1, 2, 3, 4 y 5. Con `paso 3` salta de tres
en tres. También funciona al revés: `5..1`.

## 5. Decisiones

```jp
variable edad = 20

si edad >= 18 {
    imprime("mayor de edad")
} sino {
    imprime("menor de edad")
}

si 1 < 2: imprime("una sola línea, con dos puntos")

elegir edad {
    caso 18 { imprime("acabas de cumplir 18") }
    caso 20, 21 { imprime("veinteañero") }
    sino { imprime("otra edad") }
}
```

Los paréntesis de la condición son opcionales. `elegir` no tiene caída entre
casos: entra en el primero que coincida y sale.

## 6. Bucles

```jp
variable i = 0
mientras i < 3 {
    imprime(i)
    i += 1
}

variable letras = ["a", "b", "c"]
para posicion, letra en letras {
    imprime(posicion, letra)
}
```

`romper` sale del bucle y `continuar` salta a la siguiente vuelta.

## 7. Listas y diccionarios

```jp
variable frutas = ["pera", "manzana"]
agregar(frutas, "kiwi")

imprime(frutas)
imprime(frutas[0])
imprime(longitud(frutas))

variable persona = {nombre: "Ana", edad: 30}
imprime(persona.nombre)

persona.edad = 31
imprime(persona["edad"])
```

Las listas empiezan en 0. Los diccionarios se leen con punto (`persona.edad`)
o con corchetes (`persona["edad"]`).

## 8. Funciones

```jp
funcion saludar(nombre = "mundo") {
    devuelve "Hola, " + nombre
}

imprime(saludar())
imprime(saludar("Ana"))

variable dobles = mapear([1, 2, 3], funcion(x) { devuelve x * 2 })
imprime(dobles)
```

- Los parámetros pueden tener valor por defecto.
- `funcion(x) { ... }` sin nombre es una función como valor: se pasa a
  `mapear`, `filtrar` o `reducir` como cualquier otro dato.

## 9. Clases

```jp
clase Persona {
    funcion iniciar(nombre) {
        este.nombre = nombre
    }

    funcion saludar() {
        devuelve "Hola, soy " + este.nombre
    }
}

clase Empleado hereda Persona {
    funcion saludar() {
        devuelve "Soy " + este.nombre + " y trabajo aquí"
    }
}

variable ana = Persona("Ana")
imprime(ana.saludar())

variable luis = Empleado("Luis")
imprime(luis.saludar())
```

El constructor se llama `iniciar`, y `este` es el objeto actual (`self` en
Python, `this` en JavaScript). Si la clase hija define un método con el mismo
nombre, gana el de la hija.

## 10. Errores

```jp
intenta {
    lanzar "algo salió mal"
} atrapa error {
    imprime("capturado:", error)
} finalmente {
    imprime("esto se ejecuta siempre")
}
```

`finalmente` es opcional, `atrapa` también (puedes usar solo uno de los dos).
Un error no capturado muestra la línea y una flecha `^` señalando el problema.

## 11. Varios archivos

En un archivo `utilidades.jp`:

```
funcion doble(n) {
    devuelve n * 2
}
```

En `programa.jp`, al lado:

```
importar "utilidades.jp" como util

imprime(util.doble(2))
```

Cada archivo importado tiene su propio espacio de nombres (o el alias que le
des con `como`).

## 12. Y ahora qué

- **Referencia completa**: [`referencia.md`](referencia.md), con las 149
  funciones de la biblioteca estándar.
- **Programas reales**: en `ejemplos/` hay desde un ahorcado hasta un bot de
  Telegram y un servidor web.
- **Editor**: `jp lsp` arranca el servidor de lenguaje (diagnósticos,
  autocompletado y ayuda) para VS Code, Neovim o Zed.
- **Comprobar sin ejecutar**: `python -m jp --check programa.jp`.
- **Formatear**: `python -m jp --formatear programa.jp` (ojo: pierde los
  comentarios).
