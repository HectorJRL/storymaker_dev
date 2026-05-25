#!/usr/bin/env python3
"""
storymaker-captive.py
Portal cautivo de configuración WiFi. Solo activo en modo AP.
- Rutas de detección captive portal para iOS, Android, Windows
- Desplegable con redes WiFi detectadas
- Guarda la red con perfil persistente nmcli
- Feedback real con polling de estado
Instalar en: /usr/local/bin/storymaker-captive.py
"""
import subprocess, threading, time, json, re
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

# Estado compartido de la última conexión intentada
_estado = {"intentando": False, "resultado": None, "ssid": ""}
_estado_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────
# CSS — diseño tipográfico editorial, optimizado para móvil
# ─────────────────────────────────────────────────────────────
CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Sans+3:wght@400;600&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --ink:    #1a1a2e;
    --paper:  #f5f0e8;
    --accent: #c0392b;
    --muted:  #888;
    --ok-bg:  #e8f5e9;
    --ok-fg:  #2e7d32;
    --err-bg: #fde8e8;
    --err-fg: #c0392b;
  }

  html { font-size: 16px; }

  body {
    font-family: 'Source Sans 3', sans-serif;
    background: var(--paper);
    background-image:
      radial-gradient(circle at 20% 80%, rgba(192,57,43,0.05) 0%, transparent 50%),
      radial-gradient(circle at 80% 20%, rgba(26,26,46,0.04) 0%, transparent 50%);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }

  .card {
    background: white;
    border: 2px solid var(--ink);
    padding: clamp(1.5rem, 5vw, 2.5rem);
    width: 100%;
    max-width: 420px;
    box-shadow: 5px 5px 0 var(--ink);
    position: relative;
  }

  .card::before {
    content: '';
    position: absolute;
    top: -6px; left: -6px;
    right: 6px; bottom: 6px;
    border: 1px solid rgba(26,26,46,0.15);
    pointer-events: none;
  }

  .logo {
    font-family: 'Playfair Display', serif;
    font-size: clamp(1.6rem, 5vw, 2rem);
    color: var(--ink);
    letter-spacing: -0.02em;
    line-height: 1;
  }

  .logo span { color: var(--accent); }

  .sub {
    color: var(--muted);
    font-size: .85rem;
    margin-top: .4rem;
    margin-bottom: 1.75rem;
    border-bottom: 1px solid #eee;
    padding-bottom: 1rem;
  }

  label {
    display: block;
    font-size: .7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: var(--muted);
    margin-bottom: .4rem;
    margin-top: 1.1rem;
  }

  select, input[type="text"], input[type="password"] {
    width: 100%;
    padding: .8rem .9rem;
    border: 2px solid #ddd;
    border-radius: 0;
    font-size: 1rem;
    font-family: inherit;
    background: white;
    color: var(--ink);
    outline: none;
    transition: border-color .15s;
    appearance: none;
    -webkit-appearance: none;
  }

  select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%231a1a2e' stroke-width='2' fill='none'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 1rem center;
    padding-right: 2.5rem;
    cursor: pointer;
  }

  select:focus, input:focus { border-color: var(--ink); }

  #ssid-manual {
    margin-top: .5rem;
    display: none;
  }

  .show-manual-link {
    font-size: .78rem;
    color: var(--muted);
    text-decoration: underline;
    cursor: pointer;
    display: block;
    margin-top: .4rem;
    background: none;
    border: none;
    font-family: inherit;
    text-align: left;
    padding: 0;
  }

  .show-manual-link:hover { color: var(--ink); }

  .signal-icon { margin-right: .4em; font-size: .9em; }

  button[type="submit"] {
    width: 100%;
    margin-top: 1.5rem;
    padding: .9rem;
    background: var(--ink);
    color: white;
    border: 2px solid var(--ink);
    font-size: .9rem;
    font-family: inherit;
    font-weight: 600;
    letter-spacing: .05em;
    cursor: pointer;
    transition: background .15s, color .15s;
  }

  button[type="submit"]:hover {
    background: var(--accent);
    border-color: var(--accent);
  }

  button[type="submit"]:active { transform: translate(2px, 2px); }

  .msg {
    margin-top: 1.1rem;
    padding: .8rem 1rem;
    font-size: .85rem;
    text-align: center;
    line-height: 1.5;
  }

  .ok  { background: var(--ok-bg);  color: var(--ok-fg);  }
  .err { background: var(--err-bg); color: var(--err-fg); }

  .spinner {
    display: inline-block;
    width: 1em; height: 1em;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin .7s linear infinite;
    vertical-align: middle;
    margin-right: .4em;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .footer {
    margin-top: 1.5rem;
    font-size: .72rem;
    color: #bbb;
    text-align: center;
    border-top: 1px solid #f0f0f0;
    padding-top: .8rem;
  }
"""

# ─────────────────────────────────────────────────────────────
# Utilidades de red
# ─────────────────────────────────────────────────────────────

def escanear_redes():
    """Devuelve lista de (ssid, señal_dbm, seguridad) ordenada por señal."""
    try:
        subprocess.run(
            ['nmcli', 'device', 'wifi', 'rescan', 'ifname', 'wlan0'],
            timeout=8, capture_output=True
        )
        time.sleep(2)
    except Exception:
        pass

    try:
        out = subprocess.run(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', 'ifname', 'wlan0'],
            timeout=10, capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        return []

    vistas = set()
    redes = []
    for linea in out.splitlines():
        partes = linea.split(':')
        if len(partes) < 2:
            continue
        ssid = partes[0].strip()
        if not ssid or ssid == 'StoryMaker-Setup' or ssid in vistas:
            continue
        vistas.add(ssid)
        try:
            signal = int(partes[1]) if partes[1].isdigit() else 0
        except Exception:
            signal = 0
        security = partes[2].strip() if len(partes) > 2 else ''
        redes.append((ssid, signal, security))

    redes.sort(key=lambda x: x[1], reverse=True)
    return redes


def signal_icon(dbm):
    if dbm >= 75: return '▂▄▆█'
    if dbm >= 50: return '▂▄▆_'
    if dbm >= 25: return '▂▄__'
    return '▂___'


def guardar_y_conectar(ssid, password):
    """Guarda la red como perfil persistente y conecta."""
    with _estado_lock:
        _estado['intentando'] = True
        _estado['resultado'] = None
        _estado['ssid'] = ssid

    try:
        # Eliminar perfil anterior con mismo SSID si existe
        subprocess.run(
            ['nmcli', 'connection', 'delete', ssid],
            timeout=10, capture_output=True
        )
    except Exception:
        pass

    try:
        if password:
            cmd = [
                'nmcli', 'connection', 'add',
                'type', 'wifi',
                'con-name', ssid,
                'ifname', 'wlan0',
                'ssid', ssid,
                '802-11-wireless-security.key-mgmt', 'wpa-psk',
                '802-11-wireless-security.psk', password,
                'connection.autoconnect', 'yes',
                'connection.autoconnect-priority', '10',
            ]
        else:
            cmd = [
                'nmcli', 'connection', 'add',
                'type', 'wifi',
                'con-name', ssid,
                'ifname', 'wlan0',
                'ssid', ssid,
                'connection.autoconnect', 'yes',
                'connection.autoconnect-priority', '10',
            ]

        r = subprocess.run(cmd, timeout=15, capture_output=True, text=True)
        if r.returncode != 0:
            with _estado_lock:
                _estado['resultado'] = 'error_add'
                _estado['intentando'] = False
            return

        # Activar la conexión
        r2 = subprocess.run(
            ['nmcli', 'connection', 'up', ssid, 'ifname', 'wlan0'],
            timeout=30, capture_output=True, text=True
        )

        if r2.returncode == 0:
            with _estado_lock:
                _estado['resultado'] = 'ok'
        else:
            # Conexión fallida → limpiar perfil guardado para no reconectar con datos malos
            subprocess.run(['nmcli', 'connection', 'delete', ssid],
                           timeout=10, capture_output=True)
            with _estado_lock:
                _estado['resultado'] = 'error_connect'

    except subprocess.TimeoutExpired:
        subprocess.run(['nmcli', 'connection', 'delete', ssid],
                       timeout=5, capture_output=True)
        with _estado_lock:
            _estado['resultado'] = 'timeout'
    except Exception as e:
        print(f"[Captive] Excepción: {e}")
        with _estado_lock:
            _estado['resultado'] = 'error_connect'
    finally:
        with _estado_lock:
            _estado['intentando'] = False


# ─────────────────────────────────────────────────────────────
# Rutas captive portal — responden a todos los detectores
# (iOS, Android, Windows, macOS)
# ─────────────────────────────────────────────────────────────

CAPTIVE_REDIRECT = "http://10.42.0.1:8080/"

@app.route('/generate_204')           # Android / Chrome
@app.route('/gen_204')
def gen204():
    return redirect(CAPTIVE_REDIRECT, code=302)

@app.route('/hotspot-detect.html')    # Apple / macOS / iOS
@app.route('/library/test/success.html')
@app.route('/success.txt')
def apple_detect():
    # Apple espera el texto "Success" para considerar que hay internet,
    # pero si respondemos redirect, abre el navegador con la URL indicada.
    return redirect(CAPTIVE_REDIRECT, code=302)

@app.route('/ncsi.txt')               # Windows NCSI
@app.route('/connecttest.txt')
def windows_detect():
    return redirect(CAPTIVE_REDIRECT, code=302)

@app.route('/redirect')              # Varios Android
@app.route('/canonical.html')
def generic_redirect():
    return redirect(CAPTIVE_REDIRECT, code=302)


# ─────────────────────────────────────────────────────────────
# Página principal — formulario con desplegable
# ─────────────────────────────────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    redes = escanear_redes()

    if redes:
        opciones_html = '<option value="">— Selecciona una red —</option>\n'
        for ssid, signal, security in redes:
            icono = signal_icon(signal)
            lock = ' 🔒' if security and security != '--' else ''
            opciones_html += f'<option value="{ssid}">{icono} {ssid}{lock}</option>\n'
        selector = f"""
          <select id="ssid-select" name="ssid-select" onchange="seleccionarRed(this.value)">
            {opciones_html}
          </select>
          <button type="button" class="show-manual-link" onclick="toggleManual()">
            ¿No aparece tu red? Escríbela manualmente
          </button>
          <input type="text" id="ssid-manual" name="ssid" placeholder="Nombre de la red (SSID)"
                 autocomplete="off" autocapitalize="none" spellcheck="false">
        """
        script = """
          function seleccionarRed(val) {
            const manual = document.getElementById('ssid-manual');
            if (val) {
              manual.value = val;
              manual.style.display = 'none';
            }
          }
          function toggleManual() {
            const manual = document.getElementById('ssid-manual');
            const sel = document.getElementById('ssid-select');
            const visible = manual.style.display === 'block';
            manual.style.display = visible ? 'none' : 'block';
            if (!visible) {
              manual.value = '';
              manual.focus();
              sel.value = '';
            }
          }
          // Preseleccionar la primera red
          document.addEventListener('DOMContentLoaded', function() {
            const sel = document.getElementById('ssid-select');
            if (sel && sel.options.length > 1) {
              sel.selectedIndex = 1;
              seleccionarRed(sel.options[1].value);
            }
          });
        """
    else:
        selector = """
          <input type="text" id="ssid-manual" name="ssid" placeholder="Nombre de la red (SSID)"
                 required autofocus autocomplete="off" autocapitalize="none" spellcheck="false"
                 style="display:block">
        """
        script = ""

    n_redes = f"{len(redes)} redes detectadas" if redes else "Sin redes detectadas"

    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="theme-color" content="#1a1a2e">
<title>StoryMaker — WiFi</title>
<style>{CSS}</style>
</head><body>
<div class="card">
  <div class="logo">Story<span>Maker</span></div>
  <p class="sub">Conecta el dispositivo a tu red WiFi &nbsp;·&nbsp; {n_redes}</p>

  <form method="POST" action="/conectar" onsubmit="return validar()">
    <label>Red WiFi</label>
    {selector}

    <label for="password">Contraseña</label>
    <input type="password" id="password" name="password"
           placeholder="Contraseña (vacía si es abierta)"
           autocomplete="current-password">

    <button type="submit">Conectar →</button>
  </form>

  <div class="footer">StoryMaker · Portal de configuración WiFi</div>
</div>
<script>
  {script}
  function validar() {{
    const manual = document.getElementById('ssid-manual');
    const sel = document.getElementById('ssid-select');
    const ssid = (manual && manual.value.trim()) || (sel && sel.value);
    if (!ssid) {{
      alert('Selecciona o escribe el nombre de una red WiFi.');
      return false;
    }}
    if (manual) manual.value = ssid;
    return true;
  }}
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# POST /conectar — lanza la conexión en background
# ─────────────────────────────────────────────────────────────

@app.route('/conectar', methods=['POST'])
def conectar():
    ssid     = (request.form.get('ssid') or request.form.get('ssid-manual') or '').strip()
    password = request.form.get('password', '').strip()

    if not ssid:
        return redirect('/')

    # Lanzar en hilo separado
    threading.Thread(
        target=guardar_y_conectar,
        args=(ssid, password),
        daemon=True
    ).start()

    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="theme-color" content="#1a1a2e">
<title>Conectando...</title>
<style>{CSS}</style>
</head><body>
<div class="card">
  <div class="logo">Story<span>Maker</span></div>
  <p class="sub">Conectando a la red WiFi</p>

  <div class="msg ok" id="status-msg">
    <span class="spinner"></span>
    Conectando a <strong>{ssid}</strong>…
  </div>

  <div id="result-area"></div>

  <div class="footer">
    Si la contraseña es correcta, el dispositivo se conectará
    y recordará esta red para el futuro.
  </div>
</div>
<script>
  var ssid = {json.dumps(ssid)};
  var intentos = 0;
  var maxIntentos = 20;  // 40 segundos máximo

  function checkEstado() {{
    fetch('/estado')
      .then(r => r.json())
      .then(data => {{
        intentos++;
        if (data.intentando && intentos < maxIntentos) {{
          setTimeout(checkEstado, 2000);
          return;
        }}
        var msg = document.getElementById('status-msg');
        var result = document.getElementById('result-area');
        if (data.resultado === 'ok') {{
          msg.className = 'msg ok';
          msg.innerHTML = '✓ Conectado a <strong>' + ssid + '</strong>';
          result.innerHTML = '<div class="msg ok" style="margin-top:.5rem">La red ha sido guardada. El dispositivo la recordará en futuros arranques.<br><br>Puedes cerrar esta ventana.</div>';
        }} else if (data.resultado === 'timeout') {{
          msg.className = 'msg err';
          msg.innerHTML = '⚠ Tiempo de espera agotado';
          result.innerHTML = '<div class="msg err" style="margin-top:.5rem">No se pudo conectar. Puede que la red esté fuera de alcance.<br><br><a href="/" style="color:inherit">← Intentar de nuevo</a></div>';
        }} else if (data.resultado) {{
          msg.className = 'msg err';
          msg.innerHTML = '✗ No se pudo conectar';
          result.innerHTML = '<div class="msg err" style="margin-top:.5rem">Comprueba la contraseña o acércate al router.<br><br><a href="/" style="color:inherit">← Intentar de nuevo</a></div>';
        }} else {{
          // Sin resultado aún pero agotamos intentos
          msg.className = 'msg err';
          msg.innerHTML = '⚠ Sin respuesta';
          result.innerHTML = '<div class="msg err" style="margin-top:.5rem"><a href="/" style="color:inherit">← Volver</a></div>';
        }}
      }})
      .catch(() => {{
        // Si el fetch falla, puede ser porque la Pi ya cambió de red (éxito)
        intentos++;
        if (intentos < maxIntentos) {{
          setTimeout(checkEstado, 2000);
        }}
      }});
  }}

  setTimeout(checkEstado, 3000);
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# API de estado — para el polling del cliente
# ─────────────────────────────────────────────────────────────

@app.route('/estado')
def estado():
    with _estado_lock:
        return jsonify({
            'intentando': _estado['intentando'],
            'resultado': _estado['resultado'],
            'ssid': _estado['ssid'],
        })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
