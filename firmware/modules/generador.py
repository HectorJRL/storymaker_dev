"""
generador.py — Carga y gestión de las premisas narrativas.

Al arrancar la sesión carga los tres .txt del perfil activo y baraja
su contenido. Cada llamada a generar_frase() devuelve una combinación
única mediante pop(). Una vez usada, una premisa no vuelve a aparecer
hasta el próximo arranque.
"""

import os
import random
import threading


class Generador:

    def __init__(self, ruta_perfil):
        self.detonantes    = self._cargar_lista(ruta_perfil, 'detonantes.txt')
        self.protagonistas = self._cargar_lista(ruta_perfil, 'protagonistas.txt')
        self.conflictos    = self._cargar_lista(ruta_perfil, 'conflictos.txt')

        random.shuffle(self.detonantes)
        random.shuffle(self.protagonistas)
        random.shuffle(self.conflictos)

        # Lock para atomizar la comprobación + extracción de frases:
        # evita IndexError si botón físico y portal web coinciden en el tiempo.
        self._lock = threading.Lock()

        print(f"[Generador] Sesión iniciada: {len(self.detonantes)} detonantes, "
              f"{len(self.protagonistas)} protagonistas, {len(self.conflictos)} conflictos.")

    def _cargar_lista(self, ruta_perfil, nombre_archivo):
        ruta = os.path.join(ruta_perfil, nombre_archivo)
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"No se encontró: {ruta}")
        with open(ruta, 'r', encoding='utf-8') as f:
            lineas = [l.strip().rstrip('.,;: ') for l in f if l.strip()]
        if not lineas:
            raise ValueError(
                f"El archivo '{nombre_archivo}' está vacío o solo contiene "
                "líneas en blanco. Añade al menos una entrada.")
        return lineas

    def hay_frases_disponibles(self):
        return (len(self.detonantes) > 0 and
                len(self.protagonistas) > 0 and
                len(self.conflictos) > 0)

    def frases_restantes(self):
        return min(len(self.detonantes), len(self.protagonistas), len(self.conflictos))

    def generar_frase(self):
        """Extrae una frase de forma atómica. Devuelve None si no quedan frases
        (incluido el caso en que otro hilo consumió la última simultáneamente)."""
        with self._lock:
            if not self.hay_frases_disponibles():
                return None
            d = self.detonantes.pop()
            p = self.protagonistas.pop()
            c = self.conflictos.pop()
            restantes = self.frases_restantes()
        frase = f"{d}, {p}, {c}."
        print(f"[Generador] Frase: {frase}")
        print(f"[Generador] Restantes: {restantes}")
        return frase
