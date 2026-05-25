"""
salidas.py — Router de hardware.
Lee la sección 'hardware' del config.json y carga solo los módulos
marcados como activados. Expone dos métodos principales:
  - enviar(texto)               — envío directo, sin animación
  - enviar_con_animacion(texto) — flujo con imagen "pensando" si hay e-ink,
                                  paralelo eink+audio si ambos están activos
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RouterSalidas:
    """
    Inicializa los módulos de hardware activos y despacha el texto
    a todas las salidas configuradas.
    """
    def __init__(self, config_hardware: dict):
        self.eink      = None
        self.impresora = None
        self.audio     = None
        self._errores  = []

        self._init_eink(config_hardware.get('eink', {}))
        self._init_impresora(config_hardware.get('impresora', {}))
        self._init_audio(config_hardware.get('audio', {}))

        activas = self.salidas_activas()
        if activas:
            print(f"[Router] Salidas activas: {', '.join(activas)}")
        else:
            print("[Router] AVISO: ninguna salida de hardware activa.")

    # ------------------------------------------------------------------ #
    # Inicialización individual                                            #
    # ------------------------------------------------------------------ #
    def _init_eink(self, cfg: dict):
        if not cfg.get('activada', False):
            return
        try:
            from modules.eink import PantallaEInk
            self.eink = PantallaEInk(cfg)
            print("[Router] E-ink cargada.")
        except Exception as e:
            self._errores.append(f"eink: {e}")
            print(f"[Router] ERROR al cargar e-ink: {e}")

    def _init_impresora(self, cfg: dict):
        if not cfg.get('activada', False):
            return
        try:
            from modules.impresora import Impresora
            self.impresora = Impresora(cfg)
            print("[Router] Impresora cargada.")
        except Exception as e:
            self._errores.append(f"impresora: {e}")
            print(f"[Router] AVISO al cargar impresora: {e}. Continuando sin impresora.")

    def _init_audio(self, cfg: dict):
        if not cfg.get('activada', False):
            return
        try:
            from modules.audio import Audio
            self.audio = Audio(cfg)
            print("[Router] Audio cargado.")
        except Exception as e:
            self._errores.append(f"audio: {e}")
            print(f"[Router] ERROR al cargar audio: {e}")

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #
    def salidas_activas(self) -> list:
        activas = []
        if self.eink:      activas.append('eink')
        if self.impresora: activas.append('impresora')
        if self.audio:     activas.append('audio')
        return activas

    def hay_salidas(self) -> bool:
        return bool(self.salidas_activas())

    def enviar(self, texto: str) -> dict:
        """
        Envía el texto a todas las salidas activas en serie.
        Sin animación. Útil para mensajes de sistema (agotadas, etc.).
        """
        resultados = {}

        if self.eink:
            try:
                self.eink.mostrar_texto(texto)
                resultados['eink'] = True
            except Exception as e:
                print(f"[Router] Error en e-ink: {e}")
                resultados['eink'] = False

        if self.impresora:
            try:
                self.impresora.imprimir(texto)
                resultados['impresora'] = True
            except Exception as e:
                print(f"[Router] Error en impresora: {e}")
                resultados['impresora'] = False

        if self.audio:
            try:
                self.audio.hablar(texto)
                resultados['audio'] = True
            except Exception as e:
                print(f"[Router] Error en audio: {e}")
                resultados['audio'] = False

        return resultados

    def enviar_con_animacion(self, texto: str) -> dict:
        """
        Envía el texto con animación inteligente según las salidas activas:

        CON e-ink:
          1. Muestra imagen 'pensando' (~4s refresco)
          2. En paralelo: eink premisa + audio
             → el audio arranca mientras la pantalla refresca

        SIN e-ink (solo audio / impresora):
          → Envío directo, sin espera de pantalla

        La impresora siempre va en paralelo al audio si ambos están activos.
        """
        resultados = {}

        if self.eink:
            # ── Flujo CON e-ink ──────────────────────────────────────────
            # Fase 1: imagen pensando
            try:
                self.eink.mostrar_pensando()
                resultados['eink_pensando'] = True
            except Exception as e:
                print(f"[Router] Error mostrando pensando: {e}")
                resultados['eink_pensando'] = False

            # Fase 2: eink premisa + audio en paralelo
            errores = {}

            def _mostrar_premisa():
                try:
                    self.eink.mostrar_texto(texto)
                    resultados['eink'] = True
                except Exception as e:
                    print(f"[Router] Error en e-ink premisa: {e}")
                    resultados['eink'] = False
                    errores['eink'] = e

            def _hablar():
                try:
                    self.audio.hablar(texto)
                    resultados['audio'] = True
                except Exception as e:
                    print(f"[Router] Error en audio: {e}")
                    resultados['audio'] = False
                    errores['audio'] = e

            hilos = [threading.Thread(target=_mostrar_premisa, daemon=True)]
            if self.audio:
                hilos.append(threading.Thread(target=_hablar, daemon=True))

            for h in hilos:
                h.start()
            for h in hilos:
                h.join()

        else:
            # ── Flujo SIN e-ink: directo ─────────────────────────────────
            if self.audio:
                try:
                    self.audio.hablar(texto)
                    resultados['audio'] = True
                except Exception as e:
                    print(f"[Router] Error en audio: {e}")
                    resultados['audio'] = False

        # Impresora: siempre al final (no bloquea la experiencia principal)
        if self.impresora:
            try:
                self.impresora.imprimir(texto)
                resultados['impresora'] = True
            except Exception as e:
                print(f"[Router] Error en impresora: {e}")
                resultados['impresora'] = False

        return resultados

    def mostrar_bienvenida(self):
        """Muestra/imprime bienvenida en todas las salidas activas."""
        if self.eink:
            try:
                self.eink.mostrar_bienvenida()
            except Exception as e:
                print(f"[Router] Error en bienvenida e-ink: {e}")
        if self.impresora:
            try:
                self.impresora.imprimir_bienvenida()
            except Exception as e:
                print(f"[Router] Error en bienvenida impresora: {e}")

    def mostrar_despedida(self):
        """Muestra/imprime despedida en todas las salidas activas."""
        if self.eink:
            try:
                self.eink.mostrar_despedida()
            except Exception as e:
                print(f"[Router] Error en despedida e-ink: {e}")
        if self.impresora:
            try:
                self.impresora.imprimir_despedida()
            except Exception as e:
                print(f"[Router] Error en despedida impresora: {e}")

    def cerrar(self):
        """Cierra/apaga todos los módulos de forma segura."""
        if self.eink:
            try: self.eink.apagar()
            except Exception: pass
        if self.impresora:
            try: self.impresora.cerrar()
            except Exception: pass
