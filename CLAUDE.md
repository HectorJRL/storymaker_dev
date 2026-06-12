# StoryMaker

Dispositivo educativo (Raspberry Pi Zero 2W) para talleres literarios.
Genera premisas combinando detonantes+protagonistas+conflictos desde perfiles .txt.
Salidas: e-ink, impresora térmica, audio TTS.

## Reglas
- Usuario sistema: `storymaker` (uid 1000). Proyecto en `/home/storymaker/proyecto`
- GPIO: `RPi.GPIO` + polling software (NUNCA lgpio/gpiozero/edge detection)
- SPI fragmentado a 4000 bytes (evita OverflowError)
- E-ink: secuencia SSD1683 WeAct oficial (NO Waveshare SSD1619)
- Patches quirúrgicos vía script Python, no reescrituras completas de fichero

## Estructura
Repo Codeberg = proyecto completo (código, STL, esquemas, manuales).
`firmware/` = software que se despliega en la SD (módulos en `firmware/modules/`).

## Referencia detallada (leer solo si la tarea lo requiere)
- `docs/hardware.md` — pinout completo, periféricos, audio/TTS
- `docs/sistema.md` — configs fuera del repo (sudoers, systemd, WiFi, NM)
- `docs/decisiones.md` — decisiones técnicas y por qué
- `docs/deuda-tecnica.md` — pendientes conocidos
- `docs/opus-review.md` — última auditoría de robustez (si existe)
