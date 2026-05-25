"""
config_manager.py — Punto único de acceso a config.json.
Escritura atómica con lock para evitar corrupción por concurrencia.
"""
import json
import os
import threading
import tempfile

RUTA_CONFIG = os.path.join(os.path.dirname(__file__), '..', 'data', 'config.json')
_lock = threading.Lock()

def cargar_config() -> dict:
    ruta = os.path.abspath(RUTA_CONFIG)
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"config.json no encontrado en: {ruta}")
    with _lock:
        with open(ruta, 'r', encoding='utf-8') as f:
            contenido = f.read().strip()
        if not contenido:
            raise ValueError("config.json está vacío")
        return json.loads(contenido)

def guardar_config(config: dict):
    ruta = os.path.abspath(RUTA_CONFIG)
    directorio = os.path.dirname(ruta)
    with _lock:
        # Escritura atómica: escribe en temporal y luego renombra
        fd, tmp = tempfile.mkstemp(dir=directorio, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            os.replace(tmp, ruta)  # atómico en Linux
        except Exception:
            os.unlink(tmp)
            raise
