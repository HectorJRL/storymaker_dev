"""
netinfo.py — Info de red para mostrar en e-ink o log al arrancar.
"""
import subprocess
import socket


def get_ip():
    try:
        result = subprocess.run(
            ['hostname', '-I'], capture_output=True, text=True, timeout=3
        )
        ips = result.stdout.strip().split()
        return ips[0] if ips else None
    except Exception:
        return None


def get_wifi_mode():
    """Devuelve 'ap', 'client' o 'none'."""
    try:
        result = subprocess.run(
            ['nmcli', '-t', '-f', 'STATE', 'general'],
            capture_output=True, text=True, timeout=3
        )
        if 'connected' in result.stdout:
            # Comprobar si es AP
            ap_result = subprocess.run(
                ['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'],
                capture_output=True, text=True, timeout=3
            )
            if 'StoryMaker-Setup' in ap_result.stdout:
                return 'ap'
            return 'client'
    except Exception:
        pass
    return 'none'


def get_ssid():
    try:
        result = subprocess.run(
            ['nmcli', '-t', '-f', 'ACTIVE,SSID', 'device', 'wifi'],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if line.startswith('yes:'):
                return line.split(':', 1)[1]
    except Exception:
        pass
    return None
