# StoryMaker — Archivos de sistema

Estos archivos van fuera del directorio del proyecto porque requieren
permisos de root o pertenecen a servicios del sistema operativo.
Hay que aplicarlos manualmente en cada despliegue limpio.

## Archivos y destinos

| Archivo | Destino en la Pi | Descripción |
|---|---|---|
| `historias.service` | `/etc/systemd/system/` | Servicio systemd que arranca el proyecto |
| `storymaker-wifi.sh` | `/usr/local/bin/` | Gestión WiFi: cliente o AP según disponibilidad |
| `storymaker-captive.py` | `/usr/local/bin/` | Portal cautivo Flask (puerto 8080) para configurar WiFi |
| `storymaker-shutdown` | `/etc/sudoers.d/` | Permisos NOPASSWD para shutdown y restart del servicio |

## Orden de aplicación

### 1. Sudoers
```bash
sudo cp storymaker-shutdown /etc/sudoers.d/
sudo chmod 440 /etc/sudoers.d/storymaker-shutdown
```

### 2. Scripts WiFi
```bash
sudo cp storymaker-wifi.sh /usr/local/bin/
sudo cp storymaker-captive.py /usr/local/bin/
sudo chmod +x /usr/local/bin/storymaker-wifi.sh
sudo chmod +x /usr/local/bin/storymaker-captive.py
```

### 3. Servicio systemd
```bash
sudo cp historias.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable historias.service
sudo systemctl start historias.service
```

## Configuración adicional del sistema (no en archivos)

Estas configuraciones hay que aplicarlas a mano en una instalación limpia:

- **SPI habilitado**: `sudo raspi-config nonint do_spi 0`
- **NetworkManager**: sin `wifi.backend=nl80211` en `/etc/NetworkManager/conf.d/`
- **NetworkManager-wait-online deshabilitado**: `sudo systemctl disable NetworkManager-wait-online.service`
- **netfilter-persistent**: para persistir las reglas iptables del portal cautivo
- **avahi-daemon**: para resolución mDNS → `storymaker.local`
- **Usuario del sistema**: `storymaker` (uid 1000), dueño de `/home/storymaker/proyecto`

## Red WiFi

- Con red conocida: conecta como cliente, accesible en `storymaker.local:5000`
- Sin red conocida: levanta AP abierto `StoryMaker-Setup` (10.42.0.1), portal cautivo en puerto 8080