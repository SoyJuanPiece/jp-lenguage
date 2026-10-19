"""Paquetes para JP: el principio del ecosistema.

Un paquete es una carpeta con un `paquete.json`:

    {"nombre": "saludos", "version": "1.0.0", "principal": "principal.jp"}

Se instala con el CLI:

    jp --instalar github:usuario/repo[@rama]   # desde GitHub
    jp --instalar ./mi-paquete                 # desde una carpeta local
    jp --instalar                              # lo de paquete.json (dependencias)
    jp --paquetes                              # listar los instalados
    jp --quitar-paquete saludos

Y se usa como un modulo mas, con @ delante:

    importar "@saludos" como saludos
    imprime(saludos.saludar("Ana"))

Donde se buscan (en este orden): la carpeta `paquetes/` junto al archivo
que importa, `paquetes/` del directorio de trabajo, lo que diga la
variable de entorno JP_PAQUETES y `~/.jp/paquetes`.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .errores import ErrorEjecucion


def carpeta_global() -> Path:
    return Path.home() / ".jp" / "paquetes"


def directorios_paquetes(directorio_base: Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    if directorio_base is not None:
        dirs.append(Path(directorio_base) / "paquetes")
    dirs.append(Path.cwd() / "paquetes")
    entorno = os.environ.get("JP_PAQUETES")
    if entorno:
        dirs.extend(Path(p) for p in entorno.split(os.pathsep) if p)
    dirs.append(carpeta_global())
    unicos: list[Path] = []
    for d in dirs:
        if d not in unicos:
            unicos.append(d)
    return unicos


def _principal(carpeta: Path) -> Path | None:
    manifiesto = carpeta / "paquete.json"
    principal = "principal.jp"
    if manifiesto.is_file():
        try:
            datos = json.loads(manifiesto.read_text(encoding="utf-8"))
            if isinstance(datos, dict) and isinstance(datos.get("principal"), str):
                principal = datos["principal"]
        except ValueError:
            pass
    candidato = carpeta / principal
    return candidato if candidato.is_file() else None


def resolver_paquete(ruta_paquete: str, directorio_base: Path | None, linea: int = 0) -> Path:
    """'@saludos' o '@saludos/extra.jp' -> la ruta del archivo a importar."""
    limpio = ruta_paquete[1:]
    nombre, _, resto = limpio.partition("/")
    if not nombre:
        raise ErrorEjecucion("importar '@...' espera el nombre del paquete, ej: importar \"@saludos\"", linea)
    for carpeta in directorios_paquetes(directorio_base):
        base = carpeta / nombre
        if resto:
            candidato = base / resto
            if candidato.is_file():
                return candidato.resolve()
        elif base.is_file() and base.suffix == ".jp":
            return base.resolve()
        elif base.is_dir():
            principal = _principal(base)
            if principal is not None:
                return principal.resolve()
    raise ErrorEjecucion(
        f"el paquete '@{nombre}' no esta instalado (instala con: jp --instalar <origen>)",
        linea,
    )


def leer_manifiesto(carpeta: Path) -> dict:
    manifiesto = carpeta / "paquete.json"
    if manifiesto.is_file():
        try:
            datos = json.loads(manifiesto.read_text(encoding="utf-8"))
            if isinstance(datos, dict):
                return datos
        except ValueError:
            pass
    return {}


def _nombre_paquete(carpeta: Path, por_defecto: str) -> str:
    nombre = leer_manifiesto(carpeta).get("nombre")
    return nombre if isinstance(nombre, str) and nombre else por_defecto


def _descargar_github(usuario_repo: str, rama: str | None, destino: Path) -> str:
    """Descarga el zip de GitHub (sin necesitar git) y lo deja en destino."""
    if "/" not in usuario_repo:
        raise ErrorEjecucion(f"origen GitHub invalido: '{usuario_repo}' (esperaba usuario/repo)")
    partes = usuario_repo.split("/")
    if len(partes) < 2:
        raise ErrorEjecucion(f"origen GitHub invalido: '{usuario_repo}' (esperaba usuario/repo)")
    usuario, repo = partes[0], partes[1]
    subcarpeta = "/".join(partes[2:])  # github:u/r/paquetes/saludos -> la subcarpeta es el paquete
    ramas = [rama] if rama else ["main", "master"]
    ultimo_error: Exception | None = None
    for candidata in ramas:
        url = f"https://codeload.github.com/{usuario}/{repo}/zip/refs/heads/{candidata}"
        try:
            with urllib.request.urlopen(url, timeout=60) as respuesta:
                contenido = respuesta.read()
        except (urllib.error.URLError, OSError) as error:
            ultimo_error = error
            continue
        with zipfile.ZipFile(io.BytesIO(contenido)) as zipe:
            nombres = zipe.namelist()
            raiz = nombres[0].split("/")[0] if nombres else ""
            zipe.extractall(destino.parent)
            extraido = destino.parent / raiz
            origen = extraido / subcarpeta if subcarpeta else extraido
            if not origen.is_dir():
                shutil.rmtree(extraido, ignore_errors=True)
                raise ErrorEjecucion(f"el repo {usuario}/{repo} no tiene la carpeta '{subcarpeta}'")
            if destino.exists():
                shutil.rmtree(destino)
            origen.rename(destino)
            if subcarpeta:
                shutil.rmtree(extraido, ignore_errors=True)
        return _nombre_paquete(destino, repo)
    raise ErrorEjecucion(f"no pude descargar {usuario}/{repo} de GitHub: {ultimo_error}")


def instalar(origen: str, carpeta_destino: Path) -> str:
    """Instala un paquete y devuelve su nombre.

    Origen: 'github:usuario/repo[@rama]', una URL de GitHub, una carpeta
    local o un archivo .jp suelto.
    """
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    if origen.startswith("github:"):
        usuario_repo, _, rama = origen[len("github:"):].partition("@")
        nombre_repo = usuario_repo.split("/")[-1]
        destino = carpeta_destino / nombre_repo
        return _descargar_github(usuario_repo, rama or None, destino)
    if origen.startswith("https://github.com/"):
        resto = origen[len("https://github.com/"):].strip("/").removesuffix(".git")
        destino = carpeta_destino / resto.split("/")[-1]
        return _descargar_github(resto, None, destino)
    ruta = Path(origen).expanduser()
    if ruta.is_dir():
        nombre = _nombre_paquete(ruta, ruta.name)
        destino = carpeta_destino / nombre
        if destino.resolve() != ruta.resolve():
            if destino.exists():
                shutil.rmtree(destino)
            shutil.copytree(ruta, destino, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return nombre
    if ruta.is_file() and ruta.suffix == ".jp":
        nombre = ruta.stem
        carpeta = carpeta_destino / nombre
        carpeta.mkdir(exist_ok=True)
        shutil.copy2(ruta, carpeta / "principal.jp")
        return nombre
    raise ErrorEjecucion(f"no se que hacer con el origen '{origen}': usa github:usuario/repo o una carpeta local")


def instalar_dependencias(carpeta_proyecto: Path, carpeta_destino: Path) -> list[str]:
    """Instala lo declarado en el paquete.json del proyecto."""
    manifiesto = carpeta_proyecto / "paquete.json"
    if not manifiesto.is_file():
        raise ErrorEjecucion("no hay paquete.json aqui: crea uno con {\"dependencias\": {\"nombre\": \"github:usuario/repo\"}}")
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ErrorEjecucion(f"paquete.json no es JSON valido: {error}")
    dependencias = datos.get("dependencias") if isinstance(datos, dict) else None
    if not isinstance(dependencias, dict) or not dependencias:
        raise ErrorEjecucion("paquete.json no declara dependencias")
    instalados = []
    for origen in dependencias.values():
        if not isinstance(origen, str):
            raise ErrorEjecucion("cada dependencia debe ser un origen en texto")
        instalados.append(instalar(origen, carpeta_destino))
    return instalados


def listar(directorio_base: Path | None = None) -> list[tuple[str, str, Path]]:
    """[(nombre, version, carpeta)] de los paquetes visibles."""
    vistos: dict[str, tuple[str, str, Path]] = {}
    for carpeta in directorios_paquetes(directorio_base):
        if not carpeta.is_dir():
            continue
        for hijo in sorted(carpeta.iterdir()):
            if hijo.is_dir() and _principal(hijo) is not None:
                datos = leer_manifiesto(hijo)
                nombre = datos.get("nombre") if isinstance(datos.get("nombre"), str) else hijo.name
                version = datos.get("version") if isinstance(datos.get("version"), str) else "?"
                vistos.setdefault(nombre, (nombre, version, hijo))
            elif hijo.is_file() and hijo.suffix == ".jp":
                vistos.setdefault(hijo.stem, (hijo.stem, "?", hijo))
    return sorted(vistos.values())


def quitar(nombre: str) -> Path | None:
    for carpeta in directorios_paquetes():
        destino = carpeta / nombre
        if destino.is_dir():
            shutil.rmtree(destino)
            return destino
        suelto = carpeta / f"{nombre}.jp"
        if suelto.is_file():
            suelto.unlink()
            return suelto
    return None
