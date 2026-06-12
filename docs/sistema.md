# Configuraciones del sistema (fuera del repo)

Todo lo que `setup_sd.sh` instala automáticamente. Esta doc es referencia, no pasos manuales.

## Archivos instalados por setup_sd.sh

| Archivo en repo | Destino en Pi | Descripción |
|---|---|---|
| `deploy/sistema/historias.service` | `/etc/systemd/system/` | Servicio principal Python |
| `deploy/sistema/storymaker-wifi.service` | `/etc/systemd/system/` | Gestiona WiFi al arrancar |
| `deploy/sistema/storymaker-captive.service` | `/etc/systemd/system/` | Portal cautivo (puerto 8080) |
| `deploy/sistema/storymaker-wifi.sh` | `/usr/local/bin/` | Script gestión WiFi (cliente/AP) |
| `deploy/sistema/storymaker-captive.py` | `/usr/local/bin/` | Portal cautivo Flask |
| `deploy/sistema/storymaker-shutdown` | `/etc/sudoers.d/` | NOPASSWD: shutdown + restart servicio |

## Red / WiFi

- NetworkManager gestiona wlan0
- mDNS via avahi → `storymaker.local:5000`
- Sin red conocida → AP "StoryMaker-Setup" (abierto, 10.42.0.1)
- Portal cautivo Flask en puerto 8080; iptables redirige 80→8080
- Script: `/usr/local/bin/storymaker-wifi.sh`

## Servicios habilitados

```
historias.service          # arranca con el sistema
storymaker-wifi.service    # antes de historias
storymaker-captive.service # siempre activo (solo responde en modo AP)
avahi-daemon               # mDNS → storymaker.local
NetworkManager-wait-online # DESHABILITADO (arranque más rápido)
```

## Otros ajustes configurados

- SPI habilitado (`dtparam=spi=on` en `config.txt`)
- UART estable para impresora (`enable_uart=1` + `dtoverlay=disable-bt`)
- I2S audio (`dtoverlay=hifiberry-dac`)
- Consola serie eliminada de cmdline.txt (UART libre para impresora)
- `storymaker` en grupos: spi, gpio, dialout, audio
- `/etc/asound.conf` con `dmix` para MAX98357A (evita chasquido entre premisas)
- Perfil AP en NetworkManager: "StoryMaker-Setup", 10.42.0.1, modo infrastructure/ap
- iptables: `PREROUTING -i wlan0 -p tcp --dport 80 → :8080` (captive portal)

---

## Flujo de deploy completo (SD nueva desde cero)

### Paso 1 — Flashear SD

Flashear con **Raspberry Pi Imager**:
- Modelo: Raspberry Pi Zero 2W
- SO: Raspberry Pi OS Lite (64-bit, Bookworm)
- **No personalizar** (Bookworm en Imager trata la imagen como Debian genérico y bloquea la personalización)

### Paso 2 — Preparar SD desde el PC

Con la SD en el lector conectado al PC:

```bash
# Identificar dispositivo
lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -v loop

# Configurar: escribe usuario, hostname, SSH y WiFi directamente en la SD
sudo firmware/deploy/prepare_sd.sh /dev/sdX "NombreWiFi" "ContraseñaWiFi"
```

`prepare_sd.sh` crea: `boot/ssh`, `boot/userconf.txt` (usuario storymaker), `/etc/hostname`, perfil NM en `/etc/NetworkManager/system-connections/`.

### Paso 3 — Primer arranque

Insertar SD en Pi Zero 2W y encender. La Pi conecta sola a la WiFi configurada.

Conectar por SSH (~60 s después de encender):
```bash
ssh storymaker@storymaker.local
# o por IP si mDNS no responde:
# ssh storymaker@<ip-del-router>
```

### Paso 4 — Setup automático

```bash
cd firmware/deploy
./setup_sd.sh <ip-de-la-pi>
```

Instala paquetes, habilita hardware, servicios, venv Python, despliega firmware. Reinicia la Pi al final.

### Paso 5 — Verificar

Tras el reboot (~30 s):
```bash
# Portal de control
http://storymaker.local:5000   # → login (PIN: 1234) → wizard hardware
```

---

## Flujo de actualización (deploy incremental)

Solo actualiza código Python, conserva `config.json` y `data/perfiles/`:

```bash
cd firmware/deploy
./deploy.sh <ip-de-la-pi>
```

---

## Flujo de imagen distributable

Para crear una imagen `.img.xz` lista para distribuir en Codeberg Releases:

```bash
# Prerequisito: pishrink.sh en PATH del host
# wget https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh
# chmod +x pishrink.sh && sudo mv pishrink.sh /usr/local/bin/

cd firmware/deploy
./crear_imagen.sh <ip-de-la-pi>
```

Limpia la Pi (WiFi, config, claves SSH, logs), apaga, captura con `dd`, reduce con `pishrink`, comprime con `xz`. Deja `storymaker-YYYY-MM-DD.img.xz` en la raíz del proyecto.

---

## Flujo de primer arranque desde imagen distributable

El usuario final (sin conocimientos técnicos) hace:

1. Descargar `storymaker-YYYY-MM-DD.img.xz` de Codeberg Releases
2. Abrirlo con Raspberry Pi Imager → "Usar imagen personalizada" → flashear
3. Insertar SD en Pi y encender
4. Conectar su móvil/portátil al AP **"StoryMaker-Setup"** (WiFi sin contraseña)
5. El navegador abre solo el portal cautivo (puerto 8080) → seleccionar red WiFi → conectar
6. La pantalla de éxito muestra la URL del paso 2: `http://storymaker.local:5000`
7. Reconectar el móvil a la WiFi habitual → abrir esa URL
8. Login con PIN **1234** (hay un aviso en pantalla) → wizard de hardware → listo
