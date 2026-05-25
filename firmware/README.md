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

## Despliegue

Ver `deploy/sistema/README.md` para los pasos completos.
El servicio systemd se llama `historias.service` y corre como usuario `storymaker`.