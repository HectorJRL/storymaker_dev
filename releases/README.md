# Releases

Las imágenes distribuibles de StoryMaker (`storymaker-YYYY-MM-DD.img.xz`) **no se versionan en git**:
pesan alrededor de 1 GB. Se publican como **Release assets** en Codeberg. Sí se versiona el fichero
`.sha256` de cada una, que es diminuto y sirve para comprobar después que el adjunto publicado es el
que se generó aquí.

## Dónde descargar la imagen

Sección **Releases** del repositorio → versión `vYYYY-MM-DD` → fichero `storymaker-YYYY-MM-DD.img.xz`.

> El repositorio se replica a `github.com/HectorJRL/storymaker_dev`, pero **los push-mirrors de
> Codeberg copian refs de git, no adjuntos de release**. El tag llega al espejo; la imagen no. Si
> quieres la imagen respaldada en dos sitios, hay que subirla al espejo aparte.

## Credenciales de fábrica

| Credencial | De fábrica | Quién la cambia |
|---|---|---|
| PIN del portal web | `1234` | El usuario en el asistente de primer arranque (opcional) |
| Contraseña SSH de `storymaker` | `storymaker` | El usuario en el asistente de primer arranque (**obligatoria**) |

Son conocidas y públicas a propósito: el asistente no deja completar la configuración sin definir una
contraseña SSH propia, así que cada dispositivo acaba con la suya. Ver `docs/sistema.md`.

## Cómo publicar una release nueva

El orden importa. Lo que sigue es el proceso verificado el 2026-10-03.

### 1. Antes de tocar la imagen

```bash
git pull                                  # que no haya divergencia con el espejo
./deploy.sh <ip-de-la-pi>                 # el firmware debe ser el que vas a congelar
./deploy.sh --solo-firmware <ip-de-la-pi> # si sólo ha cambiado código Python
```

Desde v2026-10-03 las imágenes no traen el `NOPASSWD: ALL` de Raspberry Pi OS, así que instalar
ficheros de sistema pide la contraseña del dispositivo; ese paso usa `ssh -t` para que `sudo` tenga
terminal. Si sólo ha cambiado código Python —compruébalo con
`git diff --name-only <tag-de-la-imagen>..HEAD -- firmware/deploy/sistema/`— usa `--solo-firmware` y
te lo ahorras: reiniciar `historias.service` sí está en la lista corta de `/etc/sudoers.d`.

Prueba en el dispositivo lo que hayas cambiado. Una imagen se publica desde una Pi cuyo
comportamiento has visto funcionar, no desde una que asumes correcta.

### 2. Limpieza y captura

```bash
cd firmware/deploy
./crear_imagen.sh --local     # con la SD ya en el PC y la Pi apagada
./crear_imagen.sh <ip>        # o con la Pi encendida: limpia por SSH y la apaga
```

**Verifica la tarjeta antes de capturar.** Monta la raíz en sólo lectura y comprueba que no quedan
claves de host SSH, que `authorized_keys` y `.bash_history` están vacíos, que `010_pi-nopasswd` ha
desaparecido, que `storymaker-setpass` está instalado, que sólo queda el perfil de red del AP y que
`config.json` tiene `setup_completado: false`. Ese paso es el que detecta los fallos de limpieza; en
junio de 2026 no se hacía y la limpieza llevaba meses ejecutándose a medias sin que nadie lo notara.

En modo `--local` se ejecuta además `limpiar_montada.sh` en frío sobre la tarjeta, que **resetea los
interruptores de hardware a desactivado**. `limpiar_pi.sh` no lo hace. Esa divergencia es conocida.

> Tras la captura, la tarjeta se queda con el sistema de ficheros encogido al mínimo y **sin** el
> gancho de autoexpansión, que `pishrink` añade a la imagen y no a la tarjeta. Reflashea la SD con la
> imagen generada antes de volver a usar esa Pi.

### 3. Checksum y tag

```bash
mv storymaker-$(date +%F).img.xz releases/
cd releases && sha256sum storymaker-*.img.xz | tee storymaker-*.img.xz.sha256
git add releases/*.sha256 && git commit && git push
git tag -a vYYYY-MM-DD        # el SHA256 va en el mensaje del tag
git push origin vYYYY-MM-DD
```

### 4. Publicar

Con el CLI [`tea`](https://dl.gitea.com/tea/) autenticado (`tea login add --name codeberg --url
https://codeberg.org --token <TOKEN>`, permiso `write:repository`):

```bash
tea release create --login codeberg --repo Profektor/storymaker_dev \
    --tag vYYYY-MM-DD --title "StoryMaker vYYYY-MM-DD" --note "$(cat notas.md)"
tea releases assets create --login codeberg --repo Profektor/storymaker_dev \
    vYYYY-MM-DD releases/storymaker-*.img.xz releases/storymaker-*.img.xz.sha256
```

`tea` no imprime nada al crear una release. Comprueba el resultado:

```bash
tea api --login codeberg "repos/Profektor/storymaker_dev/releases"
```

### 5. Espejo

Los push-mirrors replican cada 8 horas. Para no esperar:

```bash
tea api --method POST --login codeberg "repos/Profektor/storymaker_dev/push_mirrors-sync"
```

Y confirma que ha llegado, en lugar de suponerlo:

```bash
curl -s https://api.github.com/repos/HectorJRL/storymaker_dev/commits/main | grep '"sha"'
```

Recuerda que el adjunto no se replica: si lo quieres también en GitHub, súbelo a mano en su pestaña
Releases o con un token propio.
