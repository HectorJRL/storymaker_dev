# Configuraciones del sistema (fuera del repo)

Aplicar manualmente en cada SD nueva:

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
