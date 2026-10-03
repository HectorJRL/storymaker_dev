# Decisiones técnicas

- GPIO con `RPi.GPIO` + polling software (sin lgpio, sin gpiozero, sin edge detection)
- SPI fragmentado a 4000 bytes para evitar `OverflowError`
- `eink.py` usa secuencia de inicialización SSD1683 WeAct oficial (no Waveshare)
- Audio TTS: `edge-tts` genera MP3 → `mpg123` reproduce
- `config_manager.py` usa lock + escritura atómica para evitar corrupción JSON concurrente
- Animación e-ink: `pluma.png` pre-renderizada al arrancar; se muestra mientras genera
- Portal web: slider volumen con debounce 400ms; restart servicio via `subprocess.Popen` con `start_new_session=True`
- `journald`: Storage=auto (volátil) — no saturar SD en producción
- Importación de premisas (`importador.py`): flujo de tres pantallas
  (formulario → revisión → confirmación) porque el usuario final no es técnico;
  nada se escribe hasta confirmar
  - Decodifica UTF-8/BOM y reintenta CP1252 y Latin-1: los .txt llegan de Word
    y del Bloc de notas de Windows
  - Deduplica sin distinguir mayúsculas ni espacios múltiples, pero **no** toca
    la puntuación: el `Generador` ya recorta la final al cargar
  - Copia `<tipo>.txt.bak` antes de escribir → botón «Deshacer» de un nivel
  - Las categorías que el usuario deja vacías no se tocan, ni en modo reemplazar
  - Avisa si una categoría quedaría a cero: el `Generador` lanza `ValueError`
    con una lista vacía y `main.py` se quedaría con el perfil anterior en silencio
  - Al importar sobre el perfil activo se recarga el `Generador` reutilizando
    `_callback_cambiar_perfil`; eso reinicia el contador de combinaciones y el
    portal lo avisa
  - Revisión pendiente en memoria (token + sesión, 15 min), no en campos ocultos:
    menos RAM y menos tráfico en la Pi Zero
  - `MAX_CONTENT_LENGTH` 3 MB; 5000 líneas y 300 caracteres por línea

## Estructura interna de firmware/
```
firmware/
├── main.py
├── config.json
├── config_manager.py
├── modules/
│   ├── boton.py
│   ├── eink.py
│   ├── impresora.py
│   ├── audio.py
│   ├── salidas.py
│   ├── generador.py
│   ├── importador.py
│   └── portal.py
├── data/
│   ├── pluma.png
│   └── perfiles/<nombre>/{detonantes,protagonistas,conflictos}.txt
└── deploy/
    └── deploy.sh   # SSH+sshpass, sube por /tmp
```
