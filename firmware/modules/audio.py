"""
audio.py — Salida de audio TTS con edge-tts (Microsoft Neural).
I2S MAX98357A:
  GPIO18 -> BCLK
  GPIO19 -> LRC (LRCLK)
  GPIO21 -> DIN
edge-tts genera un .mp3 que se reproduce con mpg123 (plughw:0,0).
Requiere red. Sin red, cae a espeak-ng como fallback offline.
"""
import subprocess
import tempfile
import os
import shutil
import asyncio

VOZ_DEFAULT  = "es-ES-ElviraNeural"
MPG123_BIN   = "mpg123"
APLAY_DEVICE = "plug:dmixed"
EDGE_TTS_BIN = "/home/storymaker/proyecto/venv/bin/edge-tts"

class Audio:
    def __init__(self, config: dict):
        self.activada = config.get('activada', False)
        self.voz      = config.get('voz', VOZ_DEFAULT)
        self.volumen  = config.get('volumen', 90)
        self._mpg123_ok = shutil.which(MPG123_BIN) is not None
        self._espeak_ok = shutil.which('espeak-ng') is not None or shutil.which('espeak') is not None
        self._edge_ok   = os.path.isfile(EDGE_TTS_BIN)
        if self.activada:
            if self._edge_ok and self._mpg123_ok:
                print(f"[Audio] edge-tts listo. Voz: {self.voz}")
            elif self._espeak_ok:
                print("[Audio] Sin red o edge-tts no disponible, usando espeak como fallback.")
            else:
                print("[Audio] AVISO: ningun motor TTS disponible.")

    def hablar(self, texto: str):
        if not self.activada:
            return
        if self._edge_ok and self._mpg123_ok:
            try:
                asyncio.run(self._hablar_edge(texto))
                return
            except Exception as e:
                print(f"[Audio] edge-tts fallo ({e}), intentando espeak...")
        if self._espeak_ok:
            self._hablar_espeak(texto)
        else:
            print("[Audio] Sin motor TTS disponible.")

    async def _hablar_edge(self, texto: str):
        import edge_tts, json
        try:
            with open('/home/storymaker/proyecto/data/config.json') as _f:
                self.volumen = json.load(_f).get('hardware', {}).get('audio', {}).get('volumen', self.volumen)
        except Exception:
            pass
        tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmp.close()
        mp3_path = tmp.name
        try:
            comunicar = edge_tts.Communicate(texto, self.voz)
            await asyncio.wait_for(comunicar.save(mp3_path), timeout=15.0)
            subprocess.run(
                [MPG123_BIN, '-a', APLAY_DEVICE, '-f', str(int(self.volumen / 100 * 32768)), mp3_path],
                capture_output=True,
                check=True,
                timeout=60
            )
            print("[Audio] Reproduccion completada.")
        except Exception as e:
            raise e
        finally:
            if os.path.exists(mp3_path):
                os.unlink(mp3_path)

    def _hablar_espeak(self, texto: str):
        try:
            cmd = ['espeak-ng' if shutil.which('espeak-ng') else 'espeak',
                   '-v', 'es', '-s', '130', texto]
            subprocess.run(cmd, capture_output=True, timeout=30)
            print("[Audio] espeak completado.")
        except Exception as e:
            print(f"[Audio] espeak error: {e}")

    def esta_disponible(self) -> bool:
        return (self._edge_ok and self._mpg123_ok) or self._espeak_ok
