# Hardware — StoryMaker

## OS
Raspberry Pi OS Lite 64-bit Bookworm (estable)

## Pinout (BCM)
| Función | GPIO |
|---|---|
| Botón físico | 5 |
| LED estado | 23 |
| E-ink DC | 25 |
| E-ink RST | 17 |
| E-ink BUSY | 24 |
| E-ink SPI0 MOSI | 10 |
| E-ink SPI0 CLK | 11 |
| E-ink SPI0 CS0 | 8 |
| Impresora UART TX | 14 |
| Impresora UART RX | 15 |
| Audio I2S BCLK | 18 |
| Audio I2S LRCLK | 19 |
| Audio I2S DATA | 21 |

## Periféricos
- **E-ink:** WeAct 4.2" B&W (SSD1683) — refresco parcial NO soportado
- **Impresora:** QR701 UART térmica (ESC/POS, QR nativo GS(k) modelo 2)
- **Audio:** MAX98357A I2S — TTS edge-tts (es-ES-ElviraNeural) + mpg123
- **Fallback TTS offline:** espeak (voz local, entra cuando no hay red)

## LED (GPIO 23)
- Fijo encendido → sistema listo
- Parpadeo → feedback de pulsación
- Apagado → en proceso de shutdown
