# Deuda técnica conocida

- **Codeberg arrastra ~976 MB de un blob huérfano.** La imagen
  `storymaker-2026-06-23.img.xz` se subió en su día dentro del repo; al reescribir
  la historia para quitarla, el objeto quedó allí sin ninguna referencia que lo
  apunte (`git ls-remote` sólo devuelve `main`). Los objetos inalcanzables no se
  envían al clonar, así que no afecta a quien clone, pero ocupa disco en Codeberg
  y cuenta para su cuota. Sólo lo puede eliminar el `git gc` del servidor, que no
  es accesible por API: hay que pedirlo en `codeberg.org/Codeberg/Community`. El
  espejo de GitHub se libró (0,4 MB).
- **Divergencia entre los dos scripts de limpieza.** `limpiar_montada.sh` resetea
  los interruptores de hardware a desactivado y `limpiar_pi.sh` no. Como
  `crear_imagen.sh --local` ejecuta el primero, el resultado depende del modo de
  captura. Decidido el 2026-10-03 dejarlo así, pero conviene unificarlo.
- Eleven Labs como opción TTS premium (no implementado)
- **Sin internet, cada frase pierde 15 s esperando a edge-tts.** `audio.py`
  decide el motor con `self._edge_ok = os.path.isfile(EDGE_TTS_BIN)`, que sólo
  mira si existe el binario: nunca comprueba la red, pese a que el mensaje de
  arranque diga «Sin red o edge-tts no disponible». Resultado: en una zona sin
  internet, `hablar()` intenta edge-tts en cada premisa y agota el
  `asyncio.wait_for(..., timeout=15.0)` antes de caer a `espeak-ng`. Funciona,
  pero con 15 s de silencio por frase el dispositivo parece averiado.
  Dos arreglos que se complementan: usar `netinfo.get_wifi_mode()` —ya existe y
  main.py lo usa para la bienvenida— para descartar edge-tts cuando no hay ruta;
  y recordar el fallo unos minutos, de modo que tras el primer timeout las frases
  siguientes vayan directas a espeak en lugar de reintentar cada vez.
  Relevante para talleres en sitios sin cobertura, que es un escenario de uso
  previsto.
- **Permitir contraseñas SSH de 6 caracteres.** Pedido tras probar el primer
  arranque de v2026-10-03: el mínimo de 8 resulta incómodo de teclear en el
  asistente. Hay que cambiarlo en dos sitios, porque el ayudante revalida por ser
  la frontera de privilegio: `MIN_PASS_SSH` en `portal.py` y `MIN_LONGITUD` en
  `deploy/sistema/storymaker-setpass`.
  Contrapartida que conviene no perder de vista: bajar a 6 debilita justo lo que
  se endureció en esa versión, y el ataque realista no es offline sino fuerza
  bruta por SSH desde la propia red. Con 6 caracteres eso pasa a ser viable para
  alguien con paciencia. Lo sensato es acompañarlo de limitación de intentos
  —`MaxAuthTries` en `sshd_config` y/o `fail2ban`— y entonces 6 caracteres son
  defendibles. Implementar sólo la rebaja, sin el freno, deja el dispositivo peor
  de como estaba.
- **Contraseña SSH en claro sobre el AP de configuración.** El asistente de
  primer arranque pide la contraseña por HTTP y, cuando no hay red conocida, eso
  ocurre sobre el AP abierto `StoryMaker-Setup`. Alternativa valorada y no
  implementada: generar una contraseña fuerte en el dispositivo y mostrarla en la
  e-ink o imprimirla, de modo que no cruce ninguna red. Mitigación actual: la
  ventana es un único primer arranque, y si se configura ya conectado a una red
  WPA2 el problema desaparece.
- **La imagen podría salir con la contraseña bloqueada en vez de con una de
  fábrica.** `passwd -l storymaker` dejaría la imagen sin ninguna credencial SSH
  utilizable hasta que el asistente fije una, lo que elimina del todo la ventana
  anterior. No se hizo porque obliga a encadenar bloqueo y apagado en la misma
  sesión SSH durante la captura, y un fallo a medias deja la Pi de desarrollo sin
  acceso. Revisable cuando el proceso de imagen esté más automatizado.
- **El importador deja tres `.txt.bak` de 0 bytes al crear un perfil nuevo.**
  `crear_perfil` escribe los `.txt` vacíos y `aplicar()` los respalda antes de
  poblarlos. Es inocuo y hace que «Deshacer» devuelva el perfil a recién creado,
  pero ensucia la carpeta. Los scripts de limpieza los borran, así que no viajan
  en la imagen.
- `journald Storage=volatile` configurado en `setup_sd.sh` (paso 2) — solo afecta a installs nuevas; la Pi de desarrollo existente sigue en `persistent` hasta nuevo deploy
