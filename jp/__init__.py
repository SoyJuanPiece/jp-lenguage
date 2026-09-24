"""JP — un pequeño lenguaje de programación en español.

Módulos:
    tokens       — tipos de token y clase Token
    errores      — errores léxicos, de sintaxis y de ejecución
    lexer        — convierte el código fuente en tokens
    arbol        — nodos del árbol de sintaxis (AST)
    parser       — convierte tokens en un AST
    interprete   — ejecuta el AST
    cli          — línea de comandos y REPL
"""

__version__ = "0.5.0"
