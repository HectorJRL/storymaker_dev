# Releases

Las imágenes distribuibles de StoryMaker (`storymaker-YYYY-MM-DD.img.xz`) **no se versionan en git**
porque son ficheros grandes (~1 GB). Se publican como **Release assets**.

## Dónde descargar la imagen

En la sección **Releases** del repositorio → versión `vYYYY-MM-DD` → fichero `storymaker-YYYY-MM-DD.img.xz`.

## Cómo generar una imagen nueva

Ver `firmware/deploy/crear_imagen.sh`. El fichero resultante se sube manualmente como asset de una
release; no se hace `git add` (está ignorado en `.gitignore`).
