"""
Downloader de Vídeos - App Android (Kivy)
------------------------------------------
Cole o link (TikTok, YouTube ou Instagram), toque em Baixar, o vídeo vai
para a pasta Download/<Plataforma> do celular.

IMPORTANTE: use isso apenas para baixar vídeos seus ou que você tem
permissão de baixar. Baixar conteúdo de terceiros sem autorização pode
violar os Termos de Uso das plataformas e a lei de direitos autorais.
"""

import json
import os
import re
import shutil
import ssl
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request

from kivy.logger import Logger

import certifi
# Contexto SSL explícito usando o bundle de certificados do certifi.
# Não usamos variável de ambiente (SSL_CERT_FILE) porque o
# python-for-android já define essa variável sozinho, apontando pra um
# caminho que só existe na máquina onde o app foi compilado - no celular
# esse caminho não existe, e como a variável já "existia", um
# os.environ.setdefault(...) nunca tinha efeito. Um contexto explícito,
# passado direto em cada requisição, não depende disso.
CONTEXTO_SSL = ssl.create_default_context(cafile=certifi.where())

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.lang import Builder
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.clock import Clock

try:
    from android.permissions import request_permissions, Permission
    from android.storage import primary_external_storage_path
    NO_ANDROID = False
except ImportError:
    NO_ANDROID = True


# ---------- Paleta de cores ----------
COR_FUNDO = (0.94, 0.95, 0.97, 1)
COR_CARD = (1, 1, 1, 1)
COR_BORDA = (0.88, 0.90, 0.93, 1)
COR_TEXTO = (0.10, 0.12, 0.16, 1)
COR_TEXTO_MUTED = (0.45, 0.48, 0.53, 1)
COR_ACCENT = (0.20, 0.47, 0.94, 1)
COR_ACCENT_PRESSED = (0.14, 0.36, 0.78, 1)
COR_SUCESSO_BG = (0.88, 0.97, 0.90, 1)
COR_SUCESSO_TXT = (0.11, 0.52, 0.28, 1)
COR_ERRO_BG = (1.0, 0.92, 0.92, 1)
COR_ERRO_TXT = (0.72, 0.15, 0.15, 1)
COR_INFO_BG = (0.90, 0.94, 1.0, 1)
COR_INFO_TXT = (0.16, 0.38, 0.75, 1)

Window.clearcolor = COR_FUNDO


KV = """
<CartaoBase>:
    canvas.before:
        Color:
            rgba: root.cor_fundo
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [18]
        Color:
            rgba: root.cor_borda
        Line:
            rounded_rectangle: [self.x, self.y, self.width, self.height, 18]
            width: 1
"""
Builder.load_string(KV)


class CartaoBase(BoxLayout):
    cor_fundo = ListProperty(COR_CARD)
    cor_borda = ListProperty(COR_BORDA)


class BotaoPrimario(Button):
    """Botão grande, arredondado, com cor sólida e feedback ao toque."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.font_size = "19sp"
        self.bold = True
        self.size_hint_y = None
        self.height = "58dp"
        with self.canvas.before:
            self._cor = Color(*COR_ACCENT)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[16])
        self.bind(pos=self._atualizar, size=self._atualizar, state=self._atualizar_estado)

    def _atualizar(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _atualizar_estado(self, *args):
        if self.state == "down":
            self._cor.rgba = COR_ACCENT_PRESSED
        else:
            self._cor.rgba = COR_ACCENT


class BotaoAba(Button):
    """Botão de aba (TikTok / YouTube / Instagram) com estado ativo/inativo."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.font_size = "14sp"
        self.bold = True
        self.size_hint_y = None
        self.height = "44dp"
        self.ativo = False
        with self.canvas.before:
            self._cor = Color(*COR_CARD)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[12])
        self.bind(pos=self._atualizar, size=self._atualizar)
        self._aplicar_estilo()

    def _atualizar(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def definir_ativo(self, ativo):
        self.ativo = ativo
        self._aplicar_estilo()

    def _aplicar_estilo(self):
        if self.ativo:
            self._cor.rgba = COR_ACCENT
            self.color = (1, 1, 1, 1)
        else:
            self._cor.rgba = COR_CARD
            self.color = COR_TEXTO_MUTED


class CampoArredondado(BoxLayout):
    """Container com fundo branco arredondado, envolvendo o TextInput real."""

    def __init__(self, hint_text="Cole aqui o link...", **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = "54dp"
        self.spacing = 6
        self.padding = (4, 4)
        with self.canvas.before:
            Color(*COR_CARD)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
            Color(*COR_BORDA)
            self._linha = Line(rounded_rectangle=[self.x, self.y, self.width, self.height, 14], width=1.2)
        self.bind(pos=self._atualizar, size=self._atualizar)

        self.campo = TextInput(
            hint_text=hint_text,
            multiline=False,
            background_normal="",
            background_active="",
            background_color=(0, 0, 0, 0),
            foreground_color=COR_TEXTO,
            hint_text_color=COR_TEXTO_MUTED,
            cursor_color=COR_ACCENT,
            font_size="16sp",
            padding=(16, 14, 16, 14),
            use_bubble=True,
            use_handles=True,
        )
        self.add_widget(self.campo)

        self.botao_colar = Button(
            text="Colar",
            font_size="13sp",
            bold=True,
            size_hint_x=None,
            width="64dp",
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=COR_ACCENT,
        )
        self.botao_colar.bind(on_press=self._colar)
        self.add_widget(self.botao_colar)

    def _colar(self, *args):
        from kivy.core.clipboard import Clipboard
        texto = Clipboard.paste()
        if texto:
            self.campo.text = texto.strip()

    def _atualizar(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._linha.rounded_rectangle = [self.x, self.y, self.width, self.height, 14]

    @property
    def text(self):
        return self.campo.text

    @text.setter
    def text(self, value):
        self.campo.text = value


class CaixaStatus(CartaoBase):
    """Cartão de status (info / sucesso / erro) que muda de cor conforme o estado."""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("padding", (16, 14))
        kwargs.setdefault("spacing", 10)
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self.height = "0dp"
        self.opacity = 0
        self.texto = Label(
            text="",
            font_size="14sp",
            color=COR_TEXTO,
            halign="left",
            valign="middle",
        )
        self.texto.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
        self.add_widget(self.texto)

    def definir(self, tipo, mensagem):
        if not mensagem:
            self.height = "0dp"
            self.opacity = 0
            return

        estilos = {
            "info": (COR_INFO_BG, COR_INFO_TXT),
            "sucesso": (COR_SUCESSO_BG, COR_SUCESSO_TXT),
            "erro": (COR_ERRO_BG, COR_ERRO_TXT),
        }
        cor_bg, cor_txt = estilos.get(tipo, estilos["info"])
        self.cor_fundo = cor_bg
        self.cor_borda = cor_bg
        self.texto.text = mensagem
        self.texto.color = cor_txt
        self.opacity = 1
        # altura estimada conforme o tamanho do texto (folga extra)
        linhas = max(1, len(mensagem) // 32 + 1)
        self.height = f"{30 + linhas * 22}dp"


_CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
    ),
}


def abrir_no_navegador(url):
    """Abre uma URL no navegador do sistema. No Android usa uma Intent
    nativa (via pyjnius, que já vem com o Kivy) - é o jeito confiável de
    abrir o navegador padrão do usuário a partir de um app Kivy."""
    if NO_ANDROID:
        import webbrowser
        webbrowser.open(url)
        return
    from jnius import autoclass, cast

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
    atividade_atual = cast("android.app.Activity", PythonActivity.mActivity)
    atividade_atual.startActivity(intent)


def montar_url_site_externo(url, subpasta):
    """Monta o link pra abrir num site de download já existente (a
    exemplo do SnapInsta/SaveFrom), que resolve o vídeo do lado do
    servidor deles - o mesmo princípio do tikwm.com que já usamos pro
    TikTok, só que fora do app em vez de dentro dele."""
    if subpasta == "YouTube":
        return url.replace("youtube.com", "ssyoutube.com").replace("youtu.be", "ssyoutu.be")
    if subpasta == "Instagram":
        return "https://snapinsta.app/en?url=" + urllib.parse.quote(url, safe="")
    return "https://en.savefrom.net/359/#url=" + urllib.parse.quote(url, safe="")


def caminho_sessao_instagram():
    """Caminho do arquivo onde guardamos os cookies da sessão do
    Instagram depois do login, dentro da pasta privada do próprio app
    (não é acessível por outros apps)."""
    try:
        app = App.get_running_app()
        base = app.user_data_dir if app else os.path.expanduser("~")
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, ".instagram_sessao.txt")


def salvar_sessao_instagram(cookie_string):
    try:
        with open(caminho_sessao_instagram(), "w", encoding="utf-8") as f:
            f.write(cookie_string)
        Logger.info(f"InstagramLogin: sessão salva ({len(cookie_string)} chars) em {caminho_sessao_instagram()}")
    except Exception as e:
        Logger.error(f"InstagramLogin: falha ao salvar sessão: {e}")


def carregar_sessao_instagram():
    caminho = caminho_sessao_instagram()
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read().strip() or None
        Logger.info(
            f"InstagramLogin: sessão carregada de {caminho} "
            f"({'nenhuma' if not conteudo else str(len(conteudo)) + ' chars'})"
        )
        return conteudo
    except Exception as e:
        Logger.info(f"InstagramLogin: nenhuma sessão salva encontrada em {caminho} ({type(e).__name__})")
        return None


def apagar_sessao_instagram():
    try:
        os.remove(caminho_sessao_instagram())
    except Exception:
        pass
    if not NO_ANDROID:
        try:
            from jnius import autoclass
            CookieManager = autoclass("android.webkit.CookieManager")
            CookieManager.getInstance().removeAllCookies(None)
        except Exception as e:
            Logger.error(f"InstagramLogin: falha ao limpar cookies do WebView: {e}")


def abrir_login_instagram(ao_detectar_login, ao_cancelar):
    """Abre uma WebView nativa do Android, em tela cheia, com a página
    OFICIAL de login do Instagram. O usuário digita usuário/senha
    normalmente ali dentro (o app não vê nem guarda a senha em momento
    nenhum) - só ficamos de olho nos cookies que o navegador do sistema
    recebe depois que o login é aceito, pra reaproveitar essa sessão nas
    próximas buscas."""
    if NO_ANDROID:
        ao_cancelar("Login por WebView só funciona no app Android instalado no celular.")
        return

    from jnius import autoclass, cast
    from android.runnable import run_on_ui_thread

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    AndroidWebView = autoclass("android.webkit.WebView")
    WebViewClient = autoclass("android.webkit.WebViewClient")
    CookieManager = autoclass("android.webkit.CookieManager")
    LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")

    atividade = PythonActivity.mActivity
    estado = {"webview": None, "fechado": False}

    def _remover_webview(*args):
        if estado["fechado"]:
            return
        estado["fechado"] = True

        @run_on_ui_thread
        def _remover():
            try:
                decor = cast("android.view.ViewGroup", atividade.getWindow().getDecorView())
                content = cast(
                    "android.view.ViewGroup",
                    decor.findViewById(autoclass("android.R$id").content),
                )
                content.removeView(estado["webview"])
            except Exception as e:
                Logger.error(f"InstagramLogin: falha ao remover webview: {e}")

        _remover()

    def _verificar_login(dt):
        try:
            cookie_string = CookieManager.getInstance().getCookie("https://www.instagram.com")
        except Exception as e:
            Logger.error(f"InstagramLogin: falha ao ler cookies: {e}")
            return
        tem_ds_user_id = bool(cookie_string) and "ds_user_id=" in cookie_string
        estado["ticks"] = estado.get("ticks", 0) + 1
        if estado["ticks"] % 4 == 1:  # loga a cada ~6s, pra não spammar o log
            Logger.info(
                f"InstagramLogin: checagem #{estado['ticks']} - "
                f"cookie presente: {bool(cookie_string)}, "
                f"tamanho: {len(cookie_string) if cookie_string else 0}, "
                f"ds_user_id encontrado: {tem_ds_user_id}"
            )
        if tem_ds_user_id:
            Logger.info("InstagramLogin: login detectado! Fechando a janela e salvando a sessão.")
            Clock.unschedule(_verificar_login)
            _remover_webview()
            ao_detectar_login(cookie_string)

    @run_on_ui_thread
    def _abrir():
        CookieManager.getInstance().setAcceptCookie(True)
        webview = AndroidWebView(atividade)
        estado["webview"] = webview
        webview.getSettings().setJavaScriptEnabled(True)
        webview.getSettings().setDomStorageEnabled(True)
        webview.setWebViewClient(WebViewClient())
        atividade.addContentView(
            webview, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
        )
        webview.loadUrl("https://www.instagram.com/accounts/login/")

    Logger.info("InstagramLogin: abrindo a janela de login...")
    _abrir()
    Clock.schedule_interval(_verificar_login, 1.5)


def pasta_destino(subpasta):
    if NO_ANDROID:
        return os.path.join(os.path.expanduser("~"), f"{subpasta}Downloads")
    base = primary_external_storage_path()
    return os.path.join(base, "Download", subpasta)


def notificar_galeria(caminho):
    """Avisa o Android que um arquivo de mídia novo apareceu, pra ele
    entrar no índice do MediaStore mais rápido. Isso é só um "bônus" -
    se falhar, não afeta o download em si (por isso sempre roda depois
    do arquivo já estar salvo, e qualquer erro aqui só vai pro log)."""
    if NO_ANDROID:
        return
    try:
        from jnius import autoclass

        MediaScannerConnection = autoclass("android.media.MediaScannerConnection")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        MediaScannerConnection.scanFile(PythonActivity.mActivity, [caminho], None, None)
    except Exception as e:
        Logger.error(f"Galeria: falha ao notificar novo arquivo ({caminho}): {e}")


# ---------------------------------------------------------------------------
# Resolvedores: cada um recebe a URL colada pelo usuário e devolve
# (video_url, nome_do_arquivo_sem_extensao). Quem baixa de fato o arquivo é
# sempre o mesmo código genérico em PainelDownload._baixar.
# ---------------------------------------------------------------------------

def resolver_tiktok(url):
    """Consulta a API pública do tikwm.com, que devolve um link direto
    (sem marca d'água) para o vídeo do TikTok."""
    api_url = "https://www.tikwm.com/api/?" + urllib.parse.urlencode({"url": url, "hd": 1})
    req = urllib.request.Request(api_url, headers=_CABECALHOS)
    with urllib.request.urlopen(req, timeout=15, context=CONTEXTO_SSL) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if payload.get("code") != 0:
        raise RuntimeError(f"API recusou o link: {payload.get('msg')}")

    dados = payload.get("data") or {}
    video_url = dados.get("hdplay") or dados.get("play") or dados.get("wmplay")
    if not video_url:
        raise RuntimeError("A API não retornou um link de vídeo utilizável")

    video_id = str(dados.get("id") or int(time.time()))
    return video_url, video_id


class _LoggerSilenciosoYtDlp:
    """Logger próprio pro yt-dlp. Sem isso, em alguns ambientes Android o
    yt-dlp tenta escrever erros direto no stderr padrão e quebra com
    'str' object has no attribute 'write', mascarando o erro real."""

    def debug(self, msg):
        pass

    def warning(self, msg):
        Logger.warning(f"yt-dlp: {msg}")

    def error(self, msg):
        Logger.error(f"yt-dlp: {msg}")


def _baixar_e_juntar_com_ytdlp(url, opcoes_extra, prefixo_log):
    """Fallback pra quando só existem formatos separados de vídeo e
    áudio: pede pro próprio yt-dlp baixar os dois e juntar com o ffmpeg
    (se ele existir no dispositivo). Devolve o caminho do arquivo já
    pronto no disco."""
    import yt_dlp

    pasta_temp = tempfile.mkdtemp(prefix="ytdlp_merge_")
    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "logger": _LoggerSilenciosoYtDlp(),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(pasta_temp, "%(id)s.%(ext)s"),
    }
    opcoes.update(opcoes_extra)

    Logger.info(f"{prefixo_log}: nenhum formato pronto - tentando baixar e juntar com ffmpeg")
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)
        caminho = ydl.prepare_filename(info)

    caminho_mp4 = os.path.splitext(caminho)[0] + ".mp4"
    if os.path.exists(caminho_mp4):
        caminho = caminho_mp4
    if not os.path.exists(caminho):
        raise RuntimeError("yt-dlp disse que baixou, mas o arquivo final não apareceu")

    video_id = re.sub(r"[^A-Za-z0-9_-]", "", info.get("id") or str(int(time.time())))
    Logger.info(f"{prefixo_log}: baixado e juntado com sucesso em {caminho}")
    return caminho, video_id


def _localizar_qjs():
    """Acha o caminho do binário QuickJS que empacotamos como se fosse
    uma biblioteca nativa (libqjs.so) - esse é o motor de JavaScript que
    o yt-dlp usa pra resolver o desafio do YouTube. Devolve None se não
    achar (ex: rodando fora do Android, ou binário não empacotado)."""
    if NO_ANDROID:
        return None
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        native_lib_dir = PythonActivity.mActivity.getApplicationInfo().nativeLibraryDir
        caminho = os.path.join(native_lib_dir, "libqjs.so")
        if os.path.exists(caminho):
            return caminho
        Logger.warning(f"QuickJS: libqjs.so não encontrado em {native_lib_dir}")
    except Exception as e:
        Logger.error(f"QuickJS: falha ao localizar o binário: {e}")
    return None


def resolver_youtube(url):
    """Usa yt-dlp pedindo os formatos de vários "perfis de cliente" do
    YouTube (android, ios, tv, web) NUMA SÓ consulta, combinando tudo -
    assim o yt-dlp escolhe a melhor qualidade disponível entre todos os
    perfis, em vez de parar no primeiro perfil que responder (que pode
    só ter qualidades baixas). Prioriza até 1080p com ffmpeg pra juntar
    vídeo e áudio; só cai pro formato "pronto" de qualidade menor se
    isso falhar."""
    import yt_dlp

    perfis = ["android", "ios", "tv", "web_safari", "web"]
    opcoes_extractor = {"extractor_args": {"youtube": {"player_client": perfis}}}

    caminho_qjs = _localizar_qjs()
    if caminho_qjs:
        opcoes_extractor["js_runtimes"] = [f"quickjs:{caminho_qjs}"]
        Logger.info(f"YouTubeDownload: usando QuickJS em {caminho_qjs}")
    else:
        Logger.warning("YouTubeDownload: QuickJS não disponível - formatos em qualidade alta podem faltar")

    formato_hd = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    formato_pronto = "22/18/best[acodec!=none][vcodec!=none]/best"

    try:
        caminho, video_id = _baixar_e_juntar_com_ytdlp(
            url,
            {**opcoes_extractor, "format": formato_hd},
            "YouTubeDownload",
        )
        return caminho, video_id, True
    except Exception as e:
        Logger.warning(f"YouTubeDownload: HD combinando perfis falhou: {type(e).__name__}: {e}")

    # Fallback: formato "pronto" (sem precisar de ffmpeg), mesmo que
    # fique em qualidade mais baixa.
    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "logger": _LoggerSilenciosoYtDlp(),
        "format": formato_pronto,
        **opcoes_extractor,
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)

    video_url = info.get("url")
    if video_url:
        video_id = re.sub(r"[^A-Za-z0-9_-]", "", info.get("id") or str(int(time.time())))
        return video_url, video_id, False

    raise RuntimeError("Nenhum formato de vídeo utilizável foi encontrado para esse link")


def _escrever_cookiejar_netscape(cookie_string, dominio):
    """Converte a string de cookies capturada do WebView (formato
    "nome=valor; nome2=valor2") pro formato Netscape que o yt-dlp espera
    no parâmetro 'cookiefile'."""
    caminho = os.path.join(
        App.get_running_app().user_data_dir if App.get_running_app() else os.path.expanduser("~"),
        ".instagram_cookies_netscape.txt",
    )
    linhas = ["# Netscape HTTP Cookie File"]
    for par in cookie_string.split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        nome, valor = par.split("=", 1)
        linhas.append(f"{dominio}\tTRUE\t/\tTRUE\t2147483647\t{nome.strip()}\t{valor.strip()}")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    return caminho


def resolver_instagram(url):
    """Usa o extrator de Instagram embutido no yt-dlp (mantido pela
    comunidade, atualizado com frequência) em vez de vasculhar o HTML da
    página na unha - o yt-dlp fala direto com os dados internos do
    Instagram, então não esbarra na parede de "vídeo em blob" que a
    página renderizada mostra. Agora que o ffmpeg funciona no
    dispositivo, prioriza a qualidade alta de verdade (vídeo e áudio
    separados, juntados com ffmpeg) - os formatos "prontos" (1/2/3) só
    entram como plano B, porque costumam vir em qualidade mais baixa."""
    import yt_dlp

    opcoes_base = {}
    cookie_sessao = carregar_sessao_instagram()
    if cookie_sessao:
        try:
            opcoes_base["cookiefile"] = _escrever_cookiejar_netscape(cookie_sessao, ".instagram.com")
            Logger.info("InstagramDownload: usando sessão logada junto com o yt-dlp")
        except Exception as e:
            Logger.error(f"InstagramDownload: falha ao preparar cookies pro yt-dlp: {e}")

    try:
        caminho, video_id = _baixar_e_juntar_com_ytdlp(
            url,
            {**opcoes_base, "format": "bestvideo+bestaudio/best"},
            "InstagramDownload",
        )
        return caminho, video_id, True
    except Exception as e:
        Logger.warning(f"InstagramDownload: HD com ffmpeg falhou, caindo pro formato pronto: {type(e).__name__}: {e}")

    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "logger": _LoggerSilenciosoYtDlp(),
        "format": "1/2/3/best[acodec!=none][vcodec!=none]/best",
        **opcoes_base,
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)

    video_url = info.get("url")
    if video_url:
        video_id = re.sub(r"[^A-Za-z0-9_-]", "", info.get("id") or str(int(time.time())))
        return video_url, video_id, False

    raise RuntimeError("yt-dlp não retornou um link de vídeo utilizável")


def abrir_reels_para_extrair(url, ao_obter_video, ao_falhar):
    """Abre o Reels numa WebView de verdade (o mesmo motor do Chrome do
    Android), deixando a página carregar e tocar o vídeo normalmente -
    isso usa a sessão logada automaticamente, porque o CookieManager do
    Android já guarda essa sessão entre WebViews do mesmo app. Depois,
    rodamos um pedacinho de JavaScript pra perguntar pro navegador qual é
    o link que o player de vídeo está usando."""
    if NO_ANDROID:
        ao_falhar("Essa extração só funciona no app Android instalado no celular.")
        return

    from jnius import autoclass, cast, PythonJavaClass, java_method
    from android.runnable import run_on_ui_thread

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    AndroidWebView = autoclass("android.webkit.WebView")
    WebViewClient = autoclass("android.webkit.WebViewClient")
    LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")

    atividade = PythonActivity.mActivity
    estado = {"webview": None, "fechado": False, "tentativas": 0}

    def _remover_webview():
        if estado["fechado"]:
            return
        estado["fechado"] = True

        @run_on_ui_thread
        def _remover():
            try:
                decor = cast("android.view.ViewGroup", atividade.getWindow().getDecorView())
                content = cast(
                    "android.view.ViewGroup",
                    decor.findViewById(autoclass("android.R$id").content),
                )
                content.removeView(estado["webview"])
            except Exception as e:
                Logger.error(f"InstagramWebView: falha ao remover webview: {e}")

        _remover()

    script_localizar_video = (
        "(function(){"
        "  var v = document.querySelector('video');"
        "  if (v && (v.currentSrc || v.src)) { return v.currentSrc || v.src; }"
        "  return '';"
        "})();"
    )

    class _RespostaJS(PythonJavaClass):
        __javainterfaces__ = ["android/webkit/ValueCallback"]
        __javacontext__ = "app"

        @java_method("(Ljava/lang/Object;)V")
        def onReceiveValue(self, valor):
            _processar_resultado(str(valor) if valor is not None else "")

    def _processar_resultado(valor_bruto):
        # O resultado de evaluateJavascript vem como uma string JSON (com
        # aspas em volta, tipo '"https://..."', ou 'null' se não achou).
        valor = valor_bruto.strip()
        if valor.startswith('"') and valor.endswith('"'):
            valor = valor[1:-1].encode().decode("unicode_escape")
        if valor and valor != "null":
            if valor.startswith("blob:"):
                Logger.error(f"InstagramWebView: vídeo veio como blob, não dá pra baixar direto: {valor}")
                Clock.unschedule(_verificar)
                _remover_webview()
                ao_falhar(
                    "O Instagram entregou o vídeo num formato que não dá pra baixar direto "
                    "(streaming interno da página, sem link de arquivo)."
                )
                return
            if valor.startswith("http"):
                Logger.info("InstagramWebView: link de vídeo encontrado na página")
                Clock.unschedule(_verificar)
                _remover_webview()
                ao_obter_video(valor)
                return

    def _verificar(dt):
        estado["tentativas"] += 1
        if estado["tentativas"] > 20:  # ~20s de tentativa
            Clock.unschedule(_verificar)
            _remover_webview()
            ao_falhar("Não consegui localizar o vídeo na página a tempo.")
            return

        @run_on_ui_thread
        def _rodar_js():
            try:
                estado["webview"].evaluateJavascript(script_localizar_video, _RespostaJS())
            except Exception as e:
                Logger.error(f"InstagramWebView: falha ao rodar JS: {e}")

        _rodar_js()

    @run_on_ui_thread
    def _abrir():
        webview = AndroidWebView(atividade)
        estado["webview"] = webview
        webview.getSettings().setJavaScriptEnabled(True)
        webview.getSettings().setDomStorageEnabled(True)
        webview.setWebViewClient(WebViewClient())
        atividade.addContentView(
            webview, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
        )
        webview.loadUrl(url)

    Logger.info(f"InstagramWebView: abrindo {url} pra localizar o vídeo")
    _abrir()
    Clock.schedule_interval(_verificar, 1.0)


class BotaoSecundario(Button):
    """Botão de contorno (sem preenchimento) pra ações secundárias, como
    'abrir em site de download'."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = COR_ACCENT
        self.font_size = "15sp"
        self.bold = True
        self.size_hint_y = None
        self.height = "46dp"
        with self.canvas.before:
            self._cor_borda = Color(*COR_ACCENT)
            self._linha = Line(width=1.4)
        self.bind(pos=self._atualizar, size=self._atualizar)

    def _atualizar(self, *args):
        self._linha.rounded_rectangle = [self.x, self.y, self.width, self.height, 12]


class PainelDownload(BoxLayout):
    """Painel genérico de download: campo de link + botão + status.
    Usado para TikTok, YouTube e Instagram - o que muda é a configuração
    (título, dica, validação do link, função resolvedora e a política de
    tentativas/mensagens de cada plataforma)."""

    def __init__(self, titulo, subtitulo, hint_text, palavra_chave, subpasta,
                 resolver, tentativas=4, espera_inicial=3, espera_exponencial=True,
                 mostrar_erro_detalhado=False, mensagem_intermediaria=False,
                 mostrar_botao_navegador=False, requer_login_instagram=False,
                 usar_webview_extracao=False,
                 **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))

        self.palavra_chave = palavra_chave
        self.subpasta = subpasta
        self.resolver = resolver
        self.usar_webview_extracao = usar_webview_extracao
        self.tentativas = tentativas
        self.espera_inicial = espera_inicial
        self.espera_exponencial = espera_exponencial
        self.mostrar_erro_detalhado = mostrar_erro_detalhado
        self.mensagem_intermediaria = mensagem_intermediaria
        self.mostrar_botao_navegador = mostrar_botao_navegador
        self.requer_login_instagram = requer_login_instagram

        # ---------- Cabeçalho ----------
        cabecalho = BoxLayout(orientation="vertical", size_hint_y=None, height="60dp", spacing=6)
        titulo_lbl = Label(
            text=titulo,
            font_size="22sp",
            bold=True,
            color=COR_TEXTO,
            size_hint_y=None,
            height="30dp",
        )
        subtitulo_lbl = Label(
            text=subtitulo,
            font_size="14sp",
            color=COR_TEXTO_MUTED,
            size_hint_y=None,
            height="20dp",
        )
        cabecalho.add_widget(titulo_lbl)
        cabecalho.add_widget(subtitulo_lbl)
        self.add_widget(cabecalho)

        self.add_widget(Widget(size_hint_y=None, height="20dp"))

        if self.requer_login_instagram:
            cartao_login = CartaoBase(orientation="vertical", padding=(18, 16), spacing=10, size_hint_y=None)
            cartao_login.bind(minimum_height=cartao_login.setter("height"))

            self.rotulo_login = Label(
                text="",
                font_size="13sp",
                color=COR_TEXTO_MUTED,
                size_hint_y=None,
                height="18dp",
                halign="left",
            )
            self.rotulo_login.bind(size=lambda w, s: setattr(w, "text_size", s))
            cartao_login.add_widget(self.rotulo_login)

            linha_botoes_login = BoxLayout(orientation="horizontal", size_hint_y=None, height="42dp", spacing=10)
            self.botao_entrar = BotaoSecundario(text="Entrar no Instagram")
            self.botao_entrar.height = "42dp"
            self.botao_entrar.bind(on_press=self.iniciar_login_instagram)
            linha_botoes_login.add_widget(self.botao_entrar)

            self.botao_sair_login = BotaoSecundario(text="Sair")
            self.botao_sair_login.height = "42dp"
            self.botao_sair_login.size_hint_x = 0.35
            self.botao_sair_login.bind(on_press=self.sair_instagram)
            linha_botoes_login.add_widget(self.botao_sair_login)

            cartao_login.add_widget(linha_botoes_login)
            self.add_widget(cartao_login)
            self.add_widget(Widget(size_hint_y=None, height="18dp"))

            self._atualizar_rotulo_login()

        # ---------- Cartão principal (link + botão) ----------
        cartao = CartaoBase(orientation="vertical", padding=(20, 22), spacing=16, size_hint_y=None)
        cartao.bind(minimum_height=cartao.setter("height"))

        rotulo_campo = Label(
            text="Link do vídeo",
            font_size="13sp",
            bold=True,
            color=COR_TEXTO_MUTED,
            size_hint_y=None,
            height="18dp",
            halign="left",
        )
        rotulo_campo.bind(size=lambda w, s: setattr(w, "text_size", s))
        cartao.add_widget(rotulo_campo)

        self.campo_container = CampoArredondado(hint_text=hint_text)
        cartao.add_widget(self.campo_container)

        self.botao = BotaoPrimario(text="Baixar vídeo")
        self.botao.bind(on_press=self.iniciar_download)
        cartao.add_widget(self.botao)

        if self.mostrar_botao_navegador:
            self.botao_navegador = BotaoSecundario(text="Abrir em site de download")
            self.botao_navegador.bind(on_press=self.abrir_site_externo)
            cartao.add_widget(self.botao_navegador)

        self.add_widget(cartao)

        self.add_widget(Widget(size_hint_y=None, height="18dp"))

        # ---------- Cartão de status ----------
        self.status = CaixaStatus()
        self.add_widget(self.status)

        self.add_widget(Widget(size_hint_y=None, height="18dp"))

        dica_texto = f"Os vídeos são salvos em Download/{subpasta}"
        if mostrar_botao_navegador:
            dica_texto += "\nO botão de site externo abre uma página de terceiros - preste atenção pra não clicar em anúncios disfarçados de botão de download."
        dica = Label(
            text=dica_texto,
            font_size="12sp",
            color=COR_TEXTO_MUTED,
            size_hint_y=None,
            height="20dp" if not mostrar_botao_navegador else "50dp",
        )
        self.add_widget(dica)

    def _atualizar_rotulo_login(self):
        conectado = carregar_sessao_instagram() is not None
        if conectado:
            self.rotulo_login.text = "Conectado ao Instagram"
        else:
            self.rotulo_login.text = "Não conectado - alguns vídeos só baixam depois de entrar"

    def iniciar_login_instagram(self, instance):
        self.rotulo_login.text = "Abrindo a página de login do Instagram..."
        abrir_login_instagram(self._login_concluido, self._login_cancelado)

    def _login_concluido(self, cookie_string):
        salvar_sessao_instagram(cookie_string)

        def _atualiza(dt):
            self._atualizar_rotulo_login()
            self.atualizar_status("sucesso", "Login feito! Agora tente baixar de novo.")

        Clock.schedule_once(_atualiza)

    def _login_cancelado(self, motivo):
        def _atualiza(dt):
            self.rotulo_login.text = motivo

        Clock.schedule_once(_atualiza)

    def sair_instagram(self, instance):
        apagar_sessao_instagram()
        self._atualizar_rotulo_login()
        self.atualizar_status("info", "Sessão do Instagram removida.")

    def abrir_site_externo(self, instance):
        url = self.campo_container.text.strip()
        palavras = self.palavra_chave if isinstance(self.palavra_chave, (list, tuple)) else [self.palavra_chave]
        if not url or not any(p in url.lower() for p in palavras):
            self.atualizar_status("erro", f"Cole um link válido do {self.subpasta}.")
            return
        try:
            abrir_no_navegador(montar_url_site_externo(url, self.subpasta))
        except Exception as e:
            Logger.error(f"{self.subpasta}Download: falha ao abrir navegador: {e}")
            self.atualizar_status("erro", "Não consegui abrir o navegador.")

    def atualizar_status(self, tipo, texto):
        def _atualiza(dt):
            self.status.definir(tipo, texto)

        Clock.schedule_once(_atualiza)

    def iniciar_download(self, instance):
        url = self.campo_container.text.strip()
        palavras = self.palavra_chave if isinstance(self.palavra_chave, (list, tuple)) else [self.palavra_chave]
        if not url or not any(p in url.lower() for p in palavras):
            self.atualizar_status("erro", f"Cole um link válido do {self.subpasta}.")
            return

        self.botao.disabled = True
        self.botao.text = "Baixando..."

        if self.usar_webview_extracao:
            self.atualizar_status("info", "Abrindo o Instagram pra localizar o vídeo...")
            id_match = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
            video_id = id_match.group(1) if id_match else str(int(time.time()))
            abrir_reels_para_extrair(
                url,
                lambda video_url: self._webview_video_encontrado(video_url, video_id),
                self._webview_falhou,
            )
            return

        self.atualizar_status("info", "Baixando o vídeo, aguarde...")
        thread = threading.Thread(target=self._baixar, args=(url,), daemon=True)
        thread.start()

    def _webview_video_encontrado(self, video_url, video_id):
        def _cont(dt):
            self.atualizar_status("info", "Vídeo localizado! Baixando...")
            thread = threading.Thread(
                target=self._baixar_url_direta, args=(video_url, video_id), daemon=True
            )
            thread.start()

        Clock.schedule_once(_cont)

    def _webview_falhou(self, motivo):
        def _cont(dt):
            self.botao.disabled = False
            self.botao.text = "Baixar vídeo"
            self.atualizar_status("erro", motivo)

        Clock.schedule_once(_cont)

    def _baixar_url_direta(self, video_url, video_id):
        """Baixa um vídeo cuja URL já foi resolvida (ex: pela WebView),
        sem passar de novo pela etapa de descobrir o link."""
        destino = pasta_destino(self.subpasta)
        os.makedirs(destino, exist_ok=True)
        try:
            self._salvar_video(video_url, video_id, destino)
        except Exception as e:
            Logger.error(f"{self.subpasta}Download: falha no download direto: {type(e).__name__}: {e}")
            Logger.error(f"{self.subpasta}Download: " + traceback.format_exc())
            self.atualizar_status("erro", f"O vídeo foi encontrado, mas o download falhou: {e}")

        def _restaurar(dt):
            self.botao.disabled = False
            self.botao.text = "Baixar vídeo"

        Clock.schedule_once(_restaurar)

    def _salvar_video(self, video_url_ou_caminho, video_id, destino, ja_baixado=False):
        nome_arquivo = f"{video_id}.mp4"
        caminho_final = os.path.join(destino, nome_arquivo)

        if ja_baixado:
            origem = video_url_ou_caminho
            if not os.path.exists(origem):
                raise RuntimeError("O yt-dlp disse que baixou, mas o arquivo não foi encontrado")
            if os.path.getsize(origem) < 10_000:
                raise RuntimeError(f"Download incompleto ({os.path.getsize(origem)} bytes)")
            if os.path.abspath(origem) != os.path.abspath(caminho_final):
                shutil.move(origem, caminho_final)
        else:
            video_req = urllib.request.Request(video_url_ou_caminho, headers=_CABECALHOS)
            with urllib.request.urlopen(video_req, timeout=60, context=CONTEXTO_SSL) as resp_video:
                conteudo = resp_video.read()

            if len(conteudo) < 10_000:
                raise RuntimeError(f"Download incompleto ({len(conteudo)} bytes)")

            with open(caminho_final, "wb") as f:
                f.write(conteudo)

        notificar_galeria(caminho_final)
        self.atualizar_status(
            "sucesso", f"Concluído! Salvo em Download/{self.subpasta}/{nome_arquivo}"
        )

    def _baixar(self, url):
        destino = pasta_destino(self.subpasta)
        os.makedirs(destino, exist_ok=True)

        tentativas = self.tentativas
        espera = self.espera_inicial
        ultimo_erro = None

        for tentativa in range(1, tentativas + 1):
            try:
                resultado = self.resolver(url)
                if len(resultado) == 3:
                    video_url, video_id, ja_baixado = resultado
                else:
                    video_url, video_id = resultado
                    ja_baixado = False
                self._salvar_video(video_url, video_id, destino, ja_baixado=ja_baixado)
                ultimo_erro = None
                break
            except Exception as e:
                ultimo_erro = e
                # Loga o erro real no logcat, mesmo que a tela continue
                # mostrando só "Baixando..." pro usuário enquanto ainda há
                # tentativas sobrando. Ver com: adb logcat | grep Download
                Logger.error(
                    f"{self.subpasta}Download: tentativa {tentativa}/{tentativas} falhou: "
                    f"{type(e).__name__}: {e}"
                )
                Logger.error(f"{self.subpasta}Download: " + traceback.format_exc())
                if tentativa < tentativas:
                    if self.mensagem_intermediaria:
                        self.atualizar_status("info", "Não deu certo, tentando de novo...")
                    time.sleep(espera)
                    if self.espera_exponencial:
                        espera *= 2

        if ultimo_erro is not None:
            if self.mostrar_erro_detalhado:
                self.atualizar_status("erro", f"Não foi possível baixar: {ultimo_erro}")
            else:
                self.atualizar_status(
                    "erro",
                    "Não foi possível baixar esse vídeo agora. Tente novamente em alguns segundos.",
                )

        def _restaurar(dt):
            self.botao.disabled = False
            self.botao.text = "Baixar vídeo"

        Clock.schedule_once(_restaurar)


class TelaPrincipal(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        raiz_externa = BoxLayout(orientation="vertical")
        self.add_widget(raiz_externa)

        # ---------- Barra de abas fixa no topo ----------
        barra_abas = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            padding=(16, 6),
            spacing=8,
        )
        raiz_externa.add_widget(barra_abas)

        self.paineis = {}
        self.botoes_aba = {}

        configuracoes = [
            {
                "chave": "tiktok", "rotulo_aba": "TikTok",
                "titulo": "Downloader TikTok", "subtitulo": "HD, sem marca d'água",
                "hint_text": "Cole aqui o link do TikTok...",
                "palavra_chave": "tiktok", "subpasta": "TikTok",
                "resolver": resolver_tiktok,
                # Igual ao app original: 4 tentativas silenciosas, espera
                # crescente, mensagem de erro genérica no final.
                "tentativas": 4, "espera_inicial": 3, "espera_exponencial": True,
                "mostrar_erro_detalhado": False, "mensagem_intermediaria": False,
            },
            {
                "chave": "youtube", "rotulo_aba": "YouTube",
                "titulo": "Downloader YouTube", "subtitulo": "Vídeos em HD",
                "hint_text": "Cole aqui o link do YouTube...",
                "palavra_chave": ["youtube.com", "youtu.be"], "subpasta": "YouTube",
                "resolver": resolver_youtube,
                "tentativas": 2, "espera_inicial": 2, "espera_exponencial": False,
                "mostrar_erro_detalhado": True, "mensagem_intermediaria": True,
                "mostrar_botao_navegador": False,
            },
            {
                "chave": "instagram", "rotulo_aba": "Instagram",
                "titulo": "Downloader Instagram", "subtitulo": "Posts e Reels em HD",
                "hint_text": "Cole aqui o link do Instagram...",
                "palavra_chave": "instagram", "subpasta": "Instagram",
                "resolver": resolver_instagram,
                "tentativas": 2, "espera_inicial": 2, "espera_exponencial": False,
                "mostrar_erro_detalhado": True, "mensagem_intermediaria": True,
                "mostrar_botao_navegador": False, "requer_login_instagram": False,
                "usar_webview_extracao": False,
            },
        ]

        # ---------- Área de conteúdo (troca conforme a aba ativa) ----------
        scroll = ScrollView(do_scroll_x=False, size_hint=(1, 1))
        self.scroll = scroll
        raiz_externa.add_widget(scroll)

        self.container_conteudo = BoxLayout(
            orientation="vertical", padding=(24, 24, 24, 32), size_hint_y=None
        )
        self.container_conteudo.bind(minimum_height=self.container_conteudo.setter("height"))
        scroll.add_widget(self.container_conteudo)

        for cfg in configuracoes:
            botao = BotaoAba(text=cfg["rotulo_aba"])
            botao.bind(on_press=lambda inst, k=cfg["chave"]: self.trocar_aba(k))
            barra_abas.add_widget(botao)
            self.botoes_aba[cfg["chave"]] = botao

            painel = PainelDownload(
                titulo=cfg["titulo"],
                subtitulo=cfg["subtitulo"],
                hint_text=cfg["hint_text"],
                palavra_chave=cfg["palavra_chave"],
                subpasta=cfg["subpasta"],
                resolver=cfg["resolver"],
                tentativas=cfg["tentativas"],
                espera_inicial=cfg["espera_inicial"],
                espera_exponencial=cfg["espera_exponencial"],
                mostrar_erro_detalhado=cfg["mostrar_erro_detalhado"],
                mensagem_intermediaria=cfg["mensagem_intermediaria"],
                mostrar_botao_navegador=cfg.get("mostrar_botao_navegador", False),
                requer_login_instagram=cfg.get("requer_login_instagram", False),
                usar_webview_extracao=cfg.get("usar_webview_extracao", False),
            )
            painel.campo_container.campo.bind(
                focus=lambda inst, focado: setattr(self.scroll, "do_scroll_y", not focado)
            )
            self.paineis[cfg["chave"]] = painel

        # ---------- Crédito fixo no canto inferior direito ----------
        credito = Label(
            text="by @1hao",
            font_size="11sp",
            color=COR_TEXTO_MUTED,
            size_hint=(None, None),
            size=("80dp", "20dp"),
            pos_hint={"right": 0.97, "y": 0.015},
            halign="right",
        )
        self.add_widget(credito)

        self.trocar_aba("tiktok")

    def trocar_aba(self, chave):
        self.container_conteudo.clear_widgets()
        self.container_conteudo.add_widget(self.paineis[chave])
        for k, botao in self.botoes_aba.items():
            botao.definir_ativo(k == chave)
        self.scroll.scroll_y = 1


class TikTokDownloaderApp(App):
    def build(self):
        if not NO_ANDROID:
            request_permissions([
                Permission.INTERNET,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ])
        return TelaPrincipal()


if __name__ == "__main__":
    TikTokDownloaderApp().run()
