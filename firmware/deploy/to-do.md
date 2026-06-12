# TO-DO LIST en el firmware

## Pendiente
- Comprobar si Claude-code puede recrear el firmware para trixie.
- Incluir ip en pantalla bienvenida (e-ink y portal).
- **[e-ink]** Ajustar renderizado de texto para premisas largas: texto se sale de la pantalla. Revisar cálculo de tamaño de fuente dinámico y wrap en `modules/eink.py`.
- Añadir audio de bienvenida y despedida.

## Hecho
- Wizard de primer arranque: portal cautivo muestra paso 2 tras conectar WiFi, con URL y pin inicial.
- Login portal: aviso de PIN inicial (1234) cuando `setup_completado=false`.
- Fix: modelo e-ink SSD1619 → SSD1683 en página de setup.
- Scripts de imagen distributable: `limpiar_pi.sh` + `crear_imagen.sh`.

## Flujo de actualización / imagen
1. Modificar código en rama dev → commit → push a Codeberg (repo dev).
2. Deploy en Pi de prueba: `./deploy.sh <ip>` y verificar.
3. Cuando todo OK: `./crear_imagen.sh <ip>` → genera `storymaker-YYYY-MM-DD.img.xz`.
4. Subir imagen a Codeberg Releases del repo público (release vYYYY-MM-DD).
