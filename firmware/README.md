# StoryMaker — Firmware

Código Python que corre en la Raspberry Pi Zero 2W. Gestiona el botón físico,
las salidas (e-ink, impresora térmica, audio) y el portal web de configuración.

## Requisitos

- Raspberry Pi OS Lite 64-bit (Bookworm)
- Python 3.11+
- Entorno virtual en `proyecto/venv/`

## Estructura

firmware/
├── main.py              # Punto de entrada. Inicializa hardware y bucle principal
├── config.json          # Configuración activa (hardware, perfil, portal, PIN)
├── modules/
│   ├── boton.py         # Polling GPIO: pulsación corta/larga + LED
│   ├── eink.py          # Pantalla e-ink WeAct 4.2" (SSD1683, SPI0)
│   ├── audio.py         # Síntesis de voz edge-tts + reproducción mpg123
│   ├── impresora.py     # Impresora térmica QR701 UART (ESC/POS)
│   ├── generador.py     # Generador de premisas aleatorias desde perfiles .txt
│   ├── importador.py    # Importación masiva de premisas desde .txt (limpieza + copias)
│   ├── salidas.py       # Orquesta las salidas activas + animación e-ink
│   ├── portal.py        # Portal web Flask (puerto 5000): configuración y generación
│   ├── config_manager.py# Lectura/escritura atómica de config.json (thread-safe)
│   ├── netinfo.py       # Detecta modo de red (client/AP/none) para impresora/eink
│   └── init.py
└── data/
├── config.json          # Configuración activa
├── pluma.png            # Animación "pensando" para e-ink
├── logo_atrapa.png      # Logo del taller
└── perfiles/
└── 1eso/            # Perfil de ejemplo (1º ESO)
├── detonantes.txt
├── protagonistas.txt
└── conflictos.txt

## Salidas disponibles

| Salida | Módulo | Interfaz |
|---|---|---|
| Pantalla e-ink | eink.py | SPI0 (GPIO 10/11/8) + DC/RST/BUSY |
| Impresora térmica | impresora.py | UART (/dev/serial0, 9600 baud) |
| Audio | audio.py | I2S MAX98357A (GPIO 18/19/21) |

## Perfiles

Cada perfil es una carpeta en `data/perfiles/<nombre>/` con tres archivos .txt,
uno por línea: `detonantes.txt`, `protagonistas.txt`, `conflictos.txt`.
El perfil activo se configura en `config.json` → `perfil_activo`.

### Importar premisas en bloque

Desde el portal, `⇪ Importar .txt` (barra lateral, o en la cabecera de cualquier
lista de premisas) abre un asistente de tres pasos en `/importar`:

1. **Destino** — un perfil existente, o uno nuevo que se crea en el momento
   (con opción de dejarlo como perfil activo al terminar).
2. **Modo** — *añadir al final* (por defecto) o *reemplazar la lista*. En un
   perfil nuevo el paso no aplica.
3. **Textos** — un `.txt` por categoría, o la lista pegada a mano. Si se
   rellenan ambos para la misma categoría, se concatenan. Las categorías que se
   dejan vacías no se modifican.

Antes de escribir nada se muestra una **revisión**: cuántas frases entran, qué
se descarta (repetidas, ya existentes, demasiado largas) y cómo queda cada
categoría. Al confirmar se guarda un `<tipo>.txt.bak` por categoría tocada, de
modo que el botón **Deshacer** devuelve las listas a su estado anterior
(un solo nivel: la siguiente importación lo sustituye).

Si el destino es el perfil activo, el `Generador` se recarga al confirmar, lo
que reinicia el recuento de combinaciones de la sesión en curso.

Límites: 3 MB por envío, 5000 frases por categoría, 300 caracteres por frase.

## Despliegue

Ver `deploy/sistema/README.md` para los pasos completos.
El servicio systemd se llama `historias.service` y corre como usuario `storymaker`.