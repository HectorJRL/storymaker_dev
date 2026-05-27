# StoryMaker — Contexto del proyecto para Claude Code

## Qué es
Dispositivo educativo basado en Raspberry Pi Zero 2W para talleres literarios.
Genera premisas narrativas aleatorias combinando detonantes + protagonistas + conflictos
desde ficheros .txt por perfil. Las salidas son: pantalla e-ink, impresora térmica y audio TTS.

## Hardware
- **SBC:** Raspberry Pi Zero 2W
- **OS:** Raspberry Pi OS Lite 64-bit Bookworm (estable)
- **Usuario sistema:** `storymaker` (uid 1000, dueño del proyecto y del servicio)
- **Directorio proyecto:** `/home/storymaker/proyecto`

### Pinout definitivo (BCM)
| Función | GPIO |
|---|---|
| Botón físico | 5 |
| LED estado | 23 |
| E-ink DC | 25 |
| E-ink RST | 17 |
| E-ink BUSY | 24 |
| E-ink SPI0 MOSI | 10 |
| E-ink SPI0 CLK | 11 |
| E-ink SPI0 CS0 | 8 |
| Impresora UART TX | 14 |
| Impresora UART RX | 15 |
| Audio I2S BCLK | 18 |
| Audio I2S LRCLK | 19 |
| Audio I2S DATA | 21 |

### Periféricos
- **E-ink:** WeAct 4.2" B&W (controlador SSD1683) — refresco parcial NO soportado
- **Impresora:** QR701 UART térmica (ESC/POS, QR nativo GS(k) modelo 2)
- **Audio:** MAX98357A I2S — TTS con edge-tts (es-ES-ElviraNeural) + mpg123
- **Fallback TTS offline:** espeak (voz sintética local, entra cuando no hay red)

## Estructura del proyecto
El repo de Codeberg contiene el proyecto completo (código, STL, esquemas, manuales…).
La parte de software para la Pi/SD está en el directorio `firmware/`, que es lo que se despliega.

```
/home/storymaker/proyecto/   ← contenido de firmware/ desplegado en la SD
├── main.py                  # Punto de entrada, bucle principal
├── config.json              # Configuración activa (perfil, hardware, portal)
├── config_manager.py        # Lectura/escritura atómica del JSON con lock
├── modules/
│   ├── boton.py             # Polling GPIO, LED, callbacks corto/largo
│   ├── eink.py              # SSD1683 WeAct, SPI fragmentado a 4000 bytes
│   ├── impresora.py         # QR701 ESC/POS, QR nativo, bienvenida/despedida
│   ├── audio.py             # edge-tts + mpg123
│   ├── salidas.py           # Orquesta eink+audio+impresora, animación pluma
│   ├── generador.py         # Genera frases desde .txt por perfil
│   └── portal.py            # Flask web (puerto 5000), login PIN, gestión perfiles
├── data/
│   ├── pluma.png            # Animación e-ink "pensando"
│   └── perfiles/
│       └── <nombre>/        # Cada perfil: detonantes.txt, protagonistas.txt, conflictos.txt
└── deploy/
    └── deploy.sh            # Despliega vía SSH+sshpass (sube por /tmp)
```

## Configuraciones del sistema (fuera del repo)
Estas deben aplicarse manualmente en cada SD nueva:
1. `/etc/sudoers.d/storymaker-shutdown` — dos líneas NOPASSWD:
   - `/usr/sbin/shutdown` (botón físico)
   - `/usr/bin/systemctl restart historias.service` (portal web)
2. `/etc/systemd/system/historias.service`
3. `/usr/local/bin/storymaker-wifi.sh` y `storymaker-captive.py`
4. `/etc/NetworkManager/conf.d/` — sin `wifi.backend=nl80211`
5. `netfilter-persistent` para iptables del portal cautivo
6. `NetworkManager-wait-online.service` deshabilitado

## Red / WiFi
- NetworkManager gestiona wlan0
- mDNS via avahi → `storymaker.local:5000`
- Sin red conocida → AP "StoryMaker-Setup" (abierto, 10.42.0.1)
- Portal cautivo Flask en puerto 8080; iptables redirige 80→8080
- Script: `/usr/local/bin/storymaker-wifi.sh`

## Comportamiento del LED (GPIO 23)
- Encendido fijo → sistema listo
- Parpadeo → feedback de pulsación
- Apagado → en proceso de shutdown

## Decisiones técnicas importantes
- GPIO con `RPi.GPIO` + polling por software (sin lgpio, sin gpiozero, sin edge detection)
- SPI fragmentado a 4000 bytes para evitar `OverflowError`
- `eink.py` usa secuencia de inicialización SSD1683 WeAct oficial (no Waveshare)
- Audio TTS: `edge-tts` genera MP3 → `mpg123` reproduce
- `config_manager.py` usa lock + escritura atómica para evitar corrupción JSON concurrente
- Animación e-ink: `pluma.png` pre-renderizada al arrancar; se muestra mientras genera
- Portal web: slider volumen con debounce 400ms; restart servicio via `subprocess.Popen` con `start_new_session=True`
- `journald`: Storage=auto (volátil) — no saturar SD en producción

## Deploy
- Empaqueta en `storymaker.tar.gz` y despliega con `deploy/deploy.sh` via SSH
- Sube por `/tmp` para evitar problemas de permisos
- Repo privado de desarrollo: Codeberg (`storymaker_dev`)

## Deuda técnica conocida
- `setup_sd.sh` desactualizado — pendiente redactar uno nuevo que refleje el estado actual
- Eleven Labs como opción TTS premium (no implementado)
- journald `Storage=persistent` activado en mayo 2026 para debug — revertir a `auto` en producción