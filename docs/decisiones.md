# Decisiones técnicas

- GPIO con `RPi.GPIO` + polling software (sin lgpio, sin gpiozero, sin edge detection)
- SPI fragmentado a 4000 bytes para evitar `OverflowError`
- `eink.py` usa secuencia de inicialización SSD1683 WeAct oficial (no Waveshare)
- Audio TTS: `edge-tts` genera MP3 → `mpg123` reproduce
- `config_manager.py` usa lock + escritura atómica para evitar corrupción JSON concurrente
- Animación e-ink: `pluma.png` pre-renderizada al arrancar; se muestra mientras genera
- Portal web: slider volumen con debounce 400ms; restart servicio via `subprocess.Popen` con `start_new_session=True`
- `journald`: Storage=auto (volátil) — no saturar SD en producción

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
│   └── portal.py
├── data/
│   ├── pluma.png
│   └── perfiles/<nombre>/{detonantes,protagonistas,conflictos}.txt
└── deploy/
    └── deploy.sh   # SSH+sshpass, sube por /tmp
```
