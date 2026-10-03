#!/usr/bin/env python3
"""
portal.py — Interfaz web de gestión StoryMaker.
Rutas:
  /             → panel principal (requiere login)
  /login        → formulario PIN
  /logout
  /setup        → configuración de hardware (primer arranque)
  /perfil/<n>/<tipo>  → ver/editar premisas
  /importar     → importar premisas en bloque desde .txt (3 pasos)
  /api/*        → endpoints JSON
Se lanza en un hilo separado (daemon) para no bloquear main.py.
"""
import html
import os
import secrets
import tempfile
import threading
import time
from functools import wraps
from flask import Flask, request, session, redirect, url_for, jsonify
from modules.config_manager import cargar_config, guardar_config
from modules import importador

BASE_DIR     = os.path.join(os.path.dirname(__file__), '..')
PERFILES_DIR = os.path.join(BASE_DIR, 'data', 'perfiles')
PIN_DEFAULT  = "1234"

app = Flask(__name__)
# Secret temporal hasta que Portal.__init__ cargue el valor persistente de config.json
app.secret_key = secrets.token_hex(32)

# Tope de subida para la importación de premisas. 3 MB son decenas de miles de
# frases; el límite está para que un archivo enorme no agote la RAM de la Pi Zero.
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024

# Callback de generación registrado desde main.py
_callback_generar = None

def registrar_callback_generar(cb):
    global _callback_generar
    _callback_generar = cb

_callback_despedida = None

def registrar_callback_despedida(cb):
    global _callback_despedida
    _callback_despedida = cb

_callback_cambiar_perfil = None

def registrar_callback_cambiar_perfil(cb):
    global _callback_cambiar_perfil
    _callback_cambiar_perfil = cb

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #
def get_perfiles():
    ruta = os.path.abspath(PERFILES_DIR)
    if not os.path.exists(ruta):
        return []
    return sorted([d for d in os.listdir(ruta) if os.path.isdir(os.path.join(ruta, d))])

def get_premisas(perfil, tipo):
    ruta = os.path.abspath(os.path.join(PERFILES_DIR, perfil, f"{tipo}.txt"))
    if not os.path.exists(ruta):
        return []
    with open(ruta, 'r', encoding='utf-8') as f:
        return [l.strip() for l in f if l.strip()]

def guardar_premisas(perfil, tipo, premisas):
    """Escritura atómica: escribe en temporal y renombra.
    Evita corrupción si la SD se llena o el sistema pierde alimentación a mitad."""
    ruta = os.path.abspath(os.path.join(PERFILES_DIR, perfil, f"{tipo}.txt"))
    directorio = os.path.dirname(ruta)
    fd, tmp = tempfile.mkstemp(dir=directorio, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(premisas) + ('\n' if premisas else ''))
        os.replace(tmp, ruta)       # atómico en Linux
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def login_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('autenticado'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ------------------------------------------------------------------ #
# Auth                                                                #
# ------------------------------------------------------------------ #
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    config = cargar_config()
    if request.method == 'POST':
        if request.form.get('pin') == config.get('pin', PIN_DEFAULT):
            session['autenticado'] = True
            if not config.get('setup_completado', False):
                return redirect(url_for('setup'))
            return redirect(url_for('index'))
        error = "PIN incorrecto"
    primer_arranque = not config.get('setup_completado', False)
    return _render_login(error, primer_arranque)

@app.route('/api/generar', methods=['POST'])
@login_requerido
def api_generar():
    if _callback_generar is None:
        return jsonify({'ok': False, 'error': 'Sistema no listo'})
    try:
        threading.Thread(target=_callback_generar, daemon=True).start()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ------------------------------------------------------------------ #
# Setup de hardware                                                   #
# ------------------------------------------------------------------ #
@app.route('/setup', methods=['GET', 'POST'])
@login_requerido
def setup():
    config = cargar_config()
    if request.method == 'POST':
        hw = config.setdefault('hardware', {})
        eink_desactivada = 'eink' not in request.form
        hw.setdefault('eink', {})['activada'] = 'eink' in request.form
        hw.setdefault('impresora', {})['activada'] = 'impresora' in request.form
        if request.form.get('baudrate'):
            hw['impresora']['baudrate'] = int(request.form['baudrate'])
        hw.setdefault('audio', {})['activada'] = 'audio' in request.form
        if request.form.get('volumen'):
            hw['audio']['volumen'] = max(0, min(100, int(request.form['volumen'])))
        nuevo_pin = request.form.get('nuevo_pin', '').strip()
        if nuevo_pin and nuevo_pin.isdigit() and 4 <= len(nuevo_pin) <= 8:
            config['pin'] = nuevo_pin
        config['setup_completado'] = True
        guardar_config(config)
        if eink_desactivada and _callback_despedida:
            _callback_despedida()
        import subprocess
        subprocess.Popen(
            ['sudo', 'systemctl', 'restart', 'historias.service'],
            start_new_session=True
        )
        return redirect(url_for('index'))
    hw = config.get('hardware', {})
    return _render_setup(hw, config)

# ------------------------------------------------------------------ #
# Panel principal                                                     #
# ------------------------------------------------------------------ #
@app.route('/')
@login_requerido
def index():
    config = cargar_config()
    if not config.get('setup_completado', False):
        return redirect(url_for('setup'))
    return _render_pagina(get_perfiles(), config.get('perfil_activo', ''), None, None, config)

@app.route('/perfil/<nombre>')
@login_requerido
def ver_perfil(nombre):
    config = cargar_config()
    if nombre not in get_perfiles():
        return redirect(url_for('index'))
    return _render_pagina(get_perfiles(), config.get('perfil_activo', ''), nombre, None, config)

@app.route('/perfil/<nombre>/<tipo>')
@login_requerido
def ver_premisas(nombre, tipo):
    config = cargar_config()
    if nombre not in get_perfiles() or tipo not in ['detonantes', 'protagonistas', 'conflictos']:
        return redirect(url_for('index'))
    premisas = get_premisas(nombre, tipo)
    return _render_pagina(get_perfiles(), config.get('perfil_activo', ''), nombre, tipo, config, premisas)

# ------------------------------------------------------------------ #
# API JSON                                                            #
# ------------------------------------------------------------------ #
@app.route('/api/anadir_premisa', methods=['POST'])
@login_requerido
def anadir_premisa():
    data   = request.get_json()
    perfil = data.get('perfil')
    tipo   = data.get('tipo')
    texto  = data.get('texto', '').strip()
    if not perfil or not tipo or not texto:
        return jsonify({'ok': False, 'error': 'Datos incompletos'})
    if tipo not in ['detonantes', 'protagonistas', 'conflictos']:
        return jsonify({'ok': False, 'error': 'Tipo no válido'})
    if perfil not in get_perfiles():
        return jsonify({'ok': False, 'error': 'Perfil no encontrado'})
    premisas = get_premisas(perfil, tipo)
    if texto in premisas:
        return jsonify({'ok': False, 'error': 'Esa premisa ya existe'})
    premisas.append(texto)
    guardar_premisas(perfil, tipo, premisas)
    return jsonify({'ok': True, 'total': len(premisas)})

@app.route('/api/borrar_premisa', methods=['POST'])
@login_requerido
def borrar_premisa():
    data   = request.get_json()
    perfil = data.get('perfil')
    tipo   = data.get('tipo')
    indice = data.get('indice')
    if perfil is None or tipo is None or indice is None:
        return jsonify({'ok': False, 'error': 'Datos incompletos'})
    if tipo not in ['detonantes', 'protagonistas', 'conflictos']:
        return jsonify({'ok': False, 'error': 'Tipo no válido'})
    if perfil not in get_perfiles():
        return jsonify({'ok': False, 'error': 'Perfil no encontrado'})
    premisas = get_premisas(perfil, tipo)
    if indice < 0 or indice >= len(premisas):
        return jsonify({'ok': False, 'error': 'Índice fuera de rango'})
    premisas.pop(indice)
    guardar_premisas(perfil, tipo, premisas)
    return jsonify({'ok': True, 'total': len(premisas)})

@app.route('/api/cambiar_perfil', methods=['POST'])
@login_requerido
def cambiar_perfil():
    data   = request.get_json()
    perfil = data.get('perfil')
    if perfil not in get_perfiles():
        return jsonify({'ok': False, 'error': 'Perfil no encontrado'})
    config = cargar_config()
    config['perfil_activo'] = perfil
    guardar_config(config)
    if _callback_cambiar_perfil:
        threading.Thread(target=_callback_cambiar_perfil,
                         args=(perfil,), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/guardar_hardware', methods=['POST'])
@login_requerido
def guardar_hardware():
    data   = request.get_json()
    config = cargar_config()
    hw     = config.setdefault('hardware', {})
    for clave in ['eink', 'impresora', 'audio']:
        if clave in data:
            hw.setdefault(clave, {})['activada'] = bool(data[clave])
    guardar_config(config)
    return jsonify({'ok': True})

@app.route('/api/estado')
@login_requerido
def estado():
    config = cargar_config()
    hw     = config.get('hardware', {})
    return jsonify({
        'perfil_activo': config.get('perfil_activo'),
        'setup_completado': config.get('setup_completado', False),
        'hardware': {
            'eink':      hw.get('eink',      {}).get('activada', False),
            'impresora': hw.get('impresora', {}).get('activada', False),
            'audio':     hw.get('audio',     {}).get('activada', False),
        }
    })

@app.route('/api/guardar_volumen', methods=['POST'])
@login_requerido
def guardar_volumen():
    data = request.get_json()
    volumen = data.get('volumen')
    if volumen is None or not isinstance(volumen, (int, float)):
        return jsonify({'ok': False, 'error': 'Volumen no válido'})
    volumen = max(0, min(100, int(volumen)))
    config = cargar_config()
    config.setdefault('hardware', {}).setdefault('audio', {})['volumen'] = volumen
    guardar_config(config)
    return jsonify({'ok': True, 'volumen': volumen})

@app.route('/api/reset_fabrica', methods=['POST'])
@login_requerido
def reset_fabrica():
    config = cargar_config()
    config['setup_completado'] = False
    config['pin'] = PIN_DEFAULT
    guardar_config(config)
    def _restart():
        import time as _t
        _t.sleep(1)
        import subprocess as _sp
        _sp.run(['sudo', 'systemctl', 'restart', 'historias.service'], check=False)
    threading.Thread(target=_restart, daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/apagar', methods=['POST'])
@login_requerido
def apagar():
    def _secuencia():
        if _callback_despedida:
            try:
                _callback_despedida()
            except Exception:
                pass
        import subprocess as _sp
        _sp.run(['sudo', 'shutdown', '-h', 'now'], check=False)
    threading.Thread(target=_secuencia, daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/nuevo_perfil', methods=['POST'])
@login_requerido
def nuevo_perfil():
    data   = request.get_json()
    nombre = importador.slug_perfil(data.get('nombre', ''))
    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre no válido: usa letras o números'})
    try:
        # crear_perfil incluye el guard de path traversal y crea los tres .txt vacíos
        importador.crear_perfil(PERFILES_DIR, nombre)
    except FileExistsError:
        return jsonify({'ok': False, 'error': 'Ya existe ese perfil'})
    except (ValueError, OSError) as e:
        return jsonify({'ok': False, 'error': str(e)})
    return jsonify({'ok': True, 'perfil': nombre})

# ------------------------------------------------------------------ #
# Importación de premisas desde .txt                                  #
# ------------------------------------------------------------------ #
# El flujo tiene tres pantallas para que nadie sobrescriba nada sin verlo:
#   1. /importar            → formulario (destino, modo, los tres textos)
#   2. /importar/revisar    → resumen de lo que va a pasar (no escribe nada)
#   3. /importar/confirmar  → aplica y ofrece deshacer
# Entre el paso 2 y el 3 el análisis se guarda en memoria, atado a la sesión.
_IMPORT_TTL   = 900          # segundos que vive una revisión sin confirmar
_importaciones = {}
_imp_lock      = threading.Lock()


def _sid():
    if 'sid' not in session:
        session['sid'] = secrets.token_hex(8)
    return session['sid']


def _guardar_pendiente(datos):
    token, ahora, sid = secrets.token_urlsafe(16), time.time(), _sid()
    with _imp_lock:
        caducados = [k for k, v in _importaciones.items()
                     if ahora - v['ts'] > _IMPORT_TTL or v['sid'] == sid]
        for k in caducados:
            _importaciones.pop(k, None)
        _importaciones[token] = {'ts': ahora, 'sid': sid, 'datos': datos}
    return token


def _recuperar_pendiente(token):
    with _imp_lock:
        p = _importaciones.get(token)
        if not p or p['sid'] != _sid() or time.time() - p['ts'] > _IMPORT_TTL:
            return None
        return p['datos']


def _descartar_pendiente(token):
    with _imp_lock:
        _importaciones.pop(token, None)


@app.route('/importar')
@login_requerido
def importar():
    config = cargar_config()
    if not config.get('setup_completado', False):
        return redirect(url_for('setup'))
    activo  = config.get('perfil_activo', '')
    destino = request.args.get('perfil') or activo
    return _render_importar(get_perfiles(), activo, destino)


@app.route('/importar/revisar', methods=['POST'])
@login_requerido
def importar_revisar():
    config   = cargar_config()
    perfiles = get_perfiles()
    activo   = config.get('perfil_activo', '')
    form     = request.form

    modo = form.get('modo', 'anadir')
    if modo not in ('anadir', 'reemplazar'):
        modo = 'anadir'
    activar = form.get('activar') == 'si'

    error, perfil, nuevo = None, '', False
    if form.get('destino') == 'nuevo':
        slug = importador.slug_perfil(form.get('nombre_nuevo', ''))
        if not slug:
            error = ('Escribe un nombre para el perfil nuevo. Vale cualquier cosa con '
                     'letras o números: «2 ESO», «Taller de verano»...')
        elif slug in perfiles:
            error = (f'Ya existe un perfil llamado «{slug.upper()}». Elige otro nombre, '
                     'o importa sobre ese perfil desde la opción de arriba.')
        else:
            perfil, nuevo, modo = slug, True, 'anadir'
    else:
        perfil = form.get('perfil', '')
        if perfil not in perfiles:
            error = 'Elige un perfil de la lista de destino.'

    entradas = {}
    if not error:
        for tipo in importador.TIPOS:
            trozos = []
            fichero = request.files.get(f'archivo_{tipo}')
            if fichero and fichero.filename:
                datos = fichero.read()
                if datos:
                    trozos.append(importador.decodificar(datos))
            pegado = form.get(f'texto_{tipo}', '')
            if pegado.strip():
                trozos.append(pegado)
            if trozos:
                entradas[tipo] = '\n'.join(trozos)
        if not entradas:
            error = ('No has añadido ningún texto. Sube al menos un archivo .txt o pega '
                     'una lista en alguna de las tres casillas.')

    if error:
        return _render_importar(perfiles, activo, perfil or form.get('perfil', ''),
                                error=error, form=form)

    try:
        analisis = importador.analizar(PERFILES_DIR, perfil, entradas, modo, nuevo)
    except ValueError as e:
        return _render_importar(perfiles, activo, '', error=str(e), form=form)

    if not analisis['hay_algo']:
        return _render_importar(
            perfiles, activo, perfil, form=form,
            error=('Todas las frases que traes estaban ya en el perfil, así que no hay '
                   'nada nuevo que guardar.'))

    token = _guardar_pendiente({'perfil': perfil, 'nuevo': nuevo, 'modo': modo,
                                'activar': activar, 'analisis': analisis})
    return _render_revision(token, perfil, nuevo, modo, activar, analisis, activo)


@app.route('/importar/confirmar', methods=['POST'])
@login_requerido
def importar_confirmar():
    config   = cargar_config()
    perfiles = get_perfiles()
    activo   = config.get('perfil_activo', '')
    token    = request.form.get('token', '')
    pendiente = _recuperar_pendiente(token)
    if not pendiente:
        return _render_importar(
            perfiles, activo, activo,
            error=('La revisión ha caducado o se ha perdido. Vuelve a elegir los archivos; '
                   'no se ha guardado ni modificado nada.'))

    perfil, nuevo = pendiente['perfil'], pendiente['nuevo']
    if nuevo and perfil in perfiles:
        return _render_importar(
            perfiles, activo, activo,
            error=f'Mientras revisabas se creó un perfil llamado «{perfil.upper()}». Elige otro nombre.')
    if not nuevo and perfil not in perfiles:
        return _render_importar(perfiles, activo, activo,
                                error='El perfil de destino ya no existe.')

    try:
        if nuevo:
            importador.crear_perfil(PERFILES_DIR, perfil)
        tocados = importador.aplicar(PERFILES_DIR, perfil, pendiente['analisis'])
    except Exception as e:
        return _render_mensaje('No se ha podido guardar',
                               f'El dispositivo ha dado este error: {e}. '
                               'No se ha modificado nada a medias: los archivos '
                               'se escriben de golpe o no se escriben.', ok=False)

    _descartar_pendiente(token)

    activado = False
    if nuevo and pendiente['activar']:
        config['perfil_activo'] = perfil
        guardar_config(config)
        activado = True

    recargado = False
    if config.get('perfil_activo', '') == perfil and _callback_cambiar_perfil:
        threading.Thread(target=_callback_cambiar_perfil,
                         args=(perfil,), daemon=True).start()
        recargado = True

    return _render_resultado(perfil, tocados, recargado, activado, nuevo,
                             pendiente['modo'],
                             pendiente['analisis']['vacias'])


@app.route('/importar/deshacer', methods=['POST'])
@login_requerido
def importar_deshacer():
    resultado = importador.deshacer(PERFILES_DIR)
    if not resultado['ok']:
        return _render_mensaje('No se ha podido deshacer', resultado['error'], ok=False)
    perfil = resultado['perfil']
    config = cargar_config()
    if config.get('perfil_activo', '') == perfil and _callback_cambiar_perfil:
        threading.Thread(target=_callback_cambiar_perfil,
                         args=(perfil,), daemon=True).start()
    etiquetas = ', '.join(importador.LABELS[t].lower() for t in resultado['tipos'])
    return _render_mensaje(
        'Importación deshecha',
        f'Las listas de {etiquetas} del perfil {perfil.upper()} han vuelto a estar '
        'como antes de la importación.', perfil=perfil)


@app.errorhandler(413)
def _demasiado_grande(e):
    return _render_mensaje(
        'El archivo es demasiado grande',
        'El dispositivo acepta hasta 3 MB por envío, que son muchísimas frases. '
        'Divide la lista en dos archivos e impórtalos uno detrás de otro.',
        ok=False), 413


# ------------------------------------------------------------------ #
# CSS compartido                                                      #
# ------------------------------------------------------------------ #
FONTS = '<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500&display=swap" rel="stylesheet">'

CSS_VARS = """
:root {
  --paper:   #faf7f2;
  --paper2:  #f3ede3;
  --ink:     #2c2416;
  --ink2:    #5a5040;
  --accent:  #8b3a1c;
  --accent2: #b85c35;
  --border:  #ddd6c8;
  --border2: #c8bfb0;
  --ok:      #2d6a3f;
  --ok-bg:   #eaf3ec;
  --err:     #8b1c1c;
  --err-bg:  #f9eaea;
  --white:   #ffffff;
  --shadow:  rgba(44,36,22,0.08);
  --serif:   'Lora', Georgia, serif;
  --sans:    'Inter', system-ui, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 16px; -webkit-text-size-adjust: 100%; }
body { font-family: var(--sans); background: var(--paper); color: var(--ink); min-height: 100vh; }
a { text-decoration: none; color: inherit; }
button, input, select, textarea { font-family: inherit; }
"""

CSS_UTIL = """
.serif { font-family: var(--serif); }
.muted { color: var(--ink2); }
.accent { color: var(--accent); }
.badge-activo {
  display: inline-block;
  font-size: .65rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em;
  background: var(--accent); color: #fff;
  padding: .15rem .45rem;
  vertical-align: middle; margin-left: .4rem;
}
.tag {
  display: inline-flex; align-items: center; gap: .3rem;
  font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em;
  color: var(--ink2); background: var(--paper2);
  border: 1px solid var(--border); padding: .2rem .55rem;
}
.tag.on  { background: #eaf3ec; color: var(--ok);  border-color: #b8d9c2; }
.tag.off { background: #f5f5f5; color: #aaa;       border-color: #e0e0e0; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot.on  { background: var(--ok); }
.dot.off { background: #ccc; }
"""

def _page_wrap(title, body, extra_css="", extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#2c2416">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>{title} — StoryMaker</title>
{FONTS}
<style>
{CSS_VARS}
{CSS_UTIL}
{extra_css}
</style>
{extra_head}
</head>
<body>
{body}
</body>
</html>"""

# ------------------------------------------------------------------ #
# Login                                                               #
# ------------------------------------------------------------------ #
def _render_login(error=None, primer_arranque=False):
    error_html = f'<p class="form-error">{error}</p>' if error else ''
    hint_html  = '''
<div class="primer-arranque-box">
  <p class="primer-arranque-titulo">Primera configuración</p>
  <p>PIN inicial: <strong>1234</strong></p>
  <p class="primer-arranque-sub">Podrás cambiarlo en el siguiente paso.</p>
</div>''' if primer_arranque else ''

    css = """
body {
  display: flex; align-items: center; justify-content: center;
  padding: 1.5rem; min-height: 100vh;
  background: var(--paper);
  background-image: repeating-linear-gradient(
    0deg, transparent, transparent 31px,
    var(--border) 31px, var(--border) 32px
  );
}
.login-card {
  background: var(--white);
  border: 1.5px solid var(--border);
  padding: 2.5rem 2rem;
  width: 100%; max-width: 360px;
  box-shadow: 4px 4px 0 var(--border2);
}
.login-logo {
  font-family: var(--serif);
  font-size: 2.2rem; font-weight: 600;
  color: var(--ink); line-height: 1;
  margin-bottom: .25rem;
}
.login-logo em { color: var(--accent); font-style: italic; }
.login-sub {
  font-size: .8rem; color: var(--ink2);
  text-transform: uppercase; letter-spacing: .1em;
  margin-bottom: 1.5rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid var(--border);
}
.primer-arranque-box {
  margin-bottom: 1.5rem; padding: .8rem 1rem;
  background: #fef9ec; border-left: 3px solid #d4a017;
  font-size: .84rem; line-height: 1.55;
}
.primer-arranque-titulo {
  font-weight: 600; margin-bottom: .2rem; color: #7a5800;
}
.primer-arranque-sub { color: var(--ink2); font-size: .78rem; margin-top: .15rem; }
.form-label {
  display: block; font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .08em;
  color: var(--ink2); margin-bottom: .5rem;
}
.pin-wrap { position: relative; }
.pin-input {
  width: 100%; padding: .9rem 3rem .9rem 1rem;
  border: 1.5px solid var(--border);
  font-size: 1.6rem; letter-spacing: .4em;
  text-align: center; background: var(--paper);
  color: var(--ink); outline: none;
  transition: border-color .15s;
}
.pin-input:focus { border-color: var(--accent); }
.pin-eye {
  position: absolute; right: .75rem; top: 50%; transform: translateY(-50%);
  background: none; border: none; cursor: pointer;
  color: var(--ink2); padding: .2rem; line-height: 0;
  transition: color .15s;
}
.pin-eye:hover { color: var(--accent); }
.login-btn {
  width: 100%; margin-top: 1.25rem; padding: .9rem;
  background: var(--ink); color: var(--white);
  border: none; font-size: .88rem; font-weight: 500;
  letter-spacing: .08em; text-transform: uppercase;
  cursor: pointer; transition: background .15s;
}
.login-btn:hover { background: var(--accent); }
.form-error {
  margin-top: 1rem; padding: .7rem .9rem;
  background: var(--err-bg); color: var(--err);
  font-size: .84rem; border-left: 3px solid var(--err);
}
"""
    body = f"""
<div class="login-card">
  <div class="login-logo">Story<em>Maker</em></div>
  <p class="login-sub">Panel de control</p>
  {hint_html}
  <form method="POST">
    <label class="form-label" for="pin">PIN de acceso</label>
    <div class="pin-wrap">
      <input class="pin-input" type="password" id="pin" name="pin"
             maxlength="8" autofocus autocomplete="current-password"
             inputmode="numeric" placeholder="· · · ·">
      <button type="button" class="pin-eye" onclick="togglePin()" title="Mostrar/ocultar PIN" id="pin-eye-btn">
        <svg id="eye-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      </button>
    </div>
    <button class="login-btn" type="submit">Entrar</button>
  </form>
<script>
function togglePin() {{
  const input = document.getElementById('pin');
  const icon  = document.getElementById('eye-icon');
  if (input.type === 'password') {{
    input.type = 'text';
    icon.innerHTML = '<path d="M17.9 17.9A10.9 10.9 0 0 1 12 20C5 20 1 12 1 12a18.5 18.5 0 0 1 5.1-6.1M9.9 4.2A10.5 10.5 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.2 3.2M1 1l22 22"/><circle cx="12" cy="12" r="3"/>';
  }} else {{
    input.type = 'password';
    icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
  }}
}}
</script>
  {error_html}
</div>"""
    return _page_wrap("Acceso", body, css)

# ------------------------------------------------------------------ #
# Setup                                                               #
# ------------------------------------------------------------------ #
def _render_setup(hw, config):
    eink_chk  = 'checked' if hw.get('eink',      {}).get('activada', False) else ''
    imp_chk   = 'checked' if hw.get('impresora', {}).get('activada', False) else ''
    aud_chk   = 'checked' if hw.get('audio',     {}).get('activada', False) else ''
    vol_val   = hw.get('audio', {}).get('volumen', 80)
    baud_val  = hw.get('impresora', {}).get('baudrate', 9600)
    setup_ok  = config.get('setup_completado', False)
    btn_label = "Guardar cambios" if setup_ok else "Confirmar configuración"
    back_link = '<a href="/" class="back-link">← Volver al panel</a>' if setup_ok else ''

    css = """
body { display: flex; align-items: flex-start; justify-content: center; padding: 2rem 1rem; }
.setup-wrap { width: 100%; max-width: 520px; }
.setup-header { margin-bottom: 2rem; }
.setup-title {
  font-family: var(--serif); font-size: 1.8rem; font-weight: 600;
  color: var(--ink); line-height: 1.1; margin-bottom: .35rem;
}
.setup-sub { font-size: .85rem; color: var(--ink2); line-height: 1.5; }
.section {
  background: var(--white); border: 1.5px solid var(--border);
  padding: 1.25rem 1.5rem; margin-bottom: 1rem;
}
.section-title {
  font-size: .7rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink2); margin-bottom: .9rem;
}
.toggle-row { display: flex; align-items: center; gap: .75rem; }
.toggle-row input[type=checkbox] {
  width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0;
}
.toggle-label { font-size: .95rem; font-weight: 500; cursor: pointer; color: var(--ink); }
.toggle-desc { font-size: .78rem; color: var(--ink2); margin-top: .2rem; margin-left: 1.7rem; }
.sub-field { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
.sub-label {
  display: block; font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .07em;
  color: var(--ink2); margin-bottom: .4rem;
}
.sub-input {
  width: 100%; padding: .65rem .85rem;
  border: 1.5px solid var(--border); background: var(--paper);
  font-size: .95rem; color: var(--ink); outline: none;
  transition: border-color .15s;
}
.sub-input:focus { border-color: var(--accent); }
.vol-row { display: flex; align-items: center; gap: .75rem; margin-top: .5rem; }
.vol-row input[type=range] { flex: 1; accent-color: var(--accent); }
.vol-num { font-size: .88rem; font-weight: 500; min-width: 2.2rem; text-align: right; }
.nota { font-size: .75rem; color: var(--ink2); margin-top: .45rem; font-style: italic; }
.submit-btn {
  width: 100%; padding: 1rem;
  background: var(--ink); color: var(--white); border: none;
  font-size: .9rem; font-weight: 500; letter-spacing: .07em;
  text-transform: uppercase; cursor: pointer;
  transition: background .15s; margin-top: .5rem;
}
.submit-btn:hover { background: var(--accent); }
.back-link { display: inline-block; font-size: .82rem; color: var(--ink2); margin-top: 1rem; }
.back-link:hover { color: var(--accent); }
.danger-zone {
  margin-top: 2rem; padding: 1.1rem 1.5rem;
  border: 1.5px solid #e8c4c4; background: #fdf5f5;
}
.danger-title {
  font-size: .7rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .1em; color: #a03030; margin-bottom: .45rem;
}
.danger-desc { font-size: .82rem; color: var(--ink2); margin-bottom: .9rem; line-height: 1.5; }
.danger-btn {
  font-size: .8rem; font-weight: 500; text-transform: uppercase; letter-spacing: .06em;
  background: none; color: #a03030;
  border: 1.5px solid #e8c4c4; padding: .5rem 1rem;
  cursor: pointer; transition: background .12s, border-color .12s;
}
.danger-btn:hover { background: #fbeaea; border-color: #c04040; }
"""
    body = f"""
<div class="setup-wrap">
  <div class="setup-header">
    <h1 class="setup-title">{"Configuración de hardware" if setup_ok else "Configuración inicial"}</h1>
    <p class="setup-sub">{"Ajusta qué hardware está conectado al HAT de este dispositivo." if setup_ok else "Primera vez que arrancas StoryMaker. Indica qué módulos están conectados al HAT."}</p>
  </div>

  <form method="POST">
    <div class="section">
      <p class="section-title">Pantalla</p>
      <div class="toggle-row">
        <input type="checkbox" id="eink" name="eink" {eink_chk}>
        <label class="toggle-label" for="eink">Pantalla e-ink</label>
      </div>
      <p class="toggle-desc">WeAct Studio 4.2" · SSD1683 · SPI0</p>
    </div>

    <div class="section">
      <p class="section-title">Impresora</p>
      <div class="toggle-row">
        <input type="checkbox" id="impresora" name="impresora" {imp_chk}
               onchange="toggleBaud(this.checked)">
        <label class="toggle-label" for="impresora">Impresora térmica</label>
      </div>
      <p class="toggle-desc">QR701-N32 · UART · /dev/serial0</p>
      <div id="baud-wrap" class="sub-field" style="display:{'block' if imp_chk else 'none'}">
        <label class="sub-label" for="baudrate">Baudrate</label>
        <input class="sub-input" type="number" id="baudrate" name="baudrate"
               value="{baud_val}" min="4800" max="115200" style="max-width:160px">
        <p class="nota">Normalmente 9600. Consulta el manual de tu impresora.</p>
      </div>
    </div>

    <div class="section">
      <p class="section-title">Audio</p>
      <div class="toggle-row">
        <input type="checkbox" id="audio" name="audio" {aud_chk}
               onchange="toggleVol(this.checked)">
        <label class="toggle-label" for="audio">Altavoz I2S</label>
      </div>
      <p class="toggle-desc">MAX98357A · GPIO 18/19/21 · edge-tts (Elvira Neural)</p>
      <div id="vol-wrap" class="sub-field" style="display:{'block' if aud_chk else 'none'}">
        <label class="sub-label">Volumen: <span id="vol-num">{vol_val}</span>%</label>
        <div class="vol-row">
          <input type="range" id="volumen" name="volumen" min="0" max="100"
                 value="{vol_val}" step="1"
                 oninput="document.getElementById('vol-num').textContent=this.value">
        </div>
      </div>
    </div>

    <div class="section">
      <p class="section-title">Seguridad</p>
      <label class="sub-label" for="nuevo_pin">Cambiar PIN de acceso</label>
      <input class="sub-input" type="password" id="nuevo_pin" name="nuevo_pin"
             maxlength="8" placeholder="Dejar vacío para no cambiar"
             inputmode="numeric" style="max-width:200px">
      <p class="nota">4–8 dígitos. Dejar vacío para no cambiar.</p>
    </div>

    <button class="submit-btn" type="submit">{btn_label}</button>
  </form>
  {back_link}

  <div class="danger-zone">
    <p class="danger-title">Zona de peligro</p>
    <p class="danger-desc">El reset de fábrica borra la configuración de hardware y el PIN, y vuelve al primer arranque. Los perfiles y premisas no se borran.</p>
    <button class="danger-btn" onclick="mostrarConfirmReset()">↺ Reset de fábrica</button>
    <div id="reset-confirm" style="display:none;margin-top:.85rem;padding:.85rem 1rem;background:#fff0f0;border:1px solid #e8c4c4;">
      <p style="font-size:.82rem;color:#a03030;margin-bottom:.7rem;line-height:1.5">
        ¿Confirmas el reset? El PIN volverá a <strong>1234</strong> y el dispositivo volverá a la configuración inicial.
      </p>
      <div style="display:flex;gap:.6rem;">
        <button onclick="ejecutarReset()" style="font-size:.8rem;font-weight:500;padding:.45rem 1rem;background:#a03030;color:#fff;border:none;cursor:pointer;">Sí, resetear</button>
        <button onclick="cancelarReset()" style="font-size:.8rem;padding:.45rem .9rem;background:none;border:1.5px solid #e8c4c4;cursor:pointer;color:#666;">Cancelar</button>
      </div>
    </div>
  </div>
</div>
<script>
function toggleBaud(v) {{
  document.getElementById('baud-wrap').style.display = v ? 'block' : 'none';
}}
function toggleVol(v) {{
  document.getElementById('vol-wrap').style.display = v ? 'block' : 'none';
}}
function mostrarConfirmReset() {{
  document.getElementById('reset-confirm').style.display = 'block';
}}
function cancelarReset() {{
  document.getElementById('reset-confirm').style.display = 'none';
}}
async function ejecutarReset() {{
  const btns = document.querySelectorAll('#reset-confirm button');
  btns.forEach(b => b.disabled = true);
  document.querySelector('#reset-confirm p').textContent = 'Reiniciando el dispositivo...';
  try {{
    await fetch('/api/reset_fabrica', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: '{{}}'
    }});
  }} catch(e) {{}}
  setTimeout(() => window.location.href = '/', 3000);
}}
</script>"""
    return _page_wrap("Setup", body, css)

# ------------------------------------------------------------------ #
# Panel principal                                                     #
# ------------------------------------------------------------------ #
TIPOS  = ['detonantes', 'protagonistas', 'conflictos']
LABELS = {'detonantes': 'Detonantes', 'protagonistas': 'Protagonistas', 'conflictos': 'Conflictos'}
ICONOS_SVG = {
    'detonantes':    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/></svg>',
    'protagonistas': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>',
    'conflictos':    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4m0 4h.01M10.3 3.6L2.2 17A2 2 0 004 20h16a2 2 0 001.8-2.9L13.8 3.6a2 2 0 00-3.5 0z"/></svg>',
}

def _render_pagina(perfiles, perfil_activo, perfil_sel, tipo_sel, config, premisas=None):
    hw = config.get('hardware', {})
    audio_activo = hw.get('audio', {}).get('activada', False)
    vol_val      = hw.get('audio', {}).get('volumen', 80)

    # Badges hardware
    hw_tags = ''
    for clave, label in [('eink','E-ink'), ('impresora','Impresora'), ('audio','Audio')]:
        on = hw.get(clave, {}).get('activada', False)
        cls = 'on' if on else 'off'
        hw_tags += f'<span class="tag {cls}"><span class="dot {cls}"></span>{label}</span>'

    # Selector de perfil activo
    opciones = ''.join([
        f'<option value="{p}" {"selected" if p==perfil_activo else ""}>{p.upper()}</option>'
        for p in perfiles
    ])

    # Nav de perfiles (sidebar / scroll horizontal)
    nav_perfiles = ''
    for p in perfiles:
        cls    = 'activo' if p == perfil_sel else ''
        badge  = '<span class="badge-activo">activo</span>' if p == perfil_activo else ''
        nav_perfiles += f'<a href="/perfil/{p}" class="nav-perfil {cls}">{p.upper()}{badge}</a>'
    if not nav_perfiles:
        nav_perfiles = '<span class="nav-empty">Sin perfiles</span>'

    # Tabs de tipo
    tabs_html = ''
    if perfil_sel:
        for t in TIPOS:
            cls   = 'activo' if t == tipo_sel else ''
            count = len(get_premisas(perfil_sel, t))
            tabs_html += f'''<a href="/perfil/{perfil_sel}/{t}" class="tab {cls}">
              {ICONOS_SVG[t]}<span>{LABELS[t]}</span>
              <span class="tab-count">{count}</span>
            </a>'''

    # Contenido de premisas
    contenido = ''
    if perfil_sel and tipo_sel and premisas is not None:
        items = ''
        for i, p in enumerate(premisas):
            p_esc = p.replace("'", "\\'").replace('"', '&quot;')
            items += f'''<li class="premisa-item" id="p{i}">
              <span class="premisa-num">{i+1}</span>
              <span class="premisa-texto">{p}</span>
              <button class="premisa-del" onclick="borrar({i})" title="Borrar esta premisa">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </li>'''
        if not items:
            items = '<li class="premisa-vacia">Sin premisas. ¡Añade la primera abajo!</li>'

        contenido = f'''
<div class="premisas-card">
  <div class="premisas-header">
    <h2 class="premisas-title serif">{LABELS[tipo_sel]}<span class="muted" style="font-weight:400;font-size:.9em"> · {perfil_sel.upper()}</span></h2>
    <div class="premisas-head-right">
      <a class="imp-link" href="/importar?perfil={perfil_sel}">&#8681; Importar .txt</a>
      <span class="premisas-total">{len(premisas)} premisas</span>
    </div>
  </div>
  <ul class="premisas-lista">{items}</ul>
  <div class="anadir-area">
    <p class="anadir-label">Añadir nueva premisa</p>
    <textarea id="nueva-premisa" rows="3"
      placeholder="Escribe aquí la nueva premisa y pulsa Añadir..."></textarea>
    <div class="anadir-actions">
      <button class="anadir-btn" onclick="anadir()">+ Añadir</button>
      <span class="fb" id="fb"></span>
    </div>
  </div>
</div>
<script>
async function anadir() {{
  const ta = document.getElementById('nueva-premisa');
  const fb = document.getElementById('fb');
  const texto = ta.value.trim();
  if (!texto) {{ fb.textContent = 'Escribe algo primero.'; fb.className='fb err'; return; }}
  const r = await fetch('/api/anadir_premisa', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{perfil: '{perfil_sel}', tipo: '{tipo_sel}', texto}})
  }});
  const d = await r.json();
  if (d.ok) {{
    fb.textContent = 'Añadida (' + d.total + ' en total)';
    fb.className = 'fb ok';
    ta.value = '';
    setTimeout(() => location.reload(), 800);
  }} else {{
    fb.textContent = d.error;
    fb.className = 'fb err';
  }}
}}
async function borrar(i) {{
  if (!confirm('¿Borrar esta premisa?')) return;
  const r = await fetch('/api/borrar_premisa', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{perfil: '{perfil_sel}', tipo: '{tipo_sel}', indice: i}})
  }});
  const d = await r.json();
  if (d.ok) location.reload();
}}
</script>'''
    elif perfil_sel and not tipo_sel:
        contenido = '<div class="selecciona-tipo">Selecciona un tipo de premisa arriba.</div>'
    else:
        contenido = f'''<div class="bienvenida">
  <p class="serif bienvenida-title">«La historia comienza con una premisa.»</p>
  <p class="bienvenida-sub">Selecciona un perfil en el panel lateral para gestionar sus premisas, o elige el perfil activo en el encabezado.</p>
</div>'''

    # Nuevo perfil
    nuevo_perfil_html = '''
<div class="nuevo-perfil-wrap">
  <button class="nuevo-perfil-btn" onclick="toggleNuevo()">+ Nuevo perfil</button>
  <div id="nuevo-perfil-form" style="display:none; margin-top:.75rem;">
    <input type="text" id="nuevo-nombre" placeholder="ej: 2eso, bachillerato..."
           style="padding:.6rem .8rem; border:1.5px solid var(--border); width:100%; margin-bottom:.5rem; font-size:.9rem; background:var(--paper); color:var(--ink); outline:none;">
    <button class="nuevo-perfil-crear" onclick="crearPerfil()">Crear</button>
    <span class="fb" id="fb-perfil"></span>
  </div>
  <a href="/importar" class="nuevo-perfil-btn"
     style="display:block; text-align:center; margin-top:.5rem;">&#8681; Importar .txt</a>
</div>
<script>
function toggleNuevo() {
  const f = document.getElementById('nuevo-perfil-form');
  f.style.display = f.style.display === 'none' ? 'block' : 'none';
}
async function crearPerfil() {
  const nombre = document.getElementById('nuevo-nombre').value.trim();
  const fb = document.getElementById('fb-perfil');
  if (!nombre) { fb.textContent='Escribe un nombre.'; fb.className='fb err'; return; }
  const r = await fetch('/api/nuevo_perfil', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nombre})
  });
  const d = await r.json();
  if (d.ok) { location.reload(); }
  else { fb.textContent = d.error; fb.className='fb err'; }
}
</script>'''

    css = """
/* ── Layout general ── */
body { display: flex; flex-direction: column; }

/* ── Header ── */
.header {
  background: var(--ink); color: var(--white);
  padding: .85rem 1.25rem;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: .6rem;
  border-bottom: 3px solid var(--accent);
  position: sticky; top: 0; z-index: 100;
}
.header-logo {
  font-family: var(--serif); font-size: 1.3rem; font-weight: 600; line-height: 1;
}
.header-logo em { color: var(--accent2); font-style: italic; }
.header-right { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.hw-tags { display: flex; gap: .35rem; flex-wrap: wrap; }
.header-right .tag { border-color: rgba(255,255,255,.15); }
.header-right .tag.on  { background: rgba(45,106,63,.35); color: #9be6a8; border-color: rgba(155,230,168,.3); }
.header-right .tag.off { background: rgba(255,255,255,.06); color: #888; border-color: rgba(255,255,255,.1); }
.header-right .dot.on  { background: #9be6a8; }
.header-right .dot.off { background: #555; }

.vol-inline { display: flex; align-items: center; gap: .4rem; }
.vol-inline input[type=range] { width: 70px; accent-color: var(--accent2); cursor: pointer; }
.vol-inline span { font-size: .75rem; color: #aaa; min-width: 2rem; }

.perfil-sel-wrap { display: flex; align-items: center; gap: .4rem; }
.perfil-sel-wrap label { font-size: .7rem; text-transform: uppercase; letter-spacing: .07em; color: #888; }
.perfil-sel-wrap select {
  background: rgba(255,255,255,.08); color: var(--white);
  border: 1px solid rgba(255,255,255,.2);
  padding: .3rem .6rem; font-size: .82rem; cursor: pointer; outline: none;
}
.perfil-sel-wrap select option { background: var(--ink); }

.header-links { display: flex; gap: .5rem; }
.hlink {
  font-size: .75rem; text-transform: uppercase; letter-spacing: .06em;
  color: #888; padding: .3rem .5rem; transition: color .15s;
}
.hlink:hover { color: var(--accent2); }
.hlink-apagar {
  background: none; border: none; cursor: pointer;
}
.hlink-apagar:hover { color: #e05c5c; }

/* ── Layout main ── */
.main-layout { display: flex; flex: 1; min-height: 0; }

/* ── Sidebar ── */
.sidebar {
  width: 200px; flex-shrink: 0;
  background: var(--white); border-right: 1.5px solid var(--border);
  padding: 1.25rem 0;
  display: flex; flex-direction: column;
}
.sidebar-label {
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink2);
  padding: 0 1rem; margin-bottom: .6rem;
}
.nav-perfil {
  display: block; padding: .65rem 1rem;
  font-size: .88rem; font-weight: 500; color: var(--ink);
  border-left: 3px solid transparent;
  transition: background .12s, border-color .12s;
}
.nav-perfil:hover  { background: var(--paper2); border-left-color: var(--border2); }
.nav-perfil.activo { background: var(--paper2); border-left-color: var(--accent); color: var(--accent); }
.nav-empty { padding: .65rem 1rem; font-size: .82rem; color: var(--ink2); font-style: italic; }
.sidebar-footer { margin-top: auto; padding: 1rem; border-top: 1px solid var(--border); }
.nuevo-perfil-btn {
  font-size: .75rem; font-weight: 500; text-transform: uppercase; letter-spacing: .06em;
  color: var(--ink2); background: none; border: 1px dashed var(--border2);
  padding: .45rem .75rem; cursor: pointer; width: 100%; transition: color .12s, border-color .12s;
}
.nuevo-perfil-btn:hover { color: var(--accent); border-color: var(--accent); }
.nuevo-perfil-crear {
  font-size: .78rem; font-weight: 500; padding: .45rem .9rem;
  background: var(--ink); color: var(--white); border: none; cursor: pointer;
}
.nuevo-perfil-crear:hover { background: var(--accent); }

/* ── Contenido ── */
.contenido { flex: 1; padding: 1.5rem; overflow-y: auto; }

/* ── Tabs ── */
.tabs { display: flex; gap: .5rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
.tab {
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .5rem .9rem; font-size: .82rem; font-weight: 500;
  border: 1.5px solid var(--border); color: var(--ink2);
  background: var(--white); transition: all .12s;
}
.tab:hover { border-color: var(--ink); color: var(--ink); }
.tab.activo { border-color: var(--ink); background: var(--ink); color: var(--white); }
.tab-count {
  font-size: .72rem; background: rgba(255,255,255,.18);
  padding: .1rem .4rem; min-width: 1.5rem; text-align: center;
}
.tab:not(.activo) .tab-count { background: var(--paper2); color: var(--ink2); }

/* ── Premisas ── */
.premisas-card { background: var(--white); border: 1.5px solid var(--border); }
.premisas-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.premisas-title { font-size: 1.2rem; font-weight: 600; }
.premisas-total {
  font-size: .75rem; color: var(--ink2);
  background: var(--paper2); border: 1px solid var(--border);
  padding: .2rem .6rem;
}
.premisas-head-right { display: flex; align-items: center; gap: .6rem; }
.imp-link {
  font-size: .75rem; color: var(--ink2); white-space: nowrap;
  border: 1px solid var(--border2); padding: .25rem .6rem;
  transition: color .12s, border-color .12s;
}
.imp-link:hover { color: var(--accent); border-color: var(--accent); }
.premisas-lista { list-style: none; max-height: 340px; overflow-y: auto; }
.premisa-item {
  display: flex; align-items: baseline; gap: .7rem;
  padding: .65rem 1.25rem; border-bottom: 1px solid var(--paper2);
  transition: background .1s;
}
.premisa-item:hover { background: var(--paper); }
.premisa-num { font-size: .7rem; color: var(--ink2); min-width: 1.4rem; text-align: right; flex-shrink: 0; }
.premisa-texto { flex: 1; font-size: .88rem; line-height: 1.5; color: var(--ink); }
.premisa-del {
  background: none; border: none; cursor: pointer;
  color: var(--border2); padding: .2rem; flex-shrink: 0;
  transition: color .12s;
}
.premisa-del:hover { color: var(--accent); }
.premisa-vacia {
  padding: 2rem 1.25rem; text-align: center;
  font-style: italic; color: var(--ink2); font-size: .88rem;
}

/* ── Añadir ── */
.anadir-area { padding: 1.1rem 1.25rem; border-top: 2px solid var(--border); background: var(--paper); }
.anadir-label {
  font-size: .7rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .08em; color: var(--ink2); margin-bottom: .6rem;
}
.anadir-area textarea {
  width: 100%; padding: .75rem .9rem;
  border: 1.5px solid var(--border); background: var(--white);
  font-size: .9rem; line-height: 1.55; resize: vertical;
  color: var(--ink); outline: none; transition: border-color .15s;
}
.anadir-area textarea:focus { border-color: var(--accent); }
.anadir-actions { display: flex; align-items: center; gap: .75rem; margin-top: .6rem; }
.anadir-btn {
  padding: .6rem 1.25rem; background: var(--ink); color: var(--white);
  border: none; font-size: .82rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .06em;
  cursor: pointer; transition: background .12s; white-space: nowrap;
}
.anadir-btn:hover { background: var(--accent); }
.fb { font-size: .82rem; }
.fb.ok  { color: var(--ok); }
.fb.err { color: var(--err); }

/* ── Bienvenida / placeholders ── */
.bienvenida {
  padding: 3.5rem 2rem; text-align: center;
  max-width: 420px; margin: 0 auto;
}
.bienvenida-title {
  font-size: 1.25rem; font-style: italic; color: var(--ink2);
  margin-bottom: .9rem; line-height: 1.5;
}
.bienvenida-sub { font-size: .87rem; color: var(--ink2); line-height: 1.6; }
.selecciona-tipo {
  padding: 3rem 1.5rem; text-align: center;
  font-style: italic; color: var(--ink2); font-size: .9rem;
}

/* ── Barra GENERAR ── */
.generar-bar {
  background: var(--accent);
  padding: .75rem 1.25rem;
  display: flex; align-items: center; gap: 1rem;
  border-bottom: 2px solid #6b2a12;
}
.generar-btn {
  font-family: var(--serif); font-size: 1.05rem; font-weight: 600;
  letter-spacing: .08em;
  background: var(--white); color: var(--accent);
  border: none; padding: .65rem 2rem;
  cursor: pointer; transition: background .12s, transform .1s;
  white-space: nowrap;
  box-shadow: 3px 3px 0 rgba(0,0,0,.2);
}
.generar-btn:hover  { background: var(--paper); }
.generar-btn:active { transform: translate(2px,2px); box-shadow: 1px 1px 0 rgba(0,0,0,.2); }
.generar-btn:disabled {
  opacity: .6; cursor: not-allowed;
  transform: none; box-shadow: 3px 3px 0 rgba(0,0,0,.2);
}
.generar-fb {
  font-size: .82rem; color: rgba(255,255,255,.85);
  font-style: italic; flex: 1;
  min-height: 1.2em;
}
@media (max-width: 640px) {
  .generar-bar { padding: .65rem 1rem; }
  .generar-btn { padding: .6rem 1.4rem; font-size: .95rem; }
}

/* ── Mobile: menú lateral colapsado ── */
@media (max-width: 640px) {
  .sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; padding: .6rem .75rem; border-right: none; border-bottom: 1.5px solid var(--border); }
  .sidebar-label { width: 100%; margin-bottom: .35rem; }
  .nav-perfil { border-left: none; border-bottom: 3px solid transparent; padding: .45rem .75rem; font-size: .82rem; }
  .nav-perfil.activo { border-bottom-color: var(--accent); border-left-color: transparent; }
  .sidebar-footer { border-top: none; border-left: 1px solid var(--border); padding: .45rem .75rem; margin-top: 0; }
  .nuevo-perfil-btn { white-space: nowrap; }
  .main-layout { flex-direction: column; }
  .contenido { padding: 1rem; }
  .header { padding: .75rem 1rem; }
  .hw-tags { display: none; } /* ocultar en móvil pequeño */
  .hlink { padding: .3rem .3rem; }
  .premisas-lista { max-height: 260px; }
  .tabs { gap: .35rem; }
  .tab { padding: .45rem .7rem; font-size: .78rem; }
}
"""
    vol_script = f"""
<script>
var _volTimer = null;
function debounceVol(v) {{
  document.getElementById('vol-display').textContent = Math.round(v) + '%';
  clearTimeout(_volTimer);
  _volTimer = setTimeout(() => setVol(v), 400);
}}
async function setVol(v) {{
  await fetch('/api/guardar_volumen', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{volumen: parseInt(v)}})
  }});
}}
async function generarPremisa() {{
  const btn = document.getElementById('generar-btn');
  const fb  = document.getElementById('generar-fb');
  btn.disabled = true;
  fb.textContent = 'Generando...';
  try {{
    const r = await fetch('/api/generar', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:'{{}}'}});
    const d = await r.json();
    if (d.ok) {{
      fb.textContent = 'Premisa enviada a las salidas activas.';
    }} else {{
      fb.textContent = d.error || 'Error al generar.';
    }}
  }} catch(e) {{
    fb.textContent = 'Error de conexión.';
  }}
  setTimeout(() => {{
    btn.disabled = false;
    fb.textContent = '';
  }}, 3000);
}}
async function cambiarPerfil(p) {{
  const r = await fetch('/api/cambiar_perfil', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{perfil: p}})
  }});
  const d = await r.json();
  if (d.ok) {{
    const sel = document.getElementById('perfil-sel');
    sel.style.outline = '2px solid #9be6a8';
    setTimeout(() => sel.style.outline = '', 1400);
  }}
}}
async function confirmarApagado() {{
  if (!confirm('¿Apagar el dispositivo?')) return;
  const btn = document.querySelector('.hlink-apagar');
  btn.disabled = true;
  btn.textContent = 'Apagando...';
  await fetch('/api/apagar', {{method:'POST',
    headers:{{'Content-Type':'application/json'}}, body:'{{}}'}});
}}
</script>
""" if audio_activo else "<script>async function cambiarPerfil(p){const r=await fetch('/api/cambiar_perfil',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({perfil:p})});}</script>"

    vol_control = f'''
<div class="vol-inline">
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:#888"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a9 9 0 0 1 0 14"/></svg>
  <input type="range" min="0" max="100" value="{vol_val}" step="1"
         id="vol-slider" oninput="debounceVol(this.value)">
  <span id="vol-display">{vol_val}%</span>
</div>''' if audio_activo else ''

    body = f"""
<header class="header">
  <div class="header-logo">Story<em>Maker</em></div>
  <div class="header-right">
    <div class="hw-tags">{hw_tags}</div>
    {vol_control}
    <div class="perfil-sel-wrap">
      <label for="perfil-sel">Perfil activo</label>
      <select id="perfil-sel" onchange="cambiarPerfil(this.value)">{opciones}</select>
    </div>
    <div class="header-links">
      <a href="/setup" class="hlink">⚙ Hardware</a>
      <button class="hlink hlink-apagar" onclick="confirmarApagado()" title="Apagar el dispositivo">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px"><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
        Apagar
      </button>
      <a href="/logout" class="hlink">Salir</a>
    </div>
  </div>
</header>
<div class="generar-bar">
  <button class="generar-btn" id="generar-btn" onclick="generarPremisa()">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2.5" style="vertical-align:-3px;margin-right:.5rem">
      <polygon points="5,3 19,12 5,21"/>
    </svg>
    GENERAR
  </button>
  <span class="generar-fb" id="generar-fb"></span>
</div>

<div class="main-layout">
  <aside class="sidebar">
    <p class="sidebar-label">Perfiles</p>
    {nav_perfiles}
    <div class="sidebar-footer">
      {nuevo_perfil_html}
    </div>
  </aside>

  <div class="contenido">
    {'<div class="tabs">' + tabs_html + '</div>' if tabs_html else ''}
    {contenido}
  </div>
</div>
{vol_script}"""

    return _page_wrap("Panel", body, css)

# ------------------------------------------------------------------ #
# Pantallas de importación                                            #
# ------------------------------------------------------------------ #
PISTAS = {
    'detonantes': ('Cómo o cuándo arranca la historia. Normalmente termina en coma.',
                   'Después de ganar la lotería,'),
    'protagonistas': ('Quién la protagoniza. Sin punto al final.',
                      'una adolescente descarada'),
    'conflictos': ('Qué le ocurre. Es lo que cierra la frase.',
                   'ingresa en una milicia.'),
}

CSS_IMPORTAR = """
.imp-header {
  background: var(--ink); color: var(--white); padding: .85rem 1.25rem;
  display: flex; align-items: center; justify-content: space-between; gap: .6rem;
  border-bottom: 3px solid var(--accent);
}
.imp-logo { font-family: var(--serif); font-size: 1.15rem; }
.imp-logo em { color: var(--accent2); font-style: italic; }
.imp-volver { font-size: .78rem; color: #d8cfbe; border: 1px solid #4a4030; padding: .35rem .7rem; }
.imp-volver:hover { color: #fff; border-color: var(--accent2); }
.imp-wrap { max-width: 860px; margin: 0 auto; padding: 1.75rem 1.25rem 3rem; }
.imp-titulo { font-family: var(--serif); font-size: 1.6rem; font-weight: 600; margin-bottom: .35rem; }
.imp-sub { color: var(--ink2); font-size: .92rem; line-height: 1.55; margin-bottom: 1.5rem; }
.imp-ayuda {
  background: var(--paper2); border: 1px solid var(--border);
  border-left: 3px solid var(--accent); padding: 1rem 1.1rem;
  margin-bottom: 1.75rem; font-size: .88rem; line-height: 1.6; color: var(--ink2);
}
.imp-ayuda strong { color: var(--ink); }
.imp-ayuda ol { margin: .6rem 0 0 1.1rem; }
.imp-ayuda li { margin-bottom: .3rem; }
.imp-ejemplo {
  font-family: var(--serif); font-style: italic; color: var(--ink);
  background: var(--white); border: 1px solid var(--border);
  padding: .6rem .8rem; margin: .7rem 0;
}
.imp-ejemplo b { font-style: normal; font-weight: 600; color: var(--accent); }
.imp-paso { background: var(--white); border: 1.5px solid var(--border); margin-bottom: 1.25rem; }
.imp-paso-cab {
  padding: .8rem 1.1rem; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: .6rem;
}
.imp-paso-num {
  width: 22px; height: 22px; background: var(--ink); color: #fff; font-size: .72rem;
  display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
}
.imp-paso-tit { font-size: .95rem; font-weight: 600; }
.imp-paso-cuerpo { padding: 1.1rem; }
.imp-opcion { display: flex; gap: .7rem; align-items: flex-start; padding: .55rem; cursor: pointer; }
.imp-opcion:hover { background: var(--paper); }
.imp-opcion input[type=radio] { margin-top: .25rem; flex: 0 0 auto; }
.imp-opcion-txt { flex: 1; }
.imp-opcion-txt strong { display: block; font-size: .9rem; font-weight: 500; margin-bottom: .15rem; }
.imp-opcion-txt span { font-size: .8rem; color: var(--ink2); line-height: 1.45; display: block; }
.imp-campo {
  padding: .55rem .7rem; border: 1.5px solid var(--border); background: var(--paper);
  color: var(--ink); font-size: .9rem; outline: none; width: 100%; max-width: 330px;
  margin-top: .45rem;
}
.imp-campo:focus { border-color: var(--accent); }
.imp-check { font-size: .82rem; color: var(--ink2); margin-top: .55rem; display: block; }
.imp-desactivado { opacity: .45; }
.imp-cat { border: 1.5px solid var(--border); background: var(--white); margin-bottom: 1rem; }
.imp-cat-cab {
  display: flex; align-items: center; gap: .5rem; padding: .7rem 1rem;
  background: var(--paper2); border-bottom: 1px solid var(--border);
}
.imp-cat-nom { font-size: .85rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.imp-cat-cuerpo { padding: 1rem; }
.imp-cat-pista { font-size: .82rem; color: var(--ink2); margin-bottom: .85rem; line-height: 1.5; }
.imp-cat-pista i { font-family: var(--serif); color: var(--ink); }
.imp-o { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #a8a08f; margin: .8rem 0 .45rem; }
.imp-cat textarea {
  width: 100%; min-height: 86px; padding: .6rem .7rem; border: 1.5px solid var(--border);
  background: var(--paper); color: var(--ink); font-size: .88rem; line-height: 1.5;
  outline: none; resize: vertical;
}
.imp-cat textarea:focus { border-color: var(--accent); }
.imp-acciones { display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; margin-top: 1.5rem; }
.imp-btn {
  padding: .75rem 1.5rem; background: var(--ink); color: #fff; border: none;
  font-size: .85rem; font-weight: 500; text-transform: uppercase; letter-spacing: .06em;
  cursor: pointer; transition: background .12s;
}
.imp-btn:hover { background: var(--accent); }
.imp-btn-rojo { background: var(--err); }
.imp-btn-rojo:hover { background: #a82323; }
.imp-btn2 {
  padding: .72rem 1.25rem; border: 1.5px solid var(--border2); background: none;
  color: var(--ink2); font-size: .85rem; cursor: pointer; display: inline-block;
}
.imp-btn2:hover { color: var(--accent); border-color: var(--accent); }
.imp-error, .imp-aviso, .imp-ok {
  padding: .9rem 1.1rem; font-size: .88rem; line-height: 1.55;
  margin-bottom: 1.25rem; border: 1px solid;
}
.imp-error { background: var(--err-bg); border-color: #e0bcbc; color: var(--err); }
.imp-aviso { background: #fdf6e3; border-color: #e8d9a8; color: #7a5c10; }
.imp-ok    { background: var(--ok-bg); border-color: #b8d9c2; color: var(--ok); }
.imp-error strong, .imp-aviso strong, .imp-ok strong { display: block; margin-bottom: .2rem; }
.imp-tabla {
  width: 100%; border-collapse: collapse; font-size: .88rem;
  background: var(--white); border: 1.5px solid var(--border);
}
.imp-tabla th {
  text-align: left; font-size: .7rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--ink2); background: var(--paper2); padding: .6rem .8rem;
  border-bottom: 1px solid var(--border);
}
.imp-tabla td { padding: .65rem .8rem; border-bottom: 1px solid var(--border); vertical-align: top; }
.imp-tabla tr:last-child td { border-bottom: none; }
.imp-cifra { font-variant-numeric: tabular-nums; }
.imp-mas { color: var(--ok); font-weight: 600; }
.imp-menos { color: var(--err); font-weight: 600; }
.imp-nota { display: block; font-size: .77rem; color: var(--ink2); margin-top: .25rem; line-height: 1.45; }
.imp-intacta { color: #a8a08f; }
.imp-muestra { background: var(--white); border: 1.5px solid var(--border); padding: 1rem 1.1rem; margin-top: 1.25rem; }
.imp-muestra h3 {
  font-size: .75rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--ink2); margin-bottom: .7rem; font-weight: 500;
}
.imp-muestra-cat { font-size: .72rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .05em; color: var(--accent); display: block; margin: .6rem 0 .3rem; }
.imp-muestra ul { list-style: none; }
.imp-muestra li {
  font-family: var(--serif); font-size: .92rem; padding: .18rem 0 .18rem .9rem;
  border-left: 2px solid var(--border2); margin-bottom: .12rem;
}
.imp-resumen { list-style: none; margin: .4rem 0 0; }
.imp-resumen li { font-size: .9rem; padding: .2rem 0; }
@media (max-width: 640px) {
  .imp-wrap { padding: 1.1rem .9rem 2.5rem; }
  .imp-titulo { font-size: 1.3rem; }
  .imp-tabla th:nth-child(2), .imp-tabla td:nth-child(2) { display: none; }
}
"""


def _imp_cabecera():
    return ('<header class="imp-header">'
            '<div class="imp-logo">Story<em>Maker</em></div>'
            '<a href="/" class="imp-volver">← Volver al panel</a>'
            '</header>')


def _render_importar(perfiles, perfil_activo, perfil_pre, error=None, form=None):
    form     = form or {}
    destino  = form.get('destino', 'existente')
    es_nuevo = destino == 'nuevo'
    modo     = form.get('modo', 'anadir')
    nombre_nuevo = html.escape(form.get('nombre_nuevo', ''))
    activar_chk  = ' checked' if form.get('activar') == 'si' else ''

    error_html = f'<div class="imp-error"><strong>Revisa esto</strong>{html.escape(error)}</div>' if error else ''

    opciones = ''
    for p in perfiles:
        sel = ' selected' if p == perfil_pre else ''
        marca = ' — perfil activo' if p == perfil_activo else ''
        opciones += f'<option value="{html.escape(p)}"{sel}>{html.escape(p.upper())}{marca}</option>'
    if not opciones:
        opciones = '<option value="">(todavía no hay perfiles)</option>'

    r_exist = '' if es_nuevo else ' checked'
    r_nuevo = ' checked' if es_nuevo else ''

    cats = ''
    for tipo in importador.TIPOS:
        pista, ejemplo = PISTAS[tipo]
        valor = html.escape(form.get(f'texto_{tipo}', ''))
        cats += f'''
<div class="imp-cat">
  <div class="imp-cat-cab">{ICONOS_SVG[tipo]}<span class="imp-cat-nom">{LABELS[tipo]}</span></div>
  <div class="imp-cat-cuerpo">
    <p class="imp-cat-pista">{pista}<br>Ejemplo de línea: <i>{html.escape(ejemplo)}</i></p>
    <label class="imp-o" for="archivo_{tipo}">Archivo .txt</label>
    <input type="file" id="archivo_{tipo}" name="archivo_{tipo}" accept=".txt,text/plain">
    <p class="imp-o">o pega aquí la lista, una frase por línea</p>
    <textarea name="texto_{tipo}" placeholder="Una frase por línea...">{valor}</textarea>
  </div>
</div>'''

    body = f'''
{_imp_cabecera()}
<div class="imp-wrap">
  <h1 class="imp-titulo serif">Importar premisas desde archivos de texto</h1>
  <p class="imp-sub">Trae las frases de golpe desde tus propios archivos, en lugar de
  escribirlas una a una.</p>

  {error_html}

  <div class="imp-ayuda">
    <strong>Cómo funciona</strong>
    Cada historia que genera la máquina se arma con tres piezas:
    <div class="imp-ejemplo"><b>Después de ganar la lotería,</b> una adolescente descarada ingresa en una milicia.</div>
    <ol>
      <li>Abre el Bloc de notas (o TextEdit) y escribe <strong>una frase por línea</strong>.</li>
      <li>Guarda el archivo como <strong>.txt</strong>. Un archivo por cada pieza.</li>
      <li>Súbelos abajo. No hace falta traer las tres: puedes importar sólo una.</li>
    </ol>
    Si prefieres, copia la lista y pégala directamente en la casilla de texto.
  </div>

  <form method="POST" action="/importar/revisar" enctype="multipart/form-data">

    <div class="imp-paso">
      <div class="imp-paso-cab"><span class="imp-paso-num">1</span>
        <span class="imp-paso-tit">¿Dónde quieres guardarlas?</span></div>
      <div class="imp-paso-cuerpo">
        <label class="imp-opcion">
          <input type="radio" name="destino" value="existente"{r_exist} onchange="impDestino()">
          <span class="imp-opcion-txt"><strong>En un perfil que ya existe</strong>
            <span>Las frases se suman a las que ya tiene ese perfil.</span>
            <select class="imp-campo" id="imp-perfil" name="perfil">{opciones}</select>
          </span>
        </label>
        <label class="imp-opcion">
          <input type="radio" name="destino" value="nuevo"{r_nuevo} onchange="impDestino()">
          <span class="imp-opcion-txt"><strong>Crear un perfil nuevo</strong>
            <span>Se crea vacío y se llena con lo que subas ahora.</span>
            <input type="text" class="imp-campo" id="imp-nombre" name="nombre_nuevo"
                   value="{nombre_nuevo}" placeholder="ej: 2 ESO, Taller de verano..." maxlength="40">
            <label class="imp-check"><input type="checkbox" id="imp-activar" name="activar"
                   value="si"{activar_chk}> Usarlo como perfil activo al terminar</label>
          </span>
        </label>
      </div>
    </div>

    <div class="imp-paso" id="imp-modo-bloque">
      <div class="imp-paso-cab"><span class="imp-paso-num">2</span>
        <span class="imp-paso-tit">¿Qué hacemos con lo que ya hay?</span></div>
      <div class="imp-paso-cuerpo">
        <label class="imp-opcion">
          <input type="radio" name="modo" value="anadir"{'' if modo == 'reemplazar' else ' checked'}>
          <span class="imp-opcion-txt"><strong>Añadir al final</strong>
            <span>Se conserva todo lo que había y las frases nuevas se colocan detrás.
            Las que ya estuvieran no se duplican.</span></span>
        </label>
        <label class="imp-opcion">
          <input type="radio" name="modo" value="reemplazar"{' checked' if modo == 'reemplazar' else ''}>
          <span class="imp-opcion-txt"><strong>Reemplazar la lista</strong>
            <span>Se borra lo que había y queda sólo lo que subes ahora. Se guarda una
            copia de seguridad y podrás deshacerlo justo después.</span></span>
        </label>
        <p class="imp-nota" id="imp-modo-nota" style="display:none">
          Un perfil nuevo empieza vacío, así que este paso no se aplica.</p>
      </div>
    </div>

    <div class="imp-paso">
      <div class="imp-paso-cab"><span class="imp-paso-num">3</span>
        <span class="imp-paso-tit">Los textos</span></div>
      <div class="imp-paso-cuerpo">{cats}
        <p class="imp-nota">Las categorías que dejes vacías no se modifican.</p>
      </div>
    </div>

    <div class="imp-acciones">
      <button type="submit" class="imp-btn">Revisar antes de guardar</button>
      <a href="/" class="imp-btn2">Cancelar</a>
    </div>
  </form>
</div>
<script>
function impDestino() {{
  var nuevo = document.querySelector('input[name=destino][value=nuevo]').checked;
  document.getElementById('imp-perfil').disabled  = nuevo;
  document.getElementById('imp-nombre').disabled  = !nuevo;
  document.getElementById('imp-activar').disabled = !nuevo;
  var b = document.getElementById('imp-modo-bloque');
  b.className = nuevo ? 'imp-paso imp-desactivado' : 'imp-paso';
  b.querySelectorAll('input[name=modo]').forEach(function(r) {{ r.disabled = nuevo; }});
  document.getElementById('imp-modo-nota').style.display = nuevo ? 'block' : 'none';
}}
impDestino();
</script>'''
    return _page_wrap("Importar premisas", body, CSS_IMPORTAR)


def _render_revision(token, perfil, nuevo, modo, activar, analisis, perfil_activo):
    detalle  = analisis['detalle']
    reemplaza = modo == 'reemplazar'
    p_esc = html.escape(perfil.upper())

    destino_txt = (f'perfil nuevo <strong>{p_esc}</strong>' if nuevo
                   else f'perfil <strong>{p_esc}</strong>')
    if not nuevo and perfil == perfil_activo:
        destino_txt += ' (el que está en uso ahora mismo)'
    modo_txt = ('Se reemplaza la lista de cada categoría que traes'
                if reemplaza else 'Se añaden al final de lo que ya hay')
    if nuevo:
        modo_txt = 'El perfil se crea vacío y se llena con estas frases'

    filas = ''
    for tipo in importador.TIPOS:
        d = detalle.get(tipo)
        if not d:
            n = analisis['finales'][tipo]
            filas += (f'<tr><td>{LABELS[tipo]}</td>'
                      f'<td class="imp-cifra imp-intacta">{n}</td>'
                      f'<td class="imp-intacta">No has traído nada'
                      f'<span class="imp-nota">Esta lista se queda como está.</span></td>'
                      f'<td class="imp-cifra imp-intacta">{n}</td></tr>')
            continue
        notas = []
        if d['repetidas']:
            notas.append(f"{d['repetidas']} línea(s) repetida(s) dentro del archivo")
        if d['ya_estaban']:
            notas.append(f"{d['ya_estaban']} ya estaba(n) en el perfil")
        if d['largas']:
            notas.append(f"{d['largas']} línea(s) demasiado larga(s), descartada(s)")
        if d['truncado']:
            notas.append(f"sólo se admiten {importador.MAX_LINEAS} por categoría: el resto se ha cortado")
        nota_html = f'<span class="imp-nota">{html.escape(" · ".join(notas))}</span>' if notas else ''

        if reemplaza and d['eliminadas']:
            cambio = (f'<span class="imp-menos">−{d["eliminadas"]}</span> / '
                      f'<span class="imp-mas">+{len(d["nuevas"])}</span>')
        else:
            cambio = f'<span class="imp-mas">+{len(d["nuevas"])}</span>'

        filas += (f'<tr><td>{LABELS[tipo]}</td>'
                  f'<td class="imp-cifra">{d["actuales"]}</td>'
                  f'<td>{cambio}{nota_html}</td>'
                  f'<td class="imp-cifra"><strong>{d["resultantes"]}</strong></td></tr>')

    muestra = ''
    for tipo in importador.TIPOS:
        d = detalle.get(tipo)
        if not d or not d['muestra']:
            continue
        items = ''.join(f'<li>{html.escape(l)}</li>' for l in d['muestra'])
        resto = len(d['nuevas']) - len(d['muestra'])
        extra = f'<li class="imp-intacta">… y {resto} más</li>' if resto > 0 else ''
        muestra += (f'<span class="imp-muestra-cat">{LABELS[tipo]}</span>'
                    f'<ul>{items}{extra}</ul>')
    if muestra:
        muestra = (f'<div class="imp-muestra"><h3>Así se van a guardar las primeras</h3>'
                   f'{muestra}</div>')

    avisos = ''
    if reemplaza:
        total_borradas = sum(d['eliminadas'] for d in detalle.values())
        if total_borradas:
            cats = ', '.join(LABELS[t].lower() for t, d in detalle.items() if d['eliminadas'])
            avisos += (f'<div class="imp-error"><strong>Vas a borrar {total_borradas} '
                       f'premisa(s)</strong>Se sustituyen las listas de {cats}. '
                       'Se guardará una copia de seguridad: en la pantalla siguiente '
                       'tendrás un botón para deshacerlo.</div>')
    if (not nuevo and perfil == perfil_activo) or (nuevo and activar):
        avisos += ('<div class="imp-aviso"><strong>Las frases nuevas entran en juego al guardar</strong>'
                   'Este es el perfil que usa la máquina, así que recargará las listas. '
                   'Eso vuelve a poner el contador a cero: alguna combinación que ya haya '
                   'salido en esta sesión podría repetirse.</div>')
    if analisis['vacias']:
        faltan = ', '.join(LABELS[t].lower() for t in analisis['vacias'])
        avisos += (f'<div class="imp-aviso"><strong>Faltará contenido en: {faltan}</strong>'
                   'La máquina necesita al menos una frase en cada una de las tres '
                   'categorías para poder montar una historia. Puedes guardar ahora y '
                   'traer el resto en otra importación: el perfil no funcionará hasta '
                   'que las tres tengan algo.</div>')
    if nuevo and not activar:
        avisos += ('<div class="imp-aviso"><strong>El perfil quedará creado, pero no activo</strong>'
                   'Para usarlo, elígelo en «Perfil activo», arriba en el panel.</div>')

    boton = ('<button type="submit" class="imp-btn imp-btn-rojo">Sí, reemplazar y guardar</button>'
             if reemplaza and any(d['eliminadas'] for d in detalle.values())
             else '<button type="submit" class="imp-btn">Guardar</button>')

    body = f'''
{_imp_cabecera()}
<div class="imp-wrap">
  <h1 class="imp-titulo serif">Revisa antes de guardar</h1>
  <p class="imp-sub">Todavía no se ha modificado nada. Esto es lo que pasaría:<br>
  Destino: {destino_txt} · {modo_txt}.</p>

  {avisos}

  <table class="imp-tabla">
    <tr><th>Categoría</th><th>Tiene ahora</th><th>Cambio</th><th>Se quedará con</th></tr>
    {filas}
  </table>

  {muestra}

  <form method="POST" action="/importar/confirmar">
    <input type="hidden" name="token" value="{html.escape(token)}">
    <div class="imp-acciones">
      {boton}
      <a href="/importar" class="imp-btn2">Volver y cambiar algo</a>
    </div>
  </form>
</div>'''
    return _page_wrap("Revisar importación", body, CSS_IMPORTAR)


def _render_resultado(perfil, tocados, recargado, activado, nuevo, modo, vacias=()):
    p_esc = html.escape(perfil.upper())
    lineas = ''
    for tipo, t in tocados.items():
        if t['eliminadas']:
            lineas += (f'<li><strong>{LABELS[tipo]}</strong>: lista reemplazada — '
                       f'{t["eliminadas"]} fuera, {t["anadidas"]} dentro '
                       f'({t["total"]} en total).</li>')
        else:
            lineas += (f'<li><strong>{LABELS[tipo]}</strong>: {t["anadidas"]} añadida(s) '
                       f'({t["total"]} en total).</li>')
    if not lineas:
        lineas = '<li>No había nada nuevo que guardar.</li>'

    pendiente = ''
    if vacias:
        faltan = ', '.join(LABELS[t].lower() for t in vacias)
        pendiente = (f'<div class="imp-aviso"><strong>Te falta: {faltan}</strong>'
                     f'El perfil {p_esc} todavía no puede generar historias: hacen falta '
                     'frases en las tres categorías. Vuelve a importar para completarlo.</div>')

    extras = ''
    if nuevo:
        extras += f'<p class="imp-nota">Perfil {p_esc} creado.</p>'
    if activado:
        extras += f'<p class="imp-nota">{p_esc} es ahora el perfil activo.</p>'
    if recargado:
        extras += ('<p class="imp-nota">La máquina ya ha recargado las listas: '
                   'las frases nuevas pueden salir en la siguiente historia.</p>')

    primer_tipo = next(iter(tocados), 'detonantes')
    body = f'''
{_imp_cabecera()}
<div class="imp-wrap">
  <h1 class="imp-titulo serif">Importación terminada</h1>
  <div class="imp-ok"><strong>Guardado en {p_esc}</strong>
    <ul class="imp-resumen">{lineas}</ul>
  </div>
  {pendiente}
  {extras}
  <div class="imp-acciones">
    <a href="/perfil/{html.escape(perfil)}/{primer_tipo}" class="imp-btn">Ver las premisas</a>
    <a href="/importar?perfil={html.escape(perfil)}" class="imp-btn2">Importar más</a>
    <a href="/" class="imp-btn2">Volver al panel</a>
  </div>
  <form method="POST" action="/importar/deshacer" style="margin-top:1.75rem"
        onsubmit="return confirm('¿Deshacer la importación y dejar las listas como estaban?')">
    <button type="submit" class="imp-btn2">↶ Deshacer esta importación</button>
    <p class="imp-nota">Disponible mientras no hagas otra importación.</p>
  </form>
</div>'''
    return _page_wrap("Importación terminada", body, CSS_IMPORTAR)


def _render_mensaje(titulo, texto, ok=True, perfil=None):
    clase = 'imp-ok' if ok else 'imp-error'
    ver = (f'<a href="/perfil/{html.escape(perfil)}/detonantes" class="imp-btn2">Ver las premisas</a>'
           if perfil else '')
    body = f'''
{_imp_cabecera()}
<div class="imp-wrap">
  <h1 class="imp-titulo serif">{html.escape(titulo)}</h1>
  <div class="{clase}">{html.escape(texto)}</div>
  <div class="imp-acciones">
    <a href="/" class="imp-btn">Volver al panel</a>
    <a href="/importar" class="imp-btn2">Importar premisas</a>
    {ver}
  </div>
</div>'''
    return _page_wrap(titulo, body, CSS_IMPORTAR)


# ------------------------------------------------------------------ #
# Clase Portal (lanzada desde main.py)                                #
# ------------------------------------------------------------------ #
class Portal:
    def __init__(self, config):
        self.puerto = config.get('portal', {}).get('puerto', 5000)

        # Secret persistente por dispositivo: se genera una vez y se guarda en config.json.
        # Así cada Pi tiene su propia clave de sesión y no se puede falsificar una cookie
        # de un dispositivo para usarla en otro.
        secret = config.get('flask_secret')
        if not secret:
            secret = secrets.token_hex(32)
            config['flask_secret'] = secret
            guardar_config(config)
            print("[Portal] Clave de sesión generada y guardada en config.json")
        app.secret_key = secret

        self._hilo  = None

    def iniciar(self):
        self._hilo = threading.Thread(
            target=lambda: app.run(
                host='0.0.0.0', port=self.puerto,
                debug=False, use_reloader=False
            ),
            daemon=True
        )
        self._hilo.start()
        print(f"[Portal] Servidor web en http://0.0.0.0:{self.puerto}")
