# StoryMaker — Archivos de sistema

Estos archivos van fuera del directorio del proyecto porque requieren
permisos de root o pertenecen a servicios del sistema operativo.
Hay que aplicarlos manualmente en cada despliegue limpio.

## Archivos y destinos

| Archivo | Destino en la Pi | Descripción |
|---|---|---|
| `historias.service` | `/etc/systemd/system/` | Servicio principal: arranca el proyecto Python |
| `storymaker-wifi.service` | `/etc/systemd/system/` | Gestiona WiFi al arrancar (cliente o AP) |
| `storymaker-captive.service` | `/etc/systemd/system/` | Portal cautivo Flask en puerto 8080 |
| `storymaker-wifi.sh` | `/usr/local/bin/` | Script de gestión WiFi |
| `storymaker-captive.py` | `/usr/local/bin/` | Portal cautivo para configurar WiFi desde el AP |
| `storymaker-shutdown` | `/etc/sudoers.d/` | Permisos NOPASSWD para shutdown y restart del servicio |

## Orden de aplicación en una SD nueva

### 1. Sudoers
```bash
sudo cp storymaker-shutdown /etc/sudoers.d/
sudo chmod 440 /etc/sudoers.d/storymaker-shutdown
```

### 2. Scripts WiFi y portal cautivo
```bash
sudo cp storymaker-wifi.sh /usr/local/bin/
sudo cp storymaker-captive.py /usr/local/bin/
sudo chmod +x /usr/local/bin/storymaker-wifi.sh
sudo chmod +x /usr/local/bin/storymaker-captive.py
```

### 3. Servicios systemd
```bash
sudo cp historias.service          /etc/systemd/system/
sudo cp storymaker-wifi.service    /etc/systemd/system/
sudo cp storymaker-captive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable storymaker-wifi.service
sudo systemctl enable storymaker-captive.service
sudo systemctl enable historias.service
```

### 4. Reglas iptables (portal cautivo)

Estas reglas redirigen el tráfico HTTP del AP al portal cautivo para que
iOS, Android y Windows muestren la pantalla de configuración WiFi
automáticamente al conectarse.

```bash
# Redirigir HTTP (80) → portal cautivo (8080) solo en la interfaz AP
sudo iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j REDIRECT --to-port 8080

# Persistir las reglas para que sobrevivan reinicios
sudo apt-get install -y netfilter-persistent iptables-persistent
sudo netfilter-persistent save
```

> **Nota:** Sin estas reglas el portal cautivo escucha en :8080 pero los sistemas
> operativos hacen el chequeo de captive portal en el puerto 80 — sin la redirección
> nunca detectan que hay portal y no muestran la pantalla de configuración.

### 5. Configuración adicional del sistema

- **SPI habilitado**: `sudo raspi-config nonint do_spi 0`
- **I2S audio** (si se usa el MAX98357A): añadir `dtoverlay=hifiberry-dac` a `/boot/config.txt`
- **UART habilitado** (impresora): `sudo raspi-config nonint do_serial_hw 0` y deshabilitar login serial
- **NetworkManager**: sin `wifi.backend=nl80211` en `/etc/NetworkManager/conf.d/`
- **NetworkManager-wait-online deshabilitado**: `sudo systemctl disable NetworkManager-wait-online.service`
- **avahi-daemon**: para resolución mDNS → `storymaker.local:5000`
- **Usuario del sistema**: `storymaker` (uid 1000), dueño de `/home/storymaker/proyecto`
- **Perfil AP en NetworkManager**: crear la conexión `StoryMaker-Setup` como hotspot abierto en 10.42.0.1

## Red WiFi — modo de operación

| Situación | Comportamiento | Acceso |
|---|---|---|
| WiFi conocida en alcance | Conecta como cliente | `http://storymaker.local:5000` |
| Sin red conocida | Levanta AP `StoryMaker-Setup` | Conectar al AP → captive portal en `:8080` |

### QR en modo AP
El QR impreso y en pantalla apunta a `http://10.42.0.1:8080` (portal cautivo).
Desde ahí se selecciona la red WiFi y se introduce la contraseña.
Una vez conectado, el dispositivo recuerda la red para futuros arranques.
