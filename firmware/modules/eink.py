"""
eink.py — Driver para WeAct Studio 4.2" B&W (SSD1683 / EPD420).
Secuencia de init y display extraída directamente del código de referencia
oficial de WeAct (epaper.c, EPD420 branch):
  github.com/WeActStudio/WeActStudio.EpaperModule
Pinout (SPI0):
  GPIO10 → MOSI (SDA)
  GPIO11 → CLK  (SCL)
  GPIO8  → CS   (CE0, gestionado por spidev)
  GPIO25 → D/C
  GPIO17 → RST  (RES)
  GPIO24 → BUSY
"""
import time
from PIL import Image, ImageDraw, ImageFont
try:
    import spidev
    import RPi.GPIO as GPIO
    SPIDEV_DISPONIBLE = True
except ImportError:
    SPIDEV_DISPONIBLE = False
    print("[EInk] AVISO: spidev/RPi.GPIO no disponibles. Modo simulación activo.")


class EPD_4IN2:
    """
    Driver de bajo nivel para WeAct 4.2" BW (SSD1683).
    400 x 300 pixeles.
    """
    ANCHO = 400
    ALTO  = 300

    def __init__(self, spi_bus=0, spi_device=0, pines=None):
        self.pines    = pines or {}
        self.dc_pin   = self.pines.get('dc',   25)
        self.rst_pin  = self.pines.get('rst',  17)
        self.busy_pin = self.pines.get('busy', 24)

        if not SPIDEV_DISPONIBLE:
            print("[EInk] Modo simulacion activo.")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.dc_pin,   GPIO.OUT)
        GPIO.setup(self.rst_pin,  GPIO.OUT)
        GPIO.setup(self.busy_pin, GPIO.IN)   # sin pull, la placa WeAct lo lleva

        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = 4_000_000
        self.spi.mode = 0

        self._reset()
        self._init_display()
        print("[EInk] Hardware inicializado.")

    # ------------------------------------------------------------------ #
    # GPIO / SPI                                                           #
    # ------------------------------------------------------------------ #
    def _cmd(self, cmd: int):
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.xfer2([cmd])

    def _dat(self, data):
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(data, int):
            self.spi.xfer2([data])
        else:
            d = list(data)
            for i in range(0, len(d), 4096):
                self.spi.xfer2(d[i:i + 4096])

    def _reset(self):
        GPIO.output(self.rst_pin, GPIO.HIGH); time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.LOW);  time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH); time.sleep(0.05)

    def _esperar_idle(self, timeout_s=10.0):
        """HIGH = ocupado, LOW = libre (SSD1683)."""
        t0 = time.time()
        while GPIO.input(self.busy_pin) == GPIO.HIGH:
            if time.time() - t0 > timeout_s:
                print("[EInk] AVISO: timeout esperando BUSY.")
                break
            time.sleep(0.01)

    # ------------------------------------------------------------------ #
    # Inicializacion (secuencia EPD420 del fabricante WeAct)              #
    # ------------------------------------------------------------------ #
    def _address_set(self, x0, y0, x1, y1):
        self._cmd(0x44)
        self._dat((x0 >> 3) & 0xFF)
        self._dat((x1 >> 3) & 0xFF)
        self._cmd(0x45)
        self._dat(y0 & 0xFF)
        self._dat((y0 >> 8) & 0xFF)
        self._dat(y1 & 0xFF)
        self._dat((y1 >> 8) & 0xFF)

    def _setpos(self, x, y):
        self._cmd(0x4E)
        self._dat((x >> 3) & 0xFF)
        self._cmd(0x4F)
        self._dat(y & 0xFF)
        self._dat((y >> 8) & 0xFF)

    def _power_on(self):
        self._cmd(0x22)
        self._dat(0xe0)
        self._cmd(0x20)
        self._esperar_idle()

    def _init_display(self):
        # SWRESET
        self._cmd(0x12)
        time.sleep(0.01)
        self._esperar_idle()
        # Display Update Control (EPD420)
        self._cmd(0x21)
        self._dat(0x40)
        self._dat(0x00)
        # Driver output control: MUX=300
        self._cmd(0x01)
        self._dat(0x2B)
        self._dat(0x01)
        self._dat(0x00)
        # Border waveform
        self._cmd(0x3C)
        self._dat(0x01)
        # Data entry mode: X-mode (incremento X e Y)
        self._cmd(0x11)
        self._dat(0x03)
        # Ventana RAM completa
        self._address_set(0, 0, self.ANCHO - 1, self.ALTO - 1)
        # Sensor temperatura interno
        self._cmd(0x18)
        self._dat(0x80)
        # Cursor en origen
        self._setpos(0, 0)
        # Power ON
        self._power_on()

    # ------------------------------------------------------------------ #
    # API publica                                                          #
    # ------------------------------------------------------------------ #
    def imagen_a_frame(self, imagen: Image.Image) -> bytearray:
        """Convierte una imagen PIL a bytearray listo para enviar al display."""
        if imagen.mode != '1':
            imagen = imagen.convert('1')
        if imagen.size != (self.ANCHO, self.ALTO):
            imagen = imagen.resize((self.ANCHO, self.ALTO), Image.Resampling.LANCZOS)
        px    = imagen.load()
        frame = bytearray()
        for y in range(self.ALTO):
            for x in range(0, self.ANCHO, 8):
                byte = 0xFF
                for bit in range(8):
                    if x + bit < self.ANCHO and px[x + bit, y] == 0:
                        byte &= ~(0x80 >> bit)
                frame.append(byte)
        return frame

    def _escribir_frame(self, registro: int, frame: bytearray):
        self._setpos(0, 0)
        self._cmd(registro)
        self._dat(frame)

    def _actualizar(self):
        """Full refresh EPD420: 0x22->0xF7, 0x20, esperar BUSY."""
        self._cmd(0x22)
        self._dat(0xF7)
        self._cmd(0x20)
        self._esperar_idle()

    def mostrar_frame(self, frame: bytearray):
        """Muestra un frame ya convertido (bytearray). Más rápido si el frame
        está pre-calculado, evita reconvertir la imagen cada vez."""
        if not SPIDEV_DISPONIBLE:
            print("[EInk] Simulacion: mostrar_frame()")
            return
        self._escribir_frame(0x26, frame)
        self._escribir_frame(0x24, frame)
        self._actualizar()
        print("[EInk] Frame mostrado.")

    def mostrar(self, imagen: Image.Image):
        """Convierte y muestra una imagen PIL."""
        if not SPIDEV_DISPONIBLE:
            print(f"[EInk] Simulacion: imagen {imagen.size}")
            return
        frame = self.imagen_a_frame(imagen)
        self.mostrar_frame(frame)
        print("[EInk] Imagen actualizada.")

    def limpiar(self):
        frame = bytearray([0xFF] * (self.ANCHO // 8 * self.ALTO))
        self._escribir_frame(0x26, frame)
        self._escribir_frame(0x24, frame)
        self._actualizar()
        print("[EInk] Pantalla limpiada.")

    def sleep(self):
        if not SPIDEV_DISPONIBLE:
            return
        self._cmd(0x10)
        self._dat(0x01)
        print("[EInk] Modo sleep.")


class PantallaEInk:
    """Capa de alto nivel: renderiza texto e imágenes en la e-ink."""

    FUENTE_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    MARGEN      = 24
    TAM_FUENTE  = 24

    def __init__(self, config: dict):
        self.epd = EPD_4IN2(
            spi_bus=config.get('spi_bus', 0),
            spi_device=config.get('spi_device', 0),
            pines=config.get('pines', {})
        )
        # Frame de "pensando" pre-renderizado al arrancar (None si no hay imagen)
        self._frame_pensando = None
        self._preparar_frame_pensando()

    def _preparar_frame_pensando(self):
        """
        Pre-renderiza la imagen de 'pensando' al arrancar para no perder
        tiempo en el momento de la pulsación.
        Busca pluma.png en data/ junto al proyecto.
        """
        import os
        rutas_candidatas = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'pluma.png'),
            os.path.join(os.path.dirname(__file__), '..', 'data', 'pluma.png'),
        ]
        ruta_png = None
        for r in rutas_candidatas:
            if os.path.exists(r):
                ruta_png = r
                break

        if ruta_png is None:
            print("[EInk] AVISO: data/pluma.png no encontrado. Animación desactivada.")
            return

        try:
            img_orig = Image.open(ruta_png).convert('L')
            max_w, max_h = 380, 280
            ratio = min(max_w / img_orig.width, max_h / img_orig.height)
            nw = int(img_orig.width  * ratio)
            nh = int(img_orig.height * ratio)
            img_bw = img_orig.resize((nw, nh), Image.Resampling.LANCZOS).point(
                lambda p: 0 if p < 128 else 255, 'L')
            canvas = Image.new('1', (self.epd.ANCHO, self.epd.ALTO), 1)
            canvas.paste(img_bw.convert('1'),
                         ((self.epd.ANCHO - nw) // 2, (self.epd.ALTO - nh) // 2))
            self._frame_pensando = self.epd.imagen_a_frame(canvas)
            print("[EInk] Frame 'pensando' pre-renderizado.")
        except Exception as e:
            print(f"[EInk] AVISO: no se pudo preparar frame pensando: {e}")

    def mostrar_pensando(self):
        """Muestra la imagen de 'pensando'. Si no está disponible, no hace nada."""
        if self._frame_pensando is not None:
            self.epd.mostrar_frame(self._frame_pensando)

    def mostrar_texto(self, texto: str):
        ancho_util = self.epd.ANCHO - 2 * self.MARGEN
        img  = Image.new('1', (self.epd.ANCHO, self.epd.ALTO), 1)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(self.FUENTE_PATH, self.TAM_FUENTE)
        except Exception:
            font = ImageFont.load_default()

        palabras  = texto.split()
        lineas    = []
        linea_act = ""
        for palabra in palabras:
            prueba = (linea_act + " " + palabra).strip()
            bbox   = draw.textbbox((0, 0), prueba, font=font)
            if bbox[2] - bbox[0] <= ancho_util:
                linea_act = prueba
            else:
                if linea_act:
                    lineas.append(linea_act)
                linea_act = palabra
        if linea_act:
            lineas.append(linea_act)

        interlinea = self.TAM_FUENTE + 8
        bloque_h   = len(lineas) * interlinea
        y          = max(self.MARGEN, (self.epd.ALTO - bloque_h) // 2)
        for linea in lineas:
            bbox = draw.textbbox((0, 0), linea, font=font)
            x    = (self.epd.ANCHO - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), linea, font=font, fill=0)
            y += interlinea

        self.epd.mostrar(img)

    def mostrar_despedida(self):
        """
        Muestra pantalla de despedida: título + logo izquierda + QR derecha + instrucción.
        Se llama antes del shutdown físico y al desactivar eink desde el portal.
        """
        import os
        try:
            import qrcode as qrcode_lib
        except ImportError:
            print("[EInk] AVISO: qrcode no instalado. Mostrando pantalla en blanco.")
            self.epd.limpiar()
            return

        URL   = "https://codeberg.org/atrapavientos/storymaker.git"
        TITULO = "La asombrosa máquina de generar historias"
        INST   = "Escanea el QR para visitar el proyecto"
        W, H   = self.epd.ANCHO, self.epd.ALTO
        MARGEN = 18

        canvas = Image.new('1', (W, H), 1)
        draw   = ImageDraw.Draw(canvas)

        try:
            font_titulo = ImageFont.truetype(self.FUENTE_PATH, 20)
            font_inst   = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
        except Exception:
            font_titulo = font_inst = ImageFont.load_default()

        def wrap(texto, font, max_w):
            palabras = texto.split()
            lineas, linea = [], ''
            for p in palabras:
                prueba = (linea + ' ' + p).strip()
                if draw.textbbox((0, 0), prueba, font=font)[2] <= max_w:
                    linea = prueba
                else:
                    if linea: lineas.append(linea)
                    linea = p
            if linea: lineas.append(linea)
            return lineas

        # ── Título arriba ─────────────────────────────────────────────────
        lineas_tit = wrap(TITULO, font_titulo, W - 20)
        y_tit = MARGEN
        for l in lineas_tit:
            bbox = draw.textbbox((0, 0), l, font=font_titulo)
            draw.text(((W - (bbox[2]-bbox[0])) // 2, y_tit), l, font=font_titulo, fill=0)
            y_tit += 24

        # ── Instrucción abajo ─────────────────────────────────────────────
        lineas_inst = wrap(INST, font_inst, W - 20)
        inst_h = len(lineas_inst) * 19
        y_inst = H - inst_h - MARGEN
        for l in lineas_inst:
            bbox = draw.textbbox((0, 0), l, font=font_inst)
            draw.text(((W - (bbox[2]-bbox[0])) // 2, y_inst), l, font=font_inst, fill=0)
            y_inst += 19

        # ── Zona central ──────────────────────────────────────────────────
        y_medio_top = y_tit + 4
        medio_h     = H - inst_h - MARGEN - y_medio_top

        # Logo izquierda
        ruta_logo = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'data', 'logo_atrapa.png')
        lw = lh = 0
        if os.path.exists(ruta_logo):
            try:
                logo_orig   = Image.open(ruta_logo).convert('RGBA')
                logo_area_w = W // 2 - 10
                ratio = min(logo_area_w / logo_orig.width, medio_h / logo_orig.height)
                lw = int(logo_orig.width  * ratio)
                lh = int(logo_orig.height * ratio)
                logo_r  = logo_orig.resize((lw, lh), Image.Resampling.LANCZOS)
                logo_bg = Image.new('1', (lw, lh), 1)
                logo_bw = logo_r.convert('L').point(lambda p: 0 if p < 128 else 255, '1')
                mask    = logo_r.split()[3].point(lambda p: 255 if p > 128 else 0)
                logo_bg.paste(logo_bw, mask=mask)
                lx = (W // 2 - lw) // 2
                ly = y_medio_top + (medio_h - lh) // 2
                canvas.paste(logo_bg, (lx, ly))
            except Exception as e:
                print(f"[EInk] AVISO logo despedida: {e}")

        # QR derecha — 80% del logo
        logo_dim       = max(lw, lh) if lw else medio_h
        qr_size_target = int(logo_dim * 0.80)
        qr = qrcode_lib.QRCode(
            version=None,
            error_correction=qrcode_lib.constants.ERROR_CORRECT_M,
            box_size=3, border=2)
        qr.add_data(URL)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color='black', back_color='white').convert('1')
        img_qr = img_qr.resize((qr_size_target, qr_size_target), Image.Resampling.NEAREST)
        qx = W // 2 + (W // 2 - qr_size_target) // 2
        qy = y_medio_top + (medio_h - qr_size_target) // 2
        canvas.paste(img_qr, (qx, qy))

        self.epd.mostrar(canvas)
        print("[EInk] Pantalla de despedida mostrada.")

    def mostrar_bienvenida(self):
        """
        Muestra pantalla de bienvenida al arrancar.
        Detecta el modo de red y muestra QR + logo o advertencia según el caso.
        """
        import os
        try:
            import qrcode as qrcode_lib
        except ImportError:
            print("[EInk] AVISO: qrcode no instalado. Saltando bienvenida.")
            return

        from modules.netinfo import get_wifi_mode, get_ip

        W, H = self.epd.ANCHO, self.epd.ALTO
        TITULO = "La asombrosa máquina de generar historias"

        canvas = Image.new('1', (W, H), 1)
        draw   = ImageDraw.Draw(canvas)

        try:
            font_titulo = ImageFont.truetype(self.FUENTE_PATH, 20)
            font_inst   = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
            font_warn   = ImageFont.truetype(self.FUENTE_PATH, 28)
            font_sub    = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except Exception:
            font_titulo = font_inst = font_warn = font_sub = ImageFont.load_default()

        def wrap(texto, font, max_w):
            palabras = texto.split()
            lineas, linea = [], ''
            for p in palabras:
                prueba = (linea + ' ' + p).strip()
                if draw.textbbox((0, 0), prueba, font=font)[2] <= max_w:
                    linea = prueba
                else:
                    if linea: lineas.append(linea)
                    linea = p
            if linea: lineas.append(linea)
            return lineas

        def dibujar_titulo():
            lineas = wrap(TITULO, font_titulo, W - 20)
            y = 18
            for l in lineas:
                bbox = draw.textbbox((0, 0), l, font=font_titulo)
                draw.text(((W - (bbox[2]-bbox[0])) // 2, y), l, font=font_titulo, fill=0)
                y += 24
            return y

        # ── Detectar modo de red ──────────────────────────────────────────
        modo = get_wifi_mode()
        ip   = get_ip()

        if modo == 'client' and ip:
            url        = f"http://{ip}:5000"
            instruccion = "Bienvenido. Escanea el QR para abrir el portal."
        elif modo == 'ap':
            url        = "http://10.42.0.1:5000"
            instruccion = "Escanea el QR para configurar el WiFi."
        else:
            url        = None
            instruccion = None

        if url:
            # ── Variante CON QR ───────────────────────────────────────────
            y_tit = dibujar_titulo()

            # Instrucción abajo
            lineas_inst = wrap(instruccion, font_inst, W - 20)
            inst_h = len(lineas_inst) * 19
            y_inst = H - inst_h - 18
            for l in lineas_inst:
                bbox = draw.textbbox((0, 0), l, font=font_inst)
                draw.text(((W - (bbox[2]-bbox[0])) // 2, y_inst), l,
                          font=font_inst, fill=0)
                y_inst += 19

            # Zona central
            y_medio_top = y_tit + 4
            medio_h     = H - inst_h - 18 - y_medio_top

            # Logo izquierda
            rutas_logo = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'data', 'logo_atrapa.png'),
            ]
            ruta_logo = next((r for r in rutas_logo if os.path.exists(r)), None)
            lw = lh = 0
            if ruta_logo:
                logo_orig  = Image.open(ruta_logo).convert('RGBA')
                logo_area_w = W // 2 - 10
                ratio = min(logo_area_w / logo_orig.width, medio_h / logo_orig.height)
                lw = int(logo_orig.width  * ratio)
                lh = int(logo_orig.height * ratio)
                logo_r  = logo_orig.resize((lw, lh), Image.Resampling.LANCZOS)
                logo_bg = Image.new('1', (lw, lh), 1)
                logo_bw = logo_r.convert('L').point(lambda p: 0 if p < 128 else 255, '1')
                mask    = logo_r.split()[3].point(lambda p: 255 if p > 128 else 0)
                logo_bg.paste(logo_bw, mask=mask)
                lx = (W // 2 - lw) // 2
                ly = y_medio_top + (medio_h - lh) // 2
                canvas.paste(logo_bg, (lx, ly))

            # QR derecha — 80% de la dimensión mayor del logo
            logo_dim       = max(lw, lh) if lw else medio_h
            qr_size_target = int(logo_dim * 0.80)

            qr = qrcode_lib.QRCode(
                version=None,
                error_correction=qrcode_lib.constants.ERROR_CORRECT_M,
                box_size=3, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img_qr = qr.make_image(fill_color='black', back_color='white').convert('1')
            img_qr = img_qr.resize((qr_size_target, qr_size_target),
                                   Image.Resampling.NEAREST)
            qx = W // 2 + (W // 2 - qr_size_target) // 2
            qy = y_medio_top + (medio_h - qr_size_target) // 2
            canvas.paste(img_qr, (qx, qy))

        else:
            # ── Variante SIN RED ──────────────────────────────────────────
            y_tit = dibujar_titulo()
            y = y_tit + 6
            draw.line([(20, y), (W - 20, y)], fill=0, width=2)
            y += 12

            WARN1 = "SIN RED WIFI"
            WARN2 = "No se puede mostrar el portal."
            WARN3 = "Verifica la conexion y reinicia."

            espacio  = H - y - 10
            bloque   = 40 + 22 + 22
            y_warn   = y + (espacio - bloque) // 2

            bbox = draw.textbbox((0, 0), WARN1, font=font_warn)
            draw.text(((W - (bbox[2]-bbox[0])) // 2, y_warn), WARN1,
                      font=font_warn, fill=0)
            y_warn += 40
            for msg in [WARN2, WARN3]:
                bbox = draw.textbbox((0, 0), msg, font=font_sub)
                draw.text(((W - (bbox[2]-bbox[0])) // 2, y_warn), msg,
                          font=font_sub, fill=0)
                y_warn += 22

        self.epd.mostrar(canvas)
        print(f"[EInk] Bienvenida mostrada (modo={modo}, ip={ip}).")

    def limpiar(self):
        self.epd.limpiar()

    def apagar(self):
        self.epd.sleep()
