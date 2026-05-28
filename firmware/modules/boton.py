"""
boton.py — Polling seguro para Bookworm (sin edge detection).

Usa un hilo de polling a 50Hz con debounce por conteo de lecturas.
GPIO5 → botón (pull-up interno, activo LOW)
GPIO23 → LED
"""

import time
import threading
import subprocess
from typing import Callable, Optional

try:
    import RPi.GPIO as GPIO
    GPIO_DISPONIBLE = True
except ImportError:
    GPIO_DISPONIBLE = False
    print("[Boton] AVISO: RPi.GPIO no disponible. Modo simulación activo.")


class SimpleLED:
    def __init__(self, pin, active_high=True):
        self.pin = pin
        self.active_high = active_high
        if GPIO_DISPONIBLE:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW if active_high else GPIO.HIGH)

    def on(self):
        if GPIO_DISPONIBLE:
            GPIO.output(self.pin, GPIO.HIGH if self.active_high else GPIO.LOW)

    def off(self):
        if GPIO_DISPONIBLE:
            GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)

    def blink(self, on_time=0.2, off_time=0.2, n=3):
        for _ in range(n):
            self.on()
            time.sleep(on_time)
            self.off()
            time.sleep(off_time)


class Boton:
    """
    Gestiona el botón físico con polling.

    Pulsación corta → accion_corta()
    Pulsación larga → accion_larga() + apagado seguro
    """

    def __init__(self, config_boton, config_led):
        self.pin_boton          = config_boton.get('pin_gpio', 5)
        self.tiempo_largo       = config_boton.get('tiempo_pulsacion_larga', 2)
        self._callback_corto: Optional[Callable] = None
        self._callback_largo: Optional[Callable] = None
        self._parar   = False
        self._armado  = False
        self._largo_procesado = False

        if GPIO_DISPONIBLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

        self.led = SimpleLED(config_led.get('pin_gpio', 23), active_high=True)

        if GPIO_DISPONIBLE:
            GPIO.setup(self.pin_boton, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Estado pulsado = LOW (pull-up activo)
        self.pressed_state = GPIO.LOW if GPIO_DISPONIBLE else 0

        # Espera de estabilización al arranque (evita falsos positivos)
        time.sleep(2)
        self._armado = True

        threading.Thread(target=self._poll_loop, daemon=True).start()
        print(f"[Boton] Armado: GPIO{self.pin_boton} + LED GPIO{config_led.get('pin_gpio', 23)}")

    def _poll_loop(self):
        # Inicializar con el estado REAL del botón al arrancar: si ya está
        # pulsado (ej. usuario encendiendo con el dedo en el botón), no se
        # detecta como transición y no se dispara un shutdown inesperado.
        if GPIO_DISPONIBLE:
            estado_anterior = (GPIO.input(self.pin_boton) == self.pressed_state)
        else:
            estado_anterior = False
        lecturas_consistentes = 0

        while not self._parar:
            if not self._armado:
                time.sleep(0.05)
                continue

            if GPIO_DISPONIBLE:
                activo = (GPIO.input(self.pin_boton) == self.pressed_state)
            else:
                activo = False

            if activo != estado_anterior:
                lecturas_consistentes += 1
                if lecturas_consistentes >= 3:          # debounce: 3 lecturas × 20ms = 60ms
                    if activo:
                        self._al_presionar()
                    else:
                        self._al_soltar()
                    estado_anterior = activo
                    lecturas_consistentes = 0
            else:
                lecturas_consistentes = 0

            time.sleep(0.02)

    def _al_presionar(self):
        print("[Boton] Pulsación detectada")
        threading.Thread(target=self._vigilar_pulsacion_larga, daemon=True).start()

    def _vigilar_pulsacion_larga(self):
        """Comprueba si sigue pulsado tras el umbral de pulsación larga."""
        time.sleep(self.tiempo_largo)
        if not self._parar and GPIO_DISPONIBLE:
            muestras = sum(
                1 for _ in range(10)
                if GPIO.input(self.pin_boton) == self.pressed_state
            )
            if muestras >= 7:
                print("[Boton] Pulsación LARGA confirmada")
                self._largo_procesado = True
                # El LED lo gestiona main.py (apagado antes del shutdown)
                if self._callback_largo:
                    self._callback_largo()

    def _al_soltar(self):
        print("[Boton] Botón soltado")
        if self._largo_procesado:          # ← añadir
            self._largo_procesado = False  # ← añadir
            return                         # ← añadir
        if self._callback_corto:
            try:
                threading.Thread(target=self._callback_corto, daemon=True).start()
            except Exception as e:
                print(f"[Boton] Error en callback corto: {e}")

    def on_corto(self, cb: Callable):
        self._callback_corto = cb
        return self

    def on_largo(self, cb: Callable):
        self._callback_largo = cb
        return self

    def parpadear(self, veces=3, intervalo=0.2):
        self.led.blink(on_time=intervalo, off_time=intervalo, n=veces)

    def shutdown_seguro(self):
        # Tres parpadeos rápidos → LED se apaga → sistema se apaga
        self.parpadear(3, 0.15)
        self.led.off()
        time.sleep(0.3)
        subprocess.run(['sudo', 'shutdown', '-h', 'now'], check=False)

    def limpiar(self):
        self._parar = True
        if GPIO_DISPONIBLE:
            GPIO.cleanup()
        print("[Boton] GPIO liberado.")
