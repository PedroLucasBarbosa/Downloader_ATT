[app]
title = Baixador de Vídeos
package.name = baixadordevideos
package.domain = org.exemplo

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,pem

version = 1.0
icon.filename = %(source.dir)s/icon.png
# yt-dlp[default]: traz junto os scripts oficiais de resolução de
# desafio do YouTube (yt-dlp-ejs), além do yt-dlp em si.
# ffmpeg: necessário pra juntar vídeo e áudio quando vêm em arquivos
# separados (formatos DASH), tanto no YouTube quanto no Instagram.
requirements = python3,kivy,yt-dlp[default],certifi,ffmpeg

orientation = portrait
fullscreen = 0

# Binário estático do QuickJS (motor de JavaScript leve), empacotado
# como se fosse uma biblioteca nativa (.so) - é o único jeito de um
# programa "solto" ser executável dentro das restrições de segurança do
# Android. O yt-dlp usa ele pra resolver o desafio de JavaScript que o
# YouTube exige pra liberar os formatos de vídeo em qualidade alta.
android.add_libs_arm64_v8a = libs/arm64-v8a/*.so
android.add_libs_armeabi_v7a = libs/armeabi-v7a/*.so

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
# targetSdkVersion 28: mantém o modelo de storage "legado" (acesso direto a
# pastas públicas como Download/) em qualquer versão real do Android.
# A partir de API 29/30 o Android ignora WRITE_EXTERNAL_STORAGE para pastas
# públicas (scoped storage) e a escrita em Download/TikTok falha em silêncio.
# Isso é ótimo para instalar via APK direto; NÃO pode ser publicado assim na
# Play Store (que hoje exige targetSdkVersion mais alto) - se um dia for
# publicar lá, aí sim vale migrar para MediaStore.
android.api = 28
android.minapi = 24
android.ndk = 25b
p4a.branch = v2024.01.21
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
