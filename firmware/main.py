#!/usr/bin/env python3
"""
main.py — Punto de entrada StoryMaker v3.

Flujo:
  1. Carga config.json
  2. Inicia portal web (hilo daemon)
  3. Si setup no completado → avisa y espera en portal
  4. Inicia generador + salidas de hardware
  5. Configura botón y entra en bucle de espera
"""

import os
import sys
import time
import signal
import subprocess
import traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from modules.config_manager import cargar_config
from modules.generador      import Generador
from modules.boton          import Boton
from modules.salidas        import RouterSalidas
from modules.portal         import Portal


generador = None
router    = None
boton     = None


def al_pulsar_corto():
    """Genera una frase y la envía a todas las salidas activas."""
    global generador, router, boton

    if not generador or not router:
        return

    if not generador.hay_frases_disponibles():
        config  = cargar_config()
        mensaje = config.get('mensaje_sin_frases',
                             'Se han agotado las combinaciones. Reinicia el dispositivo.')
        print(f"[Main] Frases agotadas.")
        # Parpadeo lento: aviso de que no quedan premisas
        if boton:
            boton.led.off()
            boton.parpadear(5, 0.4)
            boton.led.on()
        router.enviar(mensaje)
        return

    # Parpadeo de confirmación mientras se genera/envía
    if boton:
        boton.led.off()
        boton.parpadear(2, 0.1)

    frase = generador.generar_frase()
    if frase is None:
        # Frases agotadas: otro hilo consumió la última entre la comprobación
        # anterior y este punto. Tratarlo igual que el caso de lista vacía.
        config  = cargar_config()
        mensaje = config.get('mensaje_sin_frases',
                             'Se han agotado las combinaciones. Reinicia el dispositivo.')
        print("[Main] Frases agotadas (detectado en generar_frase).")
        if boton:
            boton.led.off()
            boton.parpadear(5, 0.4)
            boton.led.on()
        router.enviar(mensaje)
        return

    resultados = router.enviar_con_animacion(frase)

    for salida, ok in resultados.items():
        icono = "✓" if ok else "✗"
        print(f"[Main] {icono} {salida}")

    # Volver a fijo: sistema listo para la siguiente pulsación
    if boton:
        boton.led.on()


def al_pulsar_largo():
    """Apagado seguro: muestra despedida y apaga."""
    print("[Main] → Pulsación larga: apagando...")
    if router:
        router.mostrar_despedida()
        router.cerrar()
    if boton:
        boton.shutdown_seguro()


def al_cambiar_perfil(nuevo_perfil):
    """Recarga el generador cuando el portal cambia el perfil activo."""
    global generador
    ruta_perfil = os.path.join(PROJECT_DIR, 'data', 'perfiles', nuevo_perfil)
    try:
        nuevo_generador = Generador(ruta_perfil)
        generador = nuevo_generador
        print(f"[Main] Perfil cambiado a '{nuevo_perfil}' — generador recargado.")
    except (FileNotFoundError, ValueError) as e:
        print(f"[Main] ERROR al cargar perfil '{nuevo_perfil}': {e}")


def cleanup(*args):
    print("[Main] Limpieza y salida.")
    if router:
        try: router.cerrar()
        except Exception: pass
    if boton:
        try: boton.limpiar()
        except Exception: pass
    sys.exit(0)


def main():
    global generador, router, boton

    print("=" * 50)
    print("  StoryMaker v3 — Arrancando...")
    print("=" * 50)

    # 1. Configuración
    try:
        config = cargar_config()
        print(f"[Main] Perfil activo: '{config.get('perfil_activo', '?')}'")
    except FileNotFoundError as e:
        print(f"[Main] ERROR CRÍTICO: {e}")
        sys.exit(1)

    # 2. Portal web (siempre, incluso antes del setup)
    portal = Portal(config)
    portal.iniciar()

    # 3. Si el setup no está completo, esperamos a que se configure desde el portal
    if not config.get('setup_completado', False):
        print("[Main] Setup no completado. Accede al portal para configurar el hardware.")
        print(f"[Main] http://<ip-de-la-pi>:{config.get('portal', {}).get('puerto', 5000)}")
        print("[Main] Esperando en modo portal...")
        signal.signal(signal.SIGINT,  cleanup)
        signal.signal(signal.SIGTERM, cleanup)
        while True:
            time.sleep(5)
            try:
                config_nueva = cargar_config()
                if config_nueva.get('setup_completado', False):
                    print("[Main] Setup completado. Reiniciando servicio...")
                    # Usar systemctl en lugar de os.execv: evita que el FD del
                    # socket Flask quede heredado y cause conflicto de puerto.
                    subprocess.Popen(
                        ['sudo', 'systemctl', 'restart', 'historias.service'],
                        start_new_session=True
                    )
                    sys.exit(0)
            except Exception:
                pass

    # 4. Generador de frases
    ruta_perfil = os.path.join(PROJECT_DIR, 'data', 'perfiles', config['perfil_activo'])
    try:
        generador = Generador(ruta_perfil)
    except (FileNotFoundError, ValueError) as e:
        print(f"[Main] ERROR CRÍTICO: {e}")
        sys.exit(1)

    # 5. Router de salidas (e-ink / impresora / audio)
    router = RouterSalidas(config.get('hardware', {}))
    if not router.hay_salidas():
        print("[Main] AVISO: ninguna salida configurada. Ve al portal → ⚙ Hardware.")

    # 6. Botón
    boton = Boton(config['boton'], config['led'])
    boton.on_corto(al_pulsar_corto)
    boton.on_largo(al_pulsar_largo)

    # Registrar callbacks en el portal (botón virtual web + cambio de perfil)
    from modules.portal import (registrar_callback_generar,
                                 registrar_callback_despedida,
                                 registrar_callback_cambiar_perfil)
    registrar_callback_generar(al_pulsar_corto)
    registrar_callback_despedida(router.mostrar_despedida)
    registrar_callback_cambiar_perfil(al_cambiar_perfil)

    # LED encendido fijo = sistema listo para generar premisas
    boton.led.on()
    router.mostrar_bienvenida()

    # 7. Señales del sistema
    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("[Main] Sistema listo. Esperando pulsaciones...")

    # 8. Bucle principal (el trabajo real lo hace el hilo del botón)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        print(f"[Main] Excepción fatal: {e}")
        traceback.print_exc()
        cleanup()
