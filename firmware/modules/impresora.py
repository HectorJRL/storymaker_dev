"""
impresora.py — Comunicación con la impresora térmica QR701-N32 vía UART.
Firmware GB18030/PC936 sin posibilidad de cambio de codificación.
Solución: transliteración a ASCII + cancelación modo chino.
Pinout UART:
  GPIO14 → TX  (/dev/serial0)
"""
import time
import textwrap
try:
    import serial
    SERIAL_DISPONIBLE = True
except ImportError:
    SERIAL_DISPONIBLE = False
    print("[Impresora] AVISO: pyserial no disponible. Modo simulación activo.")

# Tabla de transliteración: caracteres españoles → ASCII legible
TRANSLITERACION = str.maketrans(
    'áéíóúÁÉÍÓÚàèìòùÀÈÌÒÙäëïöüÄËÏÖÜâêîôûÂÊÎÔÛñÑ¿¡«»',
    'aeiouAEIOUaeiouAEIOUaeiouAEIOUaeiouAEIOUnN?!  '
)

ANCHO = 32          # Caracteres por línea de la QR701

ESC             = b'\x1b'
GS              = b'\x1d'
FS              = b'\x1c'
INIT            = ESC + b'\x40'
CANCELAR_CHINO  = FS  + b'\x2e'
CHARSET_WESTERN = ESC + b'\x52\x00'
ALIGN_LEFT      = ESC + b'\x61\x00'
ALIGN_CENTER    = ESC + b'\x61\x01'
BOLD_ON         = ESC + b'\x45\x01'
BOLD_OFF        = ESC + b'\x45\x00'
FEED            = b'\n'

def transliterar(texto: str) -> str:
    return texto.translate(TRANSLITERACION)

def _qr_nativo(url: str, size: int = 5) -> bytes:
    """Genera comando ESC/POS para QR nativo (modelo 2)."""
    data = url.encode('ascii')
    n    = len(data) + 3
    nL   = n & 0xFF
    nH   = (n >> 8) & 0xFF
    cmd  = GS + b'\x28\x6b\x04\x00\x31\x41\x32\x00'          # modelo 2
    cmd += GS + b'\x28\x6b\x03\x00\x31\x43' + bytes([size])   # tamaño módulo
    cmd += GS + b'\x28\x6b\x03\x00\x31\x45\x31'               # corrección M
    cmd += GS + b'\x28\x6b' + bytes([nL, nH]) + b'\x31\x50\x30' + data
    cmd += GS + b'\x28\x6b\x03\x00\x31\x51\x30'               # imprimir
    return cmd


class Impresora:
    """Gestiona la conexión con la impresora térmica QR701 por UART."""

    def __init__(self, config: dict):
        self.puerto   = config.get('puerto',   '/dev/serial0')
        self.baudrate = config.get('baudrate', 9600)
        self.conexion = None
        if not SERIAL_DISPONIBLE:
            print("[Impresora] Modo simulación activo.")
            return
        self._conectar()

    def _conectar(self):
        try:
            self.conexion = serial.Serial(self.puerto, self.baudrate, timeout=1)
            self.conexion.write(INIT + CANCELAR_CHINO + CHARSET_WESTERN)
            time.sleep(0.1)
            print(f"[Impresora] Conectada en {self.puerto} a {self.baudrate} bps.")
        except Exception as e:
            raise ConnectionError(f"[Impresora] No se pudo conectar en {self.puerto}: {e}")

    # ------------------------------------------------------------------ #
    # Primitivas internas                                                  #
    # ------------------------------------------------------------------ #
    def _escribir(self, data: bytes):
        if self.conexion and self.conexion.is_open:
            self.conexion.write(data)

    def _feed(self, n: int = 1):
        self._escribir(FEED * n)

    def _linea_centrada(self, texto: str, bold: bool = False):
        self._escribir(ALIGN_CENTER)
        if bold: self._escribir(BOLD_ON)
        self._escribir(transliterar(texto).encode('ascii', errors='replace') + b'\n')
        if bold: self._escribir(BOLD_OFF)

    def _separador(self):
        self._escribir(ALIGN_LEFT)
        self._escribir(b'-' * ANCHO + b'\n')

    def _qr(self, url: str, size: int = 5):
        self._escribir(ALIGN_CENTER)
        self._escribir(_qr_nativo(url, size))

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #
    def imprimir(self, texto: str):
        """Imprime una premisa narrativa alineada a la izquierda con ajuste
        automático de línea (textwrap). Usa 4 saltos al final para que la
        última línea salga completamente de la cabeza de impresión antes de
        arrancar el papel (la QR701 tiene ~30 mm de distancia cabeza-borde).
        Llamado desde salidas.py para todas las premisas."""
        if not SERIAL_DISPONIBLE:
            print(f"[Impresora] Simulación: {texto}")
            return
        if not self.conexion or not self.conexion.is_open:
            print("[Impresora] ERROR: conexión no disponible.")
            return
        try:
            limpio   = transliterar(texto)
            ajustado = textwrap.fill(limpio, width=ANCHO)
            self._feed(2)
            self._escribir(ALIGN_LEFT)
            self._escribir(ajustado.encode('ascii', errors='replace'))
            self._feed(6)           # 6 saltos: asegura que el texto salga completamente de la carcasa
            time.sleep(0.5)
            print("[Impresora] Texto enviado.")
        except Exception as e:
            print(f"[Impresora] ERROR al imprimir: {e}")

    def imprimir_centrado(self, texto: str):
        """Imprime una sola línea centrada, sin ajuste de línea automático.
        Pensado para mensajes cortos de sistema (máx. 32 caracteres).
        No se usa actualmente desde salidas.py; disponible para uso futuro."""
        if not SERIAL_DISPONIBLE:
            print(f"[Impresora] Simulación centrado: {texto}")
            return
        if not self.conexion or not self.conexion.is_open:
            return
        try:
            self._feed(1)
            self._linea_centrada(texto)
            self._feed(3)
            time.sleep(0.5)
        except Exception as e:
            print(f"[Impresora] ERROR: {e}")

    def imprimir_bienvenida(self):
        """
        Imprime cabecera de bienvenida con QR del portal.
        Detecta el modo de red igual que la e-ink.
        """
        if not SERIAL_DISPONIBLE or not self.conexion or not self.conexion.is_open:
            return
        try:
            from modules.netinfo import get_wifi_mode, get_ip
            modo = get_wifi_mode()
            ip   = get_ip()

            self._feed(2)
            self._linea_centrada("La asombrosa maquina", bold=True)
            self._linea_centrada("de generar historias", bold=True)
            self._separador()

            if modo == 'client' and ip:
                url = f"http://{ip}:5000"
                self._feed(1)
                self._linea_centrada("Bienvenido.")
                self._linea_centrada("Escanea el QR para")
                self._linea_centrada("abrir el portal:")
                self._feed(1)
                self._qr(url, size=5)
                self._feed(1)
                self._linea_centrada(url)
            elif modo == 'ap':
                url = "http://10.42.0.1:8080"
                self._feed(1)
                self._linea_centrada("Escanea el QR para")
                self._linea_centrada("configurar el WiFi:")
                self._feed(1)
                self._qr(url, size=5)
                self._feed(1)
                self._linea_centrada(url)
            else:
                self._feed(1)
                self._linea_centrada("*** SIN RED WIFI ***", bold=True)
                self._linea_centrada("No se puede mostrar")
                self._linea_centrada("el portal.")
                self._linea_centrada("Verifica la conexion")
                self._linea_centrada("y reinicia.")

            self._separador()
            self._feed(3)
            time.sleep(0.5)
            print(f"[Impresora] Bienvenida impresa (modo={modo}, ip={ip}).")
        except Exception as e:
            print(f"[Impresora] ERROR en bienvenida: {e}")

    def imprimir_despedida(self):
        """
        Imprime pie de despedida con QR del repositorio.
        """
        if not SERIAL_DISPONIBLE or not self.conexion or not self.conexion.is_open:
            return
        try:
            url = "https://codeberg.org/atrapavientos/storymaker.git"

            self._feed(2)
            self._separador()
            self._linea_centrada("La asombrosa maquina", bold=True)
            self._linea_centrada("de generar historias", bold=True)
            self._separador()
            self._feed(1)
            self._linea_centrada("Escanea el QR para")
            self._linea_centrada("visitar el proyecto:")
            self._feed(1)
            self._qr(url, size=4)
            self._feed(1)
            self._linea_centrada("codeberg.org/")
            self._linea_centrada("atrapavientos/storymaker")
            self._separador()
            self._feed(4)
            time.sleep(0.5)
            print("[Impresora] Despedida impresa.")
        except Exception as e:
            print(f"[Impresora] ERROR en despedida: {e}")

    def cerrar(self):
        if self.conexion and self.conexion.is_open:
            self.conexion.close()
            print("[Impresora] Conexión cerrada.")
