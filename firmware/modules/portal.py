#!/usr/bin/env python3
"""
portal.py — Interfaz web de gestión StoryMaker.
Rutas:
  /             → panel principal (requiere login)
  /login        → formulario PIN
  /logout
  /setup        → configuración de hardware (primer arranque)
  /perfil/<n>/<tipo>  → ver/editar premisas
  /api/*        → endpoints JSON
Se lanza en un hilo separado (daemon) para no bloquear main.py.
"""
import os
import tempfile
import threading
from functools import wraps
from flask import Flask, request, session, redirect, url_for, jsonify
from modules.config_manager import cargar_config, guardar_config

BASE_DIR     = os.path.join(os.path.dirname(__file__), '..')
PERFILES_DIR = os.path.join(BASE_DIR, 'data', 'perfiles')
PIN_DEFAULT  = "1234"

app = Flask(__name__)
app.secret_key = "storymaker-secret-2025"

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
            f.write('\n'.join(premisas))
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
    if request.method == 'POST':
        config = cargar_config()
        if request.form.get('pin') == config.get('pin', PIN_DEFAULT):
            session['autenticado'] = True
            if not config.get('setup_completado', False):
                return redirect(url_for('setup'))
            return redirect(url_for('index'))
        error = "PIN incorrecto"
    return _render_login(error)

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

@app.route('/api/nuevo_perfil', methods=['POST'])
@login_requerido
def nuevo_perfil():
    data   = request.get_json()
    nombre = data.get('nombre', '').strip().lower().replace(' ', '_')
    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre vacío'})
    ruta = os.path.abspath(os.path.join(PERFILES_DIR, nombre))
    if os.path.exists(ruta):
        return jsonify({'ok': False, 'error': 'Ya existe ese perfil'})
    os.makedirs(ruta)
    for tipo in ['detonantes', 'protagonistas', 'conflictos']:
        open(os.path.join(ruta, f'{tipo}.txt'), 'w').close()
    return jsonify({'ok': True, 'perfil': nombre})

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
def _render_login(error=None):
    error_html = f'<p class="form-error">{error}</p>' if error else ''
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
  margin-bottom: 2rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid var(--border);
}
.form-label {
  display: block; font-size: .72rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .08em;
  color: var(--ink2); margin-bottom: .5rem;
}
.pin-input {
  width: 100%; padding: .9rem 1rem;
  border: 1.5px solid var(--border);
  font-size: 1.6rem; letter-spacing: .4em;
  text-align: center; background: var(--paper);
  color: var(--ink); outline: none;
  transition: border-color .15s;
  -webkit-text-security: disc;
}
.pin-input:focus { border-color: var(--accent); }
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
  <form method="POST">
    <label class="form-label" for="pin">PIN de acceso</label>
    <input class="pin-input" type="password" id="pin" name="pin"
           maxlength="8" autofocus autocomplete="current-password"
           inputmode="numeric" placeholder="· · · ·">
    <button class="login-btn" type="submit">Entrar</button>
  </form>
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
      <p class="toggle-desc">WeAct Studio 4.2" · SSD1619 · SPI0</p>
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
      <p class="nota">4–8 dígitos. PIN actual: {config.get('pin', PIN_DEFAULT)}</p>
    </div>

    <button class="submit-btn" type="submit">{btn_label}</button>
  </form>
  {back_link}
</div>
<script>
function toggleBaud(v) {{
  document.getElementById('baud-wrap').style.display = v ? 'block' : 'none';
}}
function toggleVol(v) {{
  document.getElementById('vol-wrap').style.display = v ? 'block' : 'none';
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
    <span class="premisas-total">{len(premisas)} premisas</span>
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
# Clase Portal (lanzada desde main.py)                                #
# ------------------------------------------------------------------ #
class Portal:
    def __init__(self, config):
        self.puerto = config.get('portal', {}).get('puerto', 5000)
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
