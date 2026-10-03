#!/usr/bin/env python3
"""
importador.py — Importación masiva de premisas desde ficheros .txt o texto pegado.

Pensado para usuarios no técnicos: recibe el contenido en bruto (bytes de un
fichero subido o texto pegado en el navegador), lo limpia, y devuelve un
resumen *antes* de escribir nada. El portal muestra ese resumen, el usuario
confirma, y sólo entonces se aplica.

Reglas de limpieza (decididas con el usuario):
  - Decodifica UTF-8 (con o sin BOM); si falla, reintenta CP1252 y Latin-1,
    que es lo que sueltan Word y el Notepad antiguo de Windows.
  - Normaliza CRLF/CR, espacios duros (NBSP) y caracteres de ancho cero.
  - Descarta líneas en blanco y recorta espacios sobrantes.
  - Elimina repetidas (dentro del propio archivo y, al añadir, las que ya
    estuvieran en el perfil) comparando sin distinguir mayúsculas ni espacios
    múltiples.
  - NO toca la puntuación: el Generador ya recorta la final al cargar.

Antes de sobrescribir cualquier .txt se guarda una copia `<tipo>.txt.bak`,
lo que permite un "deshacer" de un nivel desde el propio portal.
"""

import os
import re
import shutil
import tempfile
import threading
import unicodedata

TIPOS  = ['detonantes', 'protagonistas', 'conflictos']
LABELS = {'detonantes': 'Detonantes', 'protagonistas': 'Protagonistas',
          'conflictos': 'Conflictos'}

# Límites: la Pi Zero 2W tiene 512 MB, así que acotamos lo que puede llegar.
MAX_LINEAS         = 5000   # por categoría
MAX_LONGITUD_LINEA = 300    # caracteres
MAX_LONGITUD_SLUG  = 32     # caracteres del nombre de carpeta del perfil

_lock = threading.Lock()

# Registro de la última importación aplicada, para el botón "Deshacer".
_ultima = None


# ------------------------------------------------------------------ #
# Decodificación y limpieza                                           #
# ------------------------------------------------------------------ #
def decodificar(datos) -> str:
    """Bytes de un .txt → str. Prueba UTF-8 (con BOM), luego los encodings
    típicos de Windows. Nunca lanza: en el peor caso sustituye lo ilegible."""
    if isinstance(datos, str):
        return datos
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return datos.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return datos.decode('utf-8', errors='replace')


def _clave(texto: str) -> str:
    """Clave de comparación para detectar repetidas: ignora mayúsculas y
    espacios múltiples, pero respeta tildes (á y a son palabras distintas)."""
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def limpiar(bruto) -> dict:
    """Contenido en bruto → líneas listas para guardar, con el detalle de lo
    que se ha descartado para poder explicárselo al usuario."""
    texto = decodificar(bruto)

    # Espacio duro y caracteres de ancho cero (habituales al pegar desde web/Word)
    texto = (texto.replace(' ', ' ')
                  .replace('​', '')
                  .replace('﻿', ''))
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')

    lineas, vistas = [], set()
    vacias = repetidas = largas = 0
    truncado = False

    for cruda in texto.split('\n'):
        linea = ''.join(c for c in cruda if c == '\t' or not unicodedata.category(c).startswith('C'))
        linea = re.sub(r'[ \t]+', ' ', linea).strip()
        if not linea:
            vacias += 1
            continue
        if len(linea) > MAX_LONGITUD_LINEA:
            largas += 1
            continue
        k = _clave(linea)
        if k in vistas:
            repetidas += 1
            continue
        if len(lineas) >= MAX_LINEAS:
            truncado = True
            break
        vistas.add(k)
        lineas.append(linea)

    return {'lineas': lineas, 'vacias': vacias, 'repetidas': repetidas,
            'largas': largas, 'truncado': truncado}


# ------------------------------------------------------------------ #
# Nombres de perfil                                                   #
# ------------------------------------------------------------------ #
def slug_perfil(nombre: str) -> str:
    """'1º ESO — Grupo B' → '1_eso_grupo_b'. Devuelve '' si no queda nada
    utilizable, para que la capa web dé un error comprensible."""
    s = unicodedata.normalize('NFKD', (nombre or '').strip())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[\s./\\]+', '_', s)
    s = re.sub(r'[^a-z0-9_-]', '', s)
    s = re.sub(r'_+', '_', s).strip('_-')
    return s[:MAX_LONGITUD_SLUG]


# ------------------------------------------------------------------ #
# Lectura / escritura de los .txt de un perfil                        #
# ------------------------------------------------------------------ #
def _ruta_tipo(perfiles_dir, perfil, tipo):
    """Ruta del .txt, con guard de path traversal: el resultado tiene que
    quedar dentro de perfiles_dir."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo no válido: {tipo}")
    base = os.path.abspath(perfiles_dir)
    ruta = os.path.abspath(os.path.join(base, perfil, f"{tipo}.txt"))
    if not ruta.startswith(base + os.sep):
        raise ValueError(f"Perfil no válido: {perfil}")
    return ruta


def leer(perfiles_dir, perfil, tipo) -> list:
    ruta = _ruta_tipo(perfiles_dir, perfil, tipo)
    if not os.path.exists(ruta):
        return []
    with open(ruta, 'rb') as f:
        return [l for l in (x.strip() for x in decodificar(f.read()).split('\n')) if l]


def _escribir(ruta, lineas):
    """Escritura atómica: temporal + rename, igual que config_manager."""
    directorio = os.path.dirname(ruta)
    fd, tmp = tempfile.mkstemp(dir=directorio, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lineas) + ('\n' if lineas else ''))
        os.replace(tmp, ruta)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def crear_perfil(perfiles_dir, nombre_slug):
    """Crea la carpeta del perfil con los tres .txt vacíos."""
    base = os.path.abspath(perfiles_dir)
    ruta = os.path.abspath(os.path.join(base, nombre_slug))
    if not ruta.startswith(base + os.sep):
        raise ValueError("Nombre de perfil no válido")
    if os.path.exists(ruta):
        raise FileExistsError("Ya existe ese perfil")
    os.makedirs(ruta)
    for tipo in TIPOS:
        open(os.path.join(ruta, f'{tipo}.txt'), 'w').close()
    return ruta


# ------------------------------------------------------------------ #
# Análisis (previsualización) y aplicación                            #
# ------------------------------------------------------------------ #
def analizar(perfiles_dir, perfil, entradas, modo='anadir', perfil_nuevo=False) -> dict:
    """Calcula qué pasaría al importar, sin escribir nada.

    entradas: {tipo: bytes|str} — sólo las categorías que el usuario rellenó.
    modo:     'anadir' (al final) o 'reemplazar' (sustituye la lista entera).

    Devuelve {'detalle': {tipo: {...}}, 'modo': ..., 'hay_algo': bool,
              'finales': {tipo: n}, 'vacias': [tipos que quedarían a cero]}
    """
    detalle = {}
    for tipo in TIPOS:
        if tipo not in entradas:
            continue
        limpio = limpiar(entradas[tipo])
        actuales = [] if perfil_nuevo else leer(perfiles_dir, perfil, tipo)

        if modo == 'reemplazar' or perfil_nuevo:
            nuevas, ya_estaban = limpio['lineas'], 0
            final = list(nuevas)
        else:
            existentes = {_clave(l) for l in actuales}
            nuevas, ya_estaban = [], 0
            for l in limpio['lineas']:
                if _clave(l) in existentes:
                    ya_estaban += 1
                else:
                    nuevas.append(l)
            final = actuales + nuevas

        detalle[tipo] = {
            'aportadas':  len(limpio['lineas']) + limpio['repetidas'],
            'repetidas':  limpio['repetidas'],
            'ya_estaban': ya_estaban,
            'largas':     limpio['largas'],
            'truncado':   limpio['truncado'],
            'nuevas':     nuevas,
            'actuales':   len(actuales),
            'eliminadas': len(actuales) if (modo == 'reemplazar' and not perfil_nuevo) else 0,
            'resultantes': len(final),
            'final':      final,
            'muestra':    nuevas[:6],
        }

    # Cómo queda cada categoría, incluidas las que el usuario no ha tocado.
    # El Generador exige las tres con contenido, así que el portal avisa si
    # alguna se queda a cero.
    finales = {}
    for tipo in TIPOS:
        if tipo in detalle:
            finales[tipo] = detalle[tipo]['resultantes']
        elif perfil_nuevo:
            finales[tipo] = 0
        else:
            finales[tipo] = len(leer(perfiles_dir, perfil, tipo))

    hay_algo = any(d['nuevas'] or d['eliminadas'] for d in detalle.values())
    return {'detalle': detalle, 'modo': modo, 'hay_algo': hay_algo,
            'finales': finales,
            'vacias': [t for t in TIPOS if finales[t] == 0]}


def aplicar(perfiles_dir, perfil, analisis) -> dict:
    """Escribe los .txt afectados, guardando antes `<tipo>.txt.bak`.
    Las categorías que el usuario dejó vacías no se tocan."""
    global _ultima
    tocados = {}
    with _lock:
        for tipo, d in analisis['detalle'].items():
            if not d['nuevas'] and not d['eliminadas']:
                continue
            ruta = _ruta_tipo(perfiles_dir, perfil, tipo)
            if os.path.exists(ruta):
                shutil.copy2(ruta, ruta + '.bak')
            _escribir(ruta, d['final'])
            tocados[tipo] = {'anadidas': len(d['nuevas']),
                             'eliminadas': d['eliminadas'],
                             'total': d['resultantes']}
        _ultima = {'perfil': perfil, 'tipos': list(tocados.keys())} if tocados else None
    return tocados


def hay_deshacer(perfiles_dir, perfil=None) -> bool:
    with _lock:
        if not _ultima:
            return False
        if perfil is not None and _ultima['perfil'] != perfil:
            return False
        return any(os.path.exists(_ruta_tipo(perfiles_dir, _ultima['perfil'], t) + '.bak')
                   for t in _ultima['tipos'])


def deshacer(perfiles_dir) -> dict:
    """Restaura los .bak de la última importación aplicada. Un solo nivel:
    al restaurar se consume la copia."""
    global _ultima
    with _lock:
        if not _ultima:
            return {'ok': False, 'error': 'No hay ninguna importación reciente que deshacer.'}
        perfil, restaurados = _ultima['perfil'], []
        for tipo in _ultima['tipos']:
            ruta = _ruta_tipo(perfiles_dir, perfil, tipo)
            bak  = ruta + '.bak'
            if os.path.exists(bak):
                os.replace(bak, ruta)       # atómico; consume la copia
                restaurados.append(tipo)
        _ultima = None
        if not restaurados:
            return {'ok': False, 'error': 'Las copias de seguridad ya no están disponibles.'}
        return {'ok': True, 'perfil': perfil, 'tipos': restaurados}
