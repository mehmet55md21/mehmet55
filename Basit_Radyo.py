import os
import sys
import ctypes
import wx
import datetime
import configparser
import requests
import threading
import re
import logging
import subprocess
import time
import webbrowser
import json
import shutil
import html
import urllib.request
import urllib.parse
from wx.adv import TaskBarIcon, EVT_TASKBAR_LEFT_DCLICK

# ——— LOGGING AYARLARI ———
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ——— VERİ MODELİ ———
class RadioStation:
    def __init__(self, name, url, creation_time=None):
        self.name = name
        self.url = url
        self.creation_time = creation_time or datetime.datetime.now()

    def __repr__(self):
        return f"RadioStation(name='{self.name}', url='{self.url}')"

# ——— SABİTLER VE DİZİN YAPISI ———
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
BIN_DIR = os.path.join(BASE_DIR, "bin")
os.makedirs(BIN_DIR, exist_ok=True)
os.chdir(BASE_DIR)

PROFILES_DIR = os.path.join(BIN_DIR, "profiles")
BASS_DIR = os.path.join(BIN_DIR, "bass")

FFMPEG_EXE = os.path.join(BIN_DIR, "ffmpeg.exe")
PLAYLIST_FILE = os.path.join(PROFILES_DIR, "playlist.m3u")
INI_FILE = os.path.join(PROFILES_DIR, "settings.ini")
FAVORITES_FILE = os.path.join(PROFILES_DIR, "favorites.json")
LOGS_DIR = os.path.join(BIN_DIR, "logs")

os.makedirs(PROFILES_DIR, exist_ok=True)

DEFAULT_PATH_PLACEHOLDER = "<DEFAULT>"

BASS_ATTRIB_VOL = 2
BASS_CONFIG_NET_TIMEOUT = 5
BASS_UNICODE = 0x80000000
BASS_TAG_META = 5
BASS_POS_BYTE = 0
BASS_CONFIG_NET_PLAYLIST = 21
BASS_CONFIG_NET_AGENT = 16

API_BASE_URL = "http://all.api.radio-browser.info/json/stations"
CONTACT_EMAIL = "mehmet55.md1980@gmail.com"
APP_VERSION = "6.7"
GITHUB_REPO = "mehmet55md21/mehmet55"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# --- METİN NORMALLEŞTİRME (TÜRKÇE KARAKTER DUYARSIZLIĞI) ---
def normalize_radio_name(text):
    if not text:
        return ""
    text = text.lower()
    charmap = {
        'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u',
        'i̇': 'i', 'î': 'i', 'â': 'a'
    }
    for k, v in charmap.items():
        text = text.replace(k, v)
    return text.strip()

def parse_version(version_text):
    version_text = (version_text or "").strip().lower().lstrip("v")
    parts = []
    for part in re.split(r"[.\-_\s]+", version_text):
        if part.isdigit():
            parts.append(int(part))
        else:
            match = re.match(r"(\d+)", part)
            if match:
                parts.append(int(match.group(1)))
    return tuple(parts or [0])

def is_newer_version(latest_version, current_version):
    latest = parse_version(latest_version)
    current = parse_version(current_version)
    max_len = max(len(latest), len(current))
    latest += (0,) * (max_len - len(latest))
    current += (0,) * (max_len - len(current))
    return latest > current

def migrate_old_files():
    files_to_move = {
        os.path.join(BASE_DIR, "playlist.m3u"): PLAYLIST_FILE,
        os.path.join(BASE_DIR, "settings.ini"): INI_FILE,
        os.path.join(BASE_DIR, "favorites.json"): FAVORITES_FILE,
    }
    migrated = False
    for old_path, new_path in files_to_move.items():
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(old_path, new_path)
                logging.info(f"'{old_path}' yeni dizine taşındı: {new_path}")
                migrated = True
            except Exception as e:
                logging.error(f"'{old_path}' taşınırken hata: {e}")
    if migrated:
        print("Bilgi: Ayarlar ve listeler yeni 'bin/profiles' klasörüne taşındı.")

migrate_old_files()

config = configparser.ConfigParser()

def save_config():
    with open(INI_FILE, "w", encoding="utf-8") as f:
        config.write(f)

if os.path.exists(INI_FILE):
    config.read(INI_FILE, encoding="utf-8-sig")
else:
    config["General"] = {}

default_settings = {
    "accessibility": "False",
    "record_path": DEFAULT_PATH_PLACEHOLDER,
    "filter_web_duplicates": "True",
    "fallback_to_radio_browser": "True",
    "default_list": "Tüm Radyolar",
    "last_sort_order": "date_asc",
    "play_on_startup": "False",
    "last_played_index": "-1",
    "show_now_playing_in_list": "False",
    "record_seek_seconds": "5",
    "net_timeout_seconds": "30",
    "search_source": "FMStream.org",
    "enable_logging": "True",
    "auto_update_check": "True",
}

modified = False
if "General" not in config:
    config["General"] = {}
    modified = True

for k, v in default_settings.items():
    if k not in config["General"]:
        config["General"][k] = v
        modified = True

if modified:
    save_config()

def configure_file_logging():
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, "_basit_radyo_file_handler", False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    if not config.getboolean("General", "enable_logging", fallback=True):
        return None

    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = os.path.join(LOGS_DIR, f"Basit_Radyo_{stamp}.log")
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler._basit_radyo_file_handler = True
        root_logger.addHandler(handler)
        logging.info("Dosya günlüğü başlatıldı: %s", log_path)
        return log_path
    except Exception as e:
        logging.error(f"Log dosyası başlatılamadı: {e}")
        return None

CURRENT_LOG_FILE = configure_file_logging()
BASS_LOCK = threading.RLock()

def get_record_path():
    path_from_config = config["General"].get("record_path", DEFAULT_PATH_PLACEHOLDER)
    if path_from_config == DEFAULT_PATH_PLACEHOLDER:
        return os.path.join(BASE_DIR, "kayıtlar")
    else:
        return path_from_config

record_path = get_record_path()
if not os.path.isdir(record_path):
    try:
        os.makedirs(record_path, exist_ok=True)
    except Exception as e:
        logging.error(f"Kayıt klasörü '{record_path}' oluşturulamadı: {e}")
        try:
            wx.CallAfter(
                wx.MessageBox,
                f"Kayıt klasörü '{record_path}' oluşturulamadı.\nAyarlardan geçerli bir klasör seçin.",
                "Kayıt Klasörü Hatası",
                wx.ICON_ERROR,
            )
        except Exception:
            pass

def init_bass():
    try:
        bass_dll_path = os.path.join(BASS_DIR, "bass.dll")
        if not os.path.exists(bass_dll_path):
            raise FileNotFoundError
        bass = ctypes.CDLL(bass_dll_path)
    except (OSError, FileNotFoundError):
        wx.MessageBox(
            "BASS kütüphanesi (bass.dll) bulunamadı veya yüklenemedi.\nLütfen 'bass' klasörünü kontrol edin.",
            "Kritik Hata",
            wx.ICON_ERROR,
        )
        sys.exit(1)

    if not bass.BASS_Init(-1, 44100, 0, 0, 0):
        wx.MessageBox(f"BASS başlatılamadı: {bass.BASS_ErrorGetCode()}", "Hata", wx.ICON_ERROR)
        sys.exit(1)

    timeout_ms = int(config["General"].get("net_timeout_seconds", "30")) * 1000
    bass.BASS_SetConfig(BASS_CONFIG_NET_TIMEOUT, timeout_ms)
    bass.BASS_SetConfig(BASS_CONFIG_NET_PLAYLIST, 1)

    user_agent = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    try:
        bass.BASS_SetConfigPtr.argtypes = [ctypes.c_uint, ctypes.c_char_p]
        bass.BASS_SetConfigPtr(BASS_CONFIG_NET_AGENT, user_agent)
    except AttributeError:
        old_argtypes = getattr(bass.BASS_SetConfig, "argtypes", None)
        bass.BASS_SetConfig.argtypes = [ctypes.c_uint, ctypes.c_char_p]
        bass.BASS_SetConfig(BASS_CONFIG_NET_AGENT, user_agent)
        bass.BASS_SetConfig.argtypes = old_argtypes

    bass.BASS_PluginLoad.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    bass.BASS_PluginLoad.restype = ctypes.c_ulong
    for plugin_name in ("basshls.dll", "bass_aac.dll", "bassflac.dll", "bassopus.dll", "basswma.dll"):
        plugin_path = os.path.join(BASS_DIR, plugin_name)
        if os.path.exists(plugin_path):
            plugin_handle = bass.BASS_PluginLoad(plugin_path.encode("utf-8"), 0)
            if plugin_handle:
                logging.info("BASS eklentisi yüklendi: %s", plugin_name)
            else:
                logging.warning("BASS eklentisi yüklenemedi: %s hata=%s", plugin_name, bass.BASS_ErrorGetCode())

    bass.BASS_StreamCreateURL.argtypes = [
        ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
    bass.BASS_StreamCreateURL.restype = ctypes.c_uint

    bass.BASS_StreamCreateFile.argtypes = [
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint]
    bass.BASS_StreamCreateFile.restype = ctypes.c_uint

    bass.BASS_ChannelIsActive.argtypes = [ctypes.c_uint]
    bass.BASS_ChannelIsActive.restype = ctypes.c_uint

    bass.BASS_ChannelPause.argtypes = [ctypes.c_uint]
    bass.BASS_ChannelPause.restype = ctypes.c_bool

    bass.BASS_ChannelPlay.argtypes = [ctypes.c_uint, ctypes.c_bool]
    bass.BASS_ChannelPlay.restype = ctypes.c_bool

    bass.BASS_StreamFree.argtypes = [ctypes.c_uint]
    bass.BASS_StreamFree.restype = ctypes.c_bool

    bass.BASS_ChannelSetAttribute.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_float]
    bass.BASS_ChannelSetAttribute.restype = ctypes.c_bool

    bass.BASS_ChannelGetTags.argtypes = [ctypes.c_uint, ctypes.c_int]
    bass.BASS_ChannelGetTags.restype = ctypes.c_char_p

    bass.BASS_ChannelGetPosition.argtypes = [ctypes.c_uint, ctypes.c_uint]
    bass.BASS_ChannelGetPosition.restype = ctypes.c_uint64

    bass.BASS_ChannelSetPosition.argtypes = [ctypes.c_uint, ctypes.c_uint64, ctypes.c_uint]
    bass.BASS_ChannelSetPosition.restype = ctypes.c_bool

    bass.BASS_ChannelGetLength.argtypes = [ctypes.c_uint, ctypes.c_uint]
    bass.BASS_ChannelGetLength.restype = ctypes.c_uint64

    bass.BASS_ChannelBytes2Seconds.argtypes = [ctypes.c_uint, ctypes.c_uint64]
    bass.BASS_ChannelBytes2Seconds.restype = ctypes.c_double

    bass.BASS_ChannelSeconds2Bytes.argtypes = [ctypes.c_uint, ctypes.c_double]
    bass.BASS_ChannelSeconds2Bytes.restype = ctypes.c_uint64

    return bass

NVDA_AVAILABLE = False
try:
    nvda_dll_path = os.path.join(BIN_DIR, "nvdaControllerClient64.dll")
    if os.path.exists(nvda_dll_path):
        nvda = ctypes.WinDLL(nvda_dll_path)
        nvda.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
        nvda.nvdaController_speakText.restype = None
        NVDA_AVAILABLE = True
except Exception as e:
    logging.info(f"NVDA yüklenemedi: {e}")

def speak(parent, msg):
    frm = parent if isinstance(parent, wx.Frame) else parent.GetParent()
    if getattr(frm, "accessibility_enabled", False) and NVDA_AVAILABLE:
        nvda.nvdaController_speakText(msg)

def speak_or_dialog(parent, msg, title="Bilgi", style=wx.ICON_INFORMATION):
    frm = parent if isinstance(parent, wx.Frame) else parent.GetParent()
    if getattr(frm, "accessibility_enabled", False) and NVDA_AVAILABLE:
        nvda.nvdaController_speakText(msg)
    else:
        wx.CallAfter(wx.MessageBox, msg, title, style)


# ——— DIALOG ve YARDIMCI SINIFLAR ———
class StreamSelectionDialog(wx.Dialog):
    def __init__(self, parent, station_name, streams, main_frame):
        super().__init__(parent, title=f"Akış Seç - {station_name}", size=(450, 300))
        self.streams = streams
        self.main_frame = main_frame
        self.preview_stream = ctypes.c_uint(0)
        self.current_preview_url = ""
        
        pnl = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        
        lbl = wx.StaticText(pnl, label=f"{len(streams)} akış bulundu (Boşluk: Önizleme, Enter: Ekle):")
        s.Add(lbl, 0, wx.ALL, 10)
        
        self.list_box = wx.ListBox(pnl, choices=streams)
        self.list_box.SetSelection(0)
        s.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(pnl, wx.ID_OK, "Ekle")
        cancel_button = wx.Button(pnl, wx.ID_CANCEL, "İptal")
        btns.AddButton(ok_button)
        btns.AddButton(cancel_button)
        btns.Realize()
        self.SetDefaultItem(ok_button)
        
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        pnl.SetSizer(s)
        
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_dclick)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_BUTTON, self.on_ok_btn, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_cancel_btn, id=wx.ID_CANCEL)
        
        self.list_box.SetFocus()

    def toggle_preview(self):
        global bass
        sel = self.list_box.GetSelection()
        if sel == wx.NOT_FOUND:
            return
            
        url = self.streams[sel]
        
        if self.preview_stream.value != 0 and self.current_preview_url == url:
            if bass.BASS_ChannelIsActive(self.preview_stream) == 1:
                bass.BASS_ChannelPause(self.preview_stream)
                speak(self, "Önizleme duraklatıldı.")
            else:
                bass.BASS_ChannelPlay(self.preview_stream, False)
                speak(self, "Önizleme oynatılıyor.")
            return
            
        if self.preview_stream.value != 0:
            bass.BASS_StreamFree(self.preview_stream)
            self.preview_stream = ctypes.c_uint(0)
            
        if self.main_frame.current_stream.value != 0 and bass.BASS_ChannelIsActive(self.main_frame.current_stream) == 1:
            bass.BASS_ChannelPause(self.main_frame.current_stream)
            
        if self.main_frame.record_play_stream.value != 0 and bass.BASS_ChannelIsActive(self.main_frame.record_play_stream) == 1:
            bass.BASS_ChannelPause(self.main_frame.record_play_stream)
            
        speak(self, "Bağlanılıyor...")
        wx.Yield()
        
        s = bass.BASS_StreamCreateURL(url.encode("utf-8"), 0, 0, None, None)
        if s == 0:
            err = bass.BASS_ErrorGetCode()
            speak(self, f"Bağlantı hatası (Hata kodu: {err})")
            return
            
        self.preview_stream = ctypes.c_uint(s)
        self.current_preview_url = url
        bass.BASS_ChannelSetAttribute(self.preview_stream, 2, ctypes.c_float(self.main_frame.volume / 100.0))
        bass.BASS_ChannelPlay(self.preview_stream, False)
        speak(self, "Önizleme oynatılıyor.")

    def cleanup_and_close(self, return_code):
        global bass
        if getattr(self, "preview_stream", None) and self.preview_stream.value != 0:
            bass.BASS_StreamFree(self.preview_stream)
            self.preview_stream = ctypes.c_uint(0)
        self.EndModal(return_code)

    def on_ok_btn(self, event):
        self.cleanup_and_close(wx.ID_OK)

    def on_cancel_btn(self, event):
        self.cleanup_and_close(wx.ID_CANCEL)

    def on_dclick(self, event):
        self.cleanup_and_close(wx.ID_OK)

    def copy_selected_stream_url(self):
        url = self.get_selected_url()
        if not url:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(url))
            wx.TheClipboard.Close()
            speak(self.main_frame, "Akış adresi kopyalandı.")
        
    def on_key(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and not event.ShiftDown() and not event.AltDown() and key == ord("C"):
            self.copy_selected_stream_url()
        elif key == wx.WXK_ESCAPE:
            self.cleanup_and_close(wx.ID_CANCEL)
        elif key == wx.WXK_SPACE:
            self.toggle_preview()
        elif key == wx.WXK_RETURN:
            self.cleanup_and_close(wx.ID_OK)
        else:
            event.Skip()
            
    def on_close(self, event):
        self.cleanup_and_close(wx.ID_CANCEL)
        
    def get_selected_url(self):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND:
            return self.streams[sel]
        return None

class ManageFavoritesDialog(wx.Dialog):
    def __init__(self, parent, favorites_dict):
        super().__init__(parent, title="Favori Listelerini Yönet", size=(350, 400))
        self.favorites = favorites_dict.copy()

        pnl = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        main_sizer.Add(wx.StaticText(pnl, label="Mevcut Listeler:"), 0, wx.ALL, 10)
        self.list_box = wx.ListBox(pnl)
        self.list_box.Set(sorted(self.favorites.keys()))
        main_sizer.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_rename = wx.Button(pnl, label="Yeniden Adlandır...")
        btn_delete = wx.Button(pnl, label="Sil")
        btn_sizer.Add(btn_rename, 0, wx.RIGHT, 5)
        btn_sizer.Add(btn_delete, 0)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        close_button = wx.Button(pnl, wx.ID_OK, "Kapat")
        main_sizer.Add(close_button, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        pnl.SetSizer(main_sizer)
        self.SetDefaultItem(close_button)

        btn_rename.Bind(wx.EVT_BUTTON, self.on_rename)
        btn_delete.Bind(wx.EVT_BUTTON, self.on_delete)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_rename)

    def on_rename(self, event):
        selection = self.list_box.GetStringSelection()
        if not selection:
            speak_or_dialog(self, "Önce bir liste seçin.", "Uyarı", wx.ICON_WARNING)
            return

        with wx.TextEntryDialog(self, f"'{selection}' için yeni adı girin:", "Yeniden Adlandır", value=selection) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                new_name = dlg.GetValue().strip()
                if new_name and new_name != selection and new_name not in self.favorites:
                    self.favorites[new_name] = self.favorites.pop(selection)
                    idx = self.list_box.FindString(selection)
                    self.list_box.SetString(idx, new_name)
                    speak(self.GetParent(), f"Liste '{selection}' adından '{new_name}' adına değiştirildi.")

    def on_delete(self, event):
        selection = self.list_box.GetStringSelection()
        if not selection:
            speak_or_dialog(self, "Önce bir liste seçin.", "Uyarı", wx.ICON_WARNING)
            return

        with wx.MessageDialog(
            self,
            f"'{selection}' listesini silmek istediğinizden emin misiniz?\nBu işlem geri alınamaz.",
            "Silmeyi Onayla",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_YES:
                self.favorites.pop(selection, None)
                self.list_box.Delete(self.list_box.GetSelection())
                speak(self.GetParent(), f"'{selection}' listesi silindi.")

    def get_updated_favorites(self):
        return self.favorites

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, favorite_lists):
        super().__init__(parent, title="Ayarlar", size=(580, 480))
        
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.listbook = wx.Listbook(self, wx.ID_ANY, style=wx.BK_DEFAULT)

        # 1. KATEGORİ: GENEL VE GÖRÜNÜM
        pnl_general = wx.Panel(self.listbook)
        sz_general = wx.BoxSizer(wx.VERTICAL)
        
        self.chk_play_on_startup = wx.CheckBox(pnl_general, wx.ID_ANY, "Açılışta son çalınan radyoyu oynat")
        self.chk_play_on_startup.SetValue(config.getboolean("General", "play_on_startup", fallback=False))
        sz_general.Add(self.chk_play_on_startup, 0, wx.ALL, 10)

        self.chk_show_now_playing = wx.CheckBox(pnl_general, wx.ID_ANY, "Çalan yayındaki bilgiyi listede radyo adının yanında göster")
        self.chk_show_now_playing.SetValue(config.getboolean("General", "show_now_playing_in_list", fallback=False))
        sz_general.Add(self.chk_show_now_playing, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.chk_enable_logging = wx.CheckBox(pnl_general, wx.ID_ANY, "Sorun giderme loglarını dosyaya kaydet")
        self.chk_enable_logging.SetValue(config.getboolean("General", "enable_logging", fallback=True))
        sz_general.Add(self.chk_enable_logging, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sz_general.Add(wx.StaticText(pnl_general, label="Başlangıç Listesi:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        all_lists = ["Tüm Radyolar"] + favorite_lists
        self.choice_default_list = wx.Choice(pnl_general, choices=all_lists)
        default_list_setting = config.get("General", "default_list", fallback="Tüm Radyolar")
        if default_list_setting in all_lists:
            self.choice_default_list.SetStringSelection(default_list_setting)
        else:
            self.choice_default_list.SetSelection(0)
        sz_general.Add(self.choice_default_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        pnl_general.SetSizer(sz_general)
        self.listbook.AddPage(pnl_general, "Genel ve Görünüm")

        # 2. KATEGORİ: BAĞLANTI VE WEB
        pnl_web = wx.Panel(self.listbook)
        sz_web = wx.BoxSizer(wx.VERTICAL)

        h_source = wx.BoxSizer(wx.HORIZONTAL)
        h_source.Add(wx.StaticText(pnl_web, label="Arama Kaynağı:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.choice_source = wx.Choice(pnl_web, choices=["Radio-Browser", "FMStream.org"])
        source_val = config.get("General", "search_source", fallback="FMStream.org")
        if source_val in ["Radio-Browser", "FMStream.org"]:
            self.choice_source.SetStringSelection(source_val)
        else:
            self.choice_source.SetStringSelection("FMStream.org")
        h_source.Add(self.choice_source, 1, wx.EXPAND)
        sz_web.Add(h_source, 0, wx.EXPAND | wx.ALL, 10)

        h_time = wx.BoxSizer(wx.HORIZONTAL)
        h_time.Add(wx.StaticText(pnl_web, label="Bağlantı zaman aşımı süresi (saniye):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        timeout_val = config.getint("General", "net_timeout_seconds", fallback=30)
        self.spin_timeout = wx.SpinCtrl(pnl_web, wx.ID_ANY, min=5, max=120, initial=timeout_val)
        h_time.Add(self.spin_timeout, 0)
        sz_web.Add(h_time, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.chk_filter = wx.CheckBox(pnl_web, wx.ID_ANY, "Web aramasında yinelenen isimleri filtrele")
        self.chk_filter.SetValue(config.getboolean("General", "filter_web_duplicates", fallback=True))
        sz_web.Add(self.chk_filter, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.chk_fallback_to_radio_browser = wx.CheckBox(
            pnl_web,
            wx.ID_ANY,
            "FMStream araması başarısız olursa Radio-Browser ile devam et",
        )
        self.chk_fallback_to_radio_browser.SetValue(
            config.getboolean("General", "fallback_to_radio_browser", fallback=True)
        )
        sz_web.Add(self.chk_fallback_to_radio_browser, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        pnl_web.SetSizer(sz_web)
        self.listbook.AddPage(pnl_web, "Bağlantı ve Web")

        # 3. KATEGORİ: KAYIT İŞLEMLERİ
        pnl_rec = wx.Panel(self.listbook)
        sz_rec = wx.BoxSizer(wx.VERTICAL)

        sz_rec.Add(wx.StaticText(pnl_rec, label="Kayıt Klasörü:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        h_path = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_path = wx.TextCtrl(pnl_rec, value=get_record_path())
        h_path.Add(self.txt_path, 1, wx.EXPAND)
        btn_browse = wx.Button(pnl_rec, label="Gözat...")
        btn_browse.Bind(wx.EVT_BUTTON, self.on_browse)
        h_path.Add(btn_browse, 0, wx.LEFT, 5)
        sz_rec.Add(h_path, 0, wx.EXPAND | wx.ALL, 10)

        h_seek = wx.BoxSizer(wx.HORIZONTAL)
        h_seek.Add(wx.StaticText(pnl_rec, label="Kayıt ileri/geri alma adımı (saniye):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        seek_val = config.getint("General", "record_seek_seconds", fallback=5)
        self.spin_seek = wx.SpinCtrl(pnl_rec, wx.ID_ANY, min=1, max=600, initial=seek_val)
        h_seek.Add(self.spin_seek, 0)
        sz_rec.Add(h_seek, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        pnl_rec.SetSizer(sz_rec)
        self.listbook.AddPage(pnl_rec, "Kayıt İşlemleri")

        # 4. KATEGORİ: ERİŞİLEBİLİRLİK
        pnl_acc = wx.Panel(self.listbook)
        sz_acc = wx.BoxSizer(wx.VERTICAL)

        self.chk_accessibility = wx.CheckBox(pnl_acc, wx.ID_ANY, "Ekran okuyucu (NVDA) mesajlarını etkinleştir")
        self.chk_accessibility.SetValue(config.getboolean("General", "accessibility"))
        if not NVDA_AVAILABLE:
            self.chk_accessibility.Disable()
            sz_acc.Add(wx.StaticText(pnl_acc, label="(NVDA eklentisi bulunamadığı için bu ayar devre dışı)"), 0, wx.LEFT | wx.TOP, 10)
        sz_acc.Add(self.chk_accessibility, 0, wx.ALL, 10)

        pnl_acc.SetSizer(sz_acc)
        self.listbook.AddPage(pnl_acc, "Erişilebilirlik")

        # 5. KATEGORI: GUNCELLEMELER
        pnl_updates = wx.Panel(self.listbook)
        sz_updates = wx.BoxSizer(wx.VERTICAL)

        self.chk_auto_update = wx.CheckBox(pnl_updates, wx.ID_ANY, "Program açılışında güncellemeleri otomatik denetle")
        self.chk_auto_update.SetValue(config.getboolean("General", "auto_update_check", fallback=True))
        sz_updates.Add(self.chk_auto_update, 0, wx.ALL, 10)

        pnl_updates.SetSizer(sz_updates)
        self.listbook.AddPage(pnl_updates, "Güncellemeler")

        main_sizer.Add(self.listbook, 1, wx.EXPAND | wx.ALL, 10)

        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(self, wx.ID_OK, "Tamam")
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL, "İptal"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        
        main_sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizer(main_sizer)

    def on_browse(self, event):
        dlg = wx.DirDialog(self, "Kayıt klasörünü seçin", style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            self.txt_path.SetValue(dlg.GetPath())
        dlg.Destroy()

    def get_values(self):
        return {
            "accessibility": self.chk_accessibility.GetValue(),
            "play_on_startup": self.chk_play_on_startup.GetValue(),
            "filter_web_duplicates": self.chk_filter.GetValue(),
            "fallback_to_radio_browser": self.chk_fallback_to_radio_browser.GetValue(),
            "record_path": self.txt_path.GetValue(),
            "default_list": self.choice_default_list.GetStringSelection(),
            "show_now_playing_in_list": self.chk_show_now_playing.GetValue(),
            "record_seek_seconds": self.spin_seek.GetValue(),
            "net_timeout_seconds": self.spin_timeout.GetValue(),
            "search_source": self.choice_source.GetStringSelection(),
            "enable_logging": self.chk_enable_logging.GetValue(),
            "auto_update_check": self.chk_auto_update.GetValue(),
        }

class TimedRecordDialog(wx.Dialog):
    def __init__(self, parent, radios):
        super().__init__(parent, title="Zamanlı Kayıt Ayarla", size=(400, 280))
        self.radios = radios
        pnl = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)

        for label_text in ["Başlangıç Saati (SS:DD):", "Bitiş Saati (SS:DD):"]:
            h = wx.BoxSizer(wx.HORIZONTAL)
            h.Add(wx.StaticText(pnl, label=label_text), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            txt = wx.TextCtrl(pnl, style=wx.TE_PROCESS_ENTER)
            h.Add(txt, 1)
            s.Add(h, 0, wx.EXPAND | wx.ALL, 10)
            if "Başlangıç" in label_text:
                self.txt_start = txt
            else:
                self.txt_end = txt

        h_radio = wx.BoxSizer(wx.HORIZONTAL)
        h_radio.Add(wx.StaticText(pnl, label="Kaydedilecek Radyo:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        radio_names = ["(O an çalan radyo)"] + [r.name for r in self.radios]
        self.choice_radio = wx.Choice(pnl, choices=radio_names)
        self.choice_radio.SetSelection(0)
        h_radio.Add(self.choice_radio, 1, wx.EXPAND)
        s.Add(h_radio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.btn_cancel_timer = wx.Button(pnl, label="Zamanlı Kaydı İptal Et")
        s.Add(self.btn_cancel_timer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(pnl, wx.ID_OK, "Ayarla")
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(pnl, wx.ID_CANCEL, "Vazgeç"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        pnl.SetSizer(s)
        self.txt_start.SetFocus()
        self.btn_cancel_timer.Bind(wx.EVT_BUTTON, self.on_cancel_timer)

    def on_cancel_timer(self, event):
        self.EndModal(wx.ID_DELETE)

    def get_values(self):
        start_str, end_str = self.txt_start.GetValue().strip(), self.txt_end.GetValue().strip()
        start_match = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", start_str)
        end_match = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", end_str)
        if not start_match or not end_match:
            raise ValueError("Saatler SS:DD formatında olmalıdır (örn: 09:05).")

        start_time = datetime.time(int(start_match.group(1)), int(start_match.group(2)))
        end_time = datetime.time(int(end_match.group(1)), int(end_match.group(2)))

        now = datetime.datetime.now()
        start_dt = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        end_dt = now.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)

        if end_dt <= start_dt:
            end_dt += datetime.timedelta(days=1)
        if start_dt <= now:
            start_dt += datetime.timedelta(days=1)
            if end_dt < start_dt:
                end_dt += datetime.timedelta(days=1)

        selected_index = self.choice_radio.GetSelection()
        selected_station = None
        if selected_index > 0:
            selected_station = self.radios[selected_index - 1]

        return start_dt, end_dt, selected_station

class RadioDialog(wx.Dialog):
    def __init__(self, parent, title, name="", url="", ok_label="Ekle"):
        super().__init__(parent, title=title, size=(400, 180))
        s = wx.BoxSizer(wx.VERTICAL)

        for lbl, val in [("Radyo Adı:", name), ("URL:", url)]:
            h = wx.BoxSizer(wx.HORIZONTAL)
            h.Add(wx.StaticText(self, wx.ID_ANY, lbl), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            txt = wx.TextCtrl(self, wx.ID_ANY, value=val, style=wx.TE_PROCESS_ENTER)
            if lbl.startswith("Radyo"):
                self.txt_name = txt
            else:
                self.txt_url = txt
            h.Add(txt, 1)
            s.Add(h, 0, wx.EXPAND | wx.ALL, 10)

        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(self, wx.ID_OK, ok_label)
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL, "İptal"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(s)
        self.txt_name.SetFocus()

    def get_values(self):
        return self.txt_name.GetValue().strip(), self.txt_url.GetValue().strip()

class SearchDialog(wx.Dialog):
    def __init__(self, parent, current_term=""):
        super().__init__(parent, title="Radyo Ara (Filtrele)", size=(380, 180))
        s = wx.BoxSizer(wx.VERTICAL)
        
        info_text = wx.StaticText(self, label="Listeyi daraltmak için aranacak kelimeyi girin.\n(Filtreyi temizlemek için kutuyu boş bırakıp Enter'a basın)")
        s.Add(info_text, 0, wx.EXPAND | wx.ALL, 10)
        
        h = wx.BoxSizer(wx.HORIZONTAL)
        h.Add(wx.StaticText(self, wx.ID_ANY, "Ad Ara:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.txt = wx.TextCtrl(self, wx.ID_ANY, value=current_term, style=wx.TE_PROCESS_ENTER)
        h.Add(self.txt, 1)
        s.Add(h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(self, wx.ID_OK, "Ara")
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL, "İptal"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(s)
        self.txt.SelectAll()
        self.txt.SetFocus()

    def get_term(self):
        return self.txt.GetValue().strip().lower()

class MoveDialog(wx.Dialog):
    def __init__(self, parent, max_index):
        super().__init__(parent, title="Radyoyu Taşı", size=(300, 140))
        s, h = wx.BoxSizer(wx.VERTICAL), wx.BoxSizer(wx.HORIZONTAL)
        h.Add(wx.StaticText(self, wx.ID_ANY, f"Hedef sıra (1–{max_index}):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.txt = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        h.Add(self.txt, 1)
        s.Add(h, 0, wx.EXPAND | wx.ALL, 10)
        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(self, wx.ID_OK, "Taşı")
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL, "İptal"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.SetSizer(s)
        self.txt.SetFocus()

    def get_position(self):
        return int(self.txt.GetValue().strip())

class TimerDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Kapanma Zamanlayıcısı", size=(300, 180))
        pnl = wx.Panel(self)
        s, h = wx.BoxSizer(wx.VERTICAL), wx.BoxSizer(wx.HORIZONTAL)
        h.Add(wx.StaticText(pnl, wx.ID_ANY, "Kapanma Saati (SS:DD):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.txt = wx.TextCtrl(pnl, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        h.Add(self.txt, 1)
        s.Add(h, 0, wx.EXPAND | wx.ALL, 10)
        self.btn_cancel_timer = wx.Button(pnl, label="Zamanlayıcıyı İptal Et")
        s.Add(self.btn_cancel_timer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        btns = wx.StdDialogButtonSizer()
        ok_button = wx.Button(pnl, wx.ID_OK, "Ayarla")
        btns.AddButton(ok_button)
        btns.AddButton(wx.Button(pnl, wx.ID_CANCEL, "Vazgeç"))
        btns.Realize()
        self.SetDefaultItem(ok_button)
        s.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        pnl.SetSizer(s)
        self.txt.SetFocus()
        self.btn_cancel_timer.Bind(wx.EVT_BUTTON, self.on_cancel_timer)

    def on_cancel_timer(self, event):
        self.EndModal(wx.ID_DELETE)

    def get_time(self):
        m = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", self.txt.GetValue().strip())
        if not m:
            raise ValueError("Saat SS:DD formatında olmalı (örn. 09:05)")
        return map(int, m.groups())

class WebSearchDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Web'de Radyo Ara", size=(600, 480))
        
        self.current_page = 0
        self.last_term = ""
        self.last_source = ""
        self.chunk_size = 50
        self.cancel_search = False
        self.fmstream_rate_limited = False
        self.is_closing = False
        self.fmstream_cache = {}
        
        pnl, s = wx.Panel(self), wx.BoxSizer(wx.VERTICAL)

        hs = wx.BoxSizer(wx.HORIZONTAL)
        hs.Add(wx.StaticText(pnl, wx.ID_ANY, "Arama Terimi:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.txt_term = wx.TextCtrl(pnl, wx.ID_ANY, style=wx.TE_PROCESS_ENTER)
        hs.Add(self.txt_term, 1, wx.RIGHT, 8)
        
        self.btn_search = wx.Button(pnl, wx.ID_ANY, "Ara")
        hs.Add(self.btn_search, 0)
        s.Add(hs, 0, wx.EXPAND | wx.ALL, 10)

        self.list = wx.ListCtrl(pnl, wx.ID_ANY, style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL, size=(-1, 300))
        self.list.InsertColumn(0, "Ad", width=400)
        self.list.InsertColumn(1, "Konum/Ülke", width=150)
        s.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        h2 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(pnl, wx.ID_ANY, "Ekle")
        self.btn_add.Hide()
        btn_close = wx.Button(pnl, wx.ID_CANCEL, "Kapat")
        h2.Add(self.btn_add, 0, wx.RIGHT, 10)
        h2.Add(btn_close, 0)
        s.Add(h2, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        pnl.SetSizer(s)
        self.SetDefaultItem(self.btn_search)

        self.btn_search.Bind(wx.EVT_BUTTON, self.on_search)
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self.on_ctx_menu)
        self.list.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self.txt_term.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.Bind(wx.EVT_CLOSE, self.on_close_dialog)
        
        self.txt_term.SetFocus()
        self.stations = []

    def on_close_dialog(self, event):
        self.is_closing = True
        self.cancel_search = True
        event.Skip()

    def _ui_alive(self):
        try:
            return not self.is_closing and bool(self) and not self.IsBeingDeleted()
        except Exception:
            return False

    def _call_after_if_alive(self, func, *args, **kwargs):
        def runner():
            if not self._ui_alive():
                return
            try:
                func(*args, **kwargs)
            except RuntimeError:
                pass
        wx.CallAfter(runner)

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.cancel_search = True
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def on_item_selected(self, event):
        self._update_add_button(event.GetIndex())

    def on_item_deselected(self, event):
        self._update_add_button(-1)

    def _update_add_button(self, idx):
        if not self._ui_alive():
            return
        if idx < 0 or idx >= len(self.stations):
            self.btn_add.Hide()
        else:
            item = self.stations[idx]
            if item.get("type") == "station":
                streams = item.get("streams", [])
                if not streams and item.get("url"):
                    streams = [item.get("url")]
                
                # Sadece tek bir akış varsa "Ekle" butonu görünür.
                if len(streams) == 1:
                    self.btn_add.Show()
                else:
                    self.btn_add.Hide()
            else:
                self.btn_add.Hide()
                
        try:
            self.btn_add.GetParent().Layout()
        except RuntimeError:
            pass

    def on_item_activated(self, event):
        self._handle_action_on_index(event.GetIndex(), from_button=False)

    def on_add(self, event):
        self._handle_action_on_index(self.list.GetFirstSelected(), from_button=True)

    def _handle_action_on_index(self, idx, from_button=False):
        if idx < 0 or idx >= len(self.stations):
            return
        item = self.stations[idx]
        
        if item.get("type") == "next":
            self.current_page += 1
            speak(self.GetParent(), "Daha fazla sonuç yükleniyor...")
            self._trigger_search(is_append=True)
            
        elif item.get("type") == "station":
            streams = item.get("streams", [])
            if not streams and item.get("url"):
                streams = [item.get("url")]
            
            clean_name = item.get("name", "").replace(" [Kayıtlı]", "").strip()
            
            if from_button:
                if len(streams) == 1:
                    self.GetParent().add_radio_station(clean_name, streams[0])
            else:
                if streams:
                    self._open_stream_dialog(clean_name, streams)
                else:
                    speak_or_dialog(self, "Bu radyo için geçerli bir akış adresi bulunamadı.", "Hata", wx.ICON_WARNING)

    def _open_stream_dialog(self, clean_name, streams):
        main_frame = self.GetParent()
        speak(main_frame, f"Önizleme için boşluk, eklemek için enter tuşunu kullanın.")
        with StreamSelectionDialog(self, clean_name, streams, main_frame) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                selected_url = dlg.get_selected_url()
                if selected_url:
                    main_frame.add_radio_station(clean_name, selected_url)

    def on_search(self, e):
        term = self.txt_term.GetValue().strip()
        if not term:
            return
            
        self.current_page = 0
        self.fmstream_cache = {}
        self.last_term = term
        self.last_source = config.get("General", "search_source", fallback="FMStream.org")
        
        speak(self.GetParent(), "Arama başlatılıyor...")
        self._trigger_search(is_append=False)
        
    def _trigger_search(self, is_append=False):
        self.cancel_search = False
        if not self._ui_alive():
            return
        self.btn_search.Disable()
        wx.BeginBusyCursor()
        threading.Thread(target=self._do_search, args=(is_append,), daemon=True).start()

    def _do_search(self, is_append):
        term = self.last_term
        source = self.last_source
        limit = self.chunk_size
        offset = self.current_page * limit
        self.fmstream_rate_limited = False
        
        has_next = False
        raw_stations = []
        filtered_stations = []

        if source == "FMStream.org":
            filtered_stations, has_next = self._search_fmstream_page(term, limit, offset)
            self._call_after_if_alive(self.btn_search.SetLabel, "Ara")

            if not filtered_stations and not getattr(self, "cancel_search", False):
                if getattr(self, "fmstream_rate_limited", False):
                    pass
                elif config.getboolean("General", "fallback_to_radio_browser", fallback=True):
                    logging.debug("FMStream results could not be parsed, Radio-Browser fallback is being used.")
                    raw_stations = self._search_radio_browser(term, limit, offset)
                    filtered_stations = self._finalize_web_stations(raw_stations)
                    has_next = len(filtered_stations) >= limit
                else:
                    logging.debug("FMStream results could not be parsed and Radio-Browser fallback is disabled.")

            self._call_after_if_alive(self._update_list, filtered_stations, has_next, is_append)
            return
        
        if source == "FMStream.org":
            items_fetched = 0
            parsed_count = 0
            while items_fetched < limit:
                if getattr(self, "cancel_search", False):
                    break
                
                self._call_after_if_alive(self.btn_search.SetLabel, f"Çekiliyor ({offset + items_fetched})...")
                
                batch, parsed_count = self._search_fmstream_raw(term, 50, offset + items_fetched)
                if not batch and parsed_count == 0:
                    break
                    
                raw_stations.extend(batch)
                items_fetched += 50
                
                if parsed_count < 50:
                    break

                time.sleep(0.35)
            
            self._call_after_if_alive(self.btn_search.SetLabel, "Ara")
            if items_fetched >= limit and parsed_count == 50:
                has_next = True

            # FMStream'in HTML/JS yapısı zaman zaman değişiyor.
            # Eski ayrıştırıcı geçici olarak sonuç çıkaramazsa kullanıcıya boş ekran
            # göstermemek için Radio-Browser ile otomatik geri dönüş yap.
            if not raw_stations and not getattr(self, "cancel_search", False):
                if getattr(self, "fmstream_rate_limited", False):
                    logging.info("FMStream hız sınırına takıldı, bu denemede ayrıştırma geri dönüşü uygulanmadı.")
                elif config.getboolean("General", "fallback_to_radio_browser", fallback=True):
                    logging.info("FMStream sonuçları ayrıştırılamadı, Radio-Browser geri dönüşü kullanılıyor.")
                    raw_stations = self._search_radio_browser(term, limit, offset)
                    has_next = len(raw_stations) >= limit
                else:
                    logging.info("FMStream sonuçları ayrıştırılamadı, Radio-Browser geri dönüşü kapalı.")
        else:
            # Radio Browser Smart Search (Name fallback to Country)
            raw_stations = self._search_radio_browser(term, limit, offset)
            if len(raw_stations) >= limit:
                has_next = True

        filtered_stations = []
        if config.getboolean("General", "filter_web_duplicates", fallback=True) and raw_stations:
            seen_names = set()
            for st in raw_stations:
                name = st.get("name", "").strip().lower()
                if name and name not in seen_names:
                    st["streams"] = st.get("streams", [st.get("url")])
                    filtered_stations.append(st)
                    seen_names.add(name)
        else:
            for st in raw_stations:
                st["streams"] = st.get("streams", [st.get("url")])
            filtered_stations = raw_stations
            
        self._call_after_if_alive(self._update_list, filtered_stations, has_next, is_append)

    def _finalize_web_stations(self, raw_stations):
        if not raw_stations:
            return []

        filtered_stations = []
        if config.getboolean("General", "filter_web_duplicates", fallback=True):
            seen_names = set()
            for st in raw_stations:
                name = st.get("name", "").strip().lower()
                if name and name not in seen_names:
                    st["streams"] = st.get("streams", [st.get("url")])
                    filtered_stations.append(st)
                    seen_names.add(name)
        else:
            for st in raw_stations:
                st["streams"] = st.get("streams", [st.get("url")])
                filtered_stations.append(st)

        return filtered_stations

    def _search_fmstream_page(self, term, limit, offset):
        batch_size = 50
        use_unique_fill = config.getboolean("General", "filter_web_duplicates", fallback=True)
        target_count = (offset + limit + 1) if use_unique_fill else (limit + 1)
        cache_key = (term, use_unique_fill)
        cache = self.fmstream_cache.get(cache_key)
        if cache is None:
            cache = {"raw_stations": [], "next_offset": 0, "exhausted": False, "last_batch_full": False}
            self.fmstream_cache[cache_key] = cache

        while len(self._finalize_web_stations(cache["raw_stations"])) < target_count and not cache["exhausted"]:
            if getattr(self, "cancel_search", False):
                break

            raw_offset = cache["next_offset"]
            self._call_after_if_alive(self.btn_search.SetLabel, f"Çekiliyor ({raw_offset})...")
            batch, parsed_count = self._search_fmstream_raw(term, batch_size, raw_offset)
            if not batch and parsed_count == 0:
                if not self.fmstream_rate_limited:
                    cache["exhausted"] = True
                break

            cache["raw_stations"].extend(batch)
            cache["last_batch_full"] = parsed_count == batch_size
            if parsed_count < batch_size:
                cache["exhausted"] = True
                break

            cache["next_offset"] += batch_size
            time.sleep(0.35)

        finalized = self._finalize_web_stations(cache["raw_stations"])
        if not use_unique_fill:
            has_next = len(finalized) > limit or cache["last_batch_full"] or self.fmstream_rate_limited
            return finalized[offset:offset + limit], has_next

        page_items = finalized[offset:offset + limit]
        has_next = len(finalized) > (offset + limit) or cache["last_batch_full"] or self.fmstream_rate_limited
        return page_items, has_next

    def _search_radio_browser(self, term, limit, offset):
        base = API_BASE_URL.rstrip("/")
        params = {"limit": limit, "offset": offset, "hidebroken": "true"}
        
        try:
            r = requests.get(f"{base}/byname/{term}", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            
            if not data and offset == 0:
                r = requests.get(f"{base}/bycountry/{term}", params=params, timeout=10)
                r.raise_for_status()
                data = r.json()
                
            return data
        except Exception as exc:
            logging.error(f"Radio-Browser arama hatası: {exc}")
            return []

    def _fmstream_request(self, method, url, **kwargs):
        headers = kwargs.pop("headers", {})
        merged_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"}
        merged_headers.update(headers)
        timeout = kwargs.pop("timeout", 15)

        last_exc = None
        for attempt in range(3):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=merged_headers,
                    timeout=timeout,
                    proxies={"http": None, "https": None},
                    **kwargs,
                )
                if response.status_code == 429:
                    self.fmstream_rate_limited = True
                    retry_after = response.headers.get("Retry-After", "").strip()
                    wait_seconds = int(retry_after) if retry_after.isdigit() else (2 + attempt * 2)
                    wait_seconds = max(2, min(wait_seconds, 10))
                    logging.debug(f"FMStream hız sınırı uyguladı, {wait_seconds} saniye sonra tekrar denenecek.")
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                break

        if last_exc:
            raise last_exc
        raise RuntimeError("FMStream isteği başarısız oldu.")

    def _search_fmstream_raw(self, term, limit, offset):
        base_url = f"https://fmstream.org/index.php?s={urllib.parse.quote(term)}&n={offset}"
        stations = []
        parsed_count = 0
        try:
            response = self._fmstream_request("GET", base_url)
            html = response.text
            stations, parsed_count = self._search_fmstream_modern(html, limit)
        except Exception as e:
            if self.fmstream_rate_limited:
                logging.debug(f"FMStream arama isteği geçici olarak başarısız oldu: {e}")
            else:
                logging.error(f"FMStream arama hatası: {e}")
        return stations, parsed_count

    def _search_fmstream_modern(self, page_html, limit):
        fetch_ids_match = re.search(r'const\s+fetchIds\s*=\s*"([^"]*)"', page_html, re.IGNORECASE)
        fetch_ids = [x.strip() for x in (fetch_ids_match.group(1).split(",") if fetch_ids_match else []) if x.strip()]
        parsed_count = len(fetch_ids)
        if not fetch_ids:
            return [], 0

        stations = self._fetch_fmstream_stations_by_ids(fetch_ids[:limit])
        if stations:
            return stations, parsed_count

        cards = self._extract_fmstream_station_cards(page_html)
        for card in cards[:limit]:
            detail = self._fetch_fmstream_station_detail(card)
            if detail:
                stations.append(detail)

        return stations, parsed_count or len(cards)

    def _fetch_fmstream_stations_by_ids(self, station_ids):
        if not station_ids:
            return []

        try:
            response = self._fmstream_request(
                "POST",
                "https://fmstream.org/stations2.php",
                data={"ids": ",".join(station_ids), "app": "fmstream"},
            )
            rows = response.json()
        except Exception as exc:
            logging.debug(f"FMStream stations2 arama hatası: {exc}")
            return []

        stations = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 3:
                continue

            name = str(row[1]).strip() if len(row) > 1 and row[1] else "Bilinmiyor"
            location_parts = []
            if len(row) > 3 and row[3]:
                location_parts.append(str(row[3]).strip())
            if len(row) > 5 and row[5]:
                location_parts.append(str(row[5]).strip())
            country = ", ".join([part for part in location_parts if part])

            streams = []
            raw_urls = row[2] if isinstance(row[2], list) else []
            for item in raw_urls:
                raw_url = item[0] if isinstance(item, list) and item else item
                clean = self._sanitize_url(raw_url)
                if not clean or self._is_obviously_non_stream(clean):
                    continue
                if clean not in streams:
                    streams.append(clean)

            if streams:
                stations.append({
                    "name": name,
                    "country": country,
                    "url": streams[0],
                    "streams": streams,
                })

        return stations

    def _extract_fmstream_station_cards(self, page_html):
        cards = []
        seen = set()
        pattern = re.compile(
            r'<h3[^>]*>\s*<a[^>]+href="(?P<href>[^"]+?-live[^"]*)"[^>]*>(?P<name>.*?)</a>\s*</h3>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in pattern.finditer(page_html):
            href = html.unescape(match.group("href")).strip()
            name = self._html_to_text(match.group("name"))
            if not href or not name:
                continue

            detail_url = urllib.parse.urljoin("https://fmstream.org/", href)
            if detail_url in seen:
                continue
            seen.add(detail_url)

            tail = page_html[match.end():match.end() + 800]
            cards.append({
                "name": name,
                "country": self._extract_fmstream_location(tail),
                "detail_url": detail_url,
            })

        fallback_pattern = re.compile(
            r'<a[^>]+href="(?P<href>[^"]+?-live[^"]*)"[^>]*>(?P<label>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in fallback_pattern.finditer(page_html):
            href = html.unescape(match.group("href")).strip()
            detail_url = urllib.parse.urljoin("https://fmstream.org/", href)
            if not href or detail_url in seen:
                continue

            name = self._html_to_text(match.group("label"))
            if not name or name.lower() in ("about", "info"):
                continue

            seen.add(detail_url)
            tail = page_html[match.end():match.end() + 800]
            cards.append({
                "name": name,
                "country": self._extract_fmstream_location(tail),
                "detail_url": detail_url,
            })

        return cards

    def _extract_fmstream_location(self, snippet):
        text = self._html_to_text(snippet)
        if not text:
            return ""

        parts = [p.strip() for p in re.split(r"[|\n\r]+", text) if p.strip()]
        for part in parts:
            if len(part) > 120:
                continue
            if "This site only works with JAVASCRIPT" in part:
                continue
            return part
        return ""

    def _fetch_fmstream_station_detail(self, card):
        detail_url = card.get("detail_url")
        if not detail_url:
            return None

        try:
            req = urllib.request.Request(
                detail_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                detail_html = response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logging.debug(f"FMStream detay sayfası okunamadı: {detail_url} - {exc}")
            return None

        streams = []
        for raw in self._extract_url_candidates_from_html(detail_html):
            clean = self._sanitize_url(raw)
            if not clean or self._is_obviously_non_stream(clean):
                continue
            if clean not in streams:
                streams.append(clean)

        if not streams:
            return None

        return {
            "name": card.get("name", "Bilinmiyor"),
            "country": card.get("country", ""),
            "url": streams[0],
            "streams": streams,
        }

    def _extract_url_candidates_from_html(self, page_html):
        candidates = []
        seen = set()

        for candidate in self._pick_url_candidates(self._extract_js_string_literals(page_html)):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        for match in re.finditer(r'https?://[^\s"\'<>\\]+', page_html, re.IGNORECASE):
            candidate = match.group(0).strip()
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        attr_pattern = re.compile(
            r'(?:href|src|data-[a-z0-9_-]+)\s*=\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for match in attr_pattern.finditer(page_html):
            candidate = html.unescape(match.group(1).strip())
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        return candidates

    def _html_to_text(self, value):
        if not value:
            return ""
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _sanitize_url(self, raw_link):
        try:
            if raw_link is None: return None
            s = str(raw_link)
            s = re.sub(r"[\x00-\x1F\x7F]", "", s).strip()
            s = s.replace("\\/", "/").replace(r"\/", "/").strip()
            s = s.strip(" \t\r\n[](){}<>\"'")
            if not s: return None
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", s):
                if s.startswith("//"): s = "http:" + s
                else: s = "http://" + s
            u = urllib.parse.urlsplit(s)
            scheme = (u.scheme or "").lower()
            if scheme not in ("http", "https"): return None
            if not u.netloc: return None
            netloc = u.netloc.strip(" \t\r\n\"'")
            cleaned = urllib.parse.urlunsplit((scheme, netloc, u.path or "", u.query or "", u.fragment or ""))
            if " " in cleaned: cleaned = cleaned.replace(" ", "%20")
            return cleaned
        except Exception:
            return None

    def _is_obviously_non_stream(self, url):
        try:
            u = urllib.parse.urlsplit(url)
            host = (u.netloc or "").lower()
            path = (u.path or "").lower()
            query = (u.query or "").lower()

            if "fmstream.org" in host:
                if path in ("", "/") or "index.php" in path:
                    return True
                if path.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".htm", ".html", ".php")):
                    return True

            if "cdn.jsdelivr.net" in host or "cdn.dashjs.org" in host:
                return True

            hints = ("stream", "listen", "live", "radio", "icecast", "shoutcast", "mount", "audio", "hls", "playlist", "mp3", "aac", "ogg", "opus", "m3u")
            has_hint = any(h in host for h in hints) or any(h in path for h in hints) or any(h in query for h in hints)
            audio_exts = (".mp3", ".aac", ".aacp", ".ogg", ".opus", ".flac", ".m3u", ".m3u8", ".pls")
            has_audio_ext = any(path.endswith(ext) for ext in audio_exts)

            web_page_exts = (".html", ".htm", ".php", ".asp", ".aspx", ".jsp")
            if any(path.endswith(ext) for ext in web_page_exts) and not (has_hint or has_audio_ext):
                return True

            bad_hosts = ("youtube.com", "youtu.be", "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "telegram.me", "t.me")
            if any(bh in host for bh in bad_hosts) and not (has_hint or has_audio_ext):
                return True
            return False
        except Exception:
            return False

    def _iter_js_entries(self, js_content):
        entries = []
        depth = 0
        in_str = None
        escape = False
        start = None
        for i, ch in enumerate(js_content):
            if in_str:
                if escape: escape = False; continue
                if ch == "\\": escape = True; continue
                if ch == in_str: in_str = None
                continue
            if ch in ("'", '"'):
                in_str = ch
                continue
            if ch == "[":
                if depth == 0: start = i + 1
                depth += 1
                continue
            if ch == "]":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        entries.append(js_content[start:i])
                        start = None
                continue
        return entries

    def _extract_js_string_literals(self, entry):
        out = []
        pattern = re.compile(r"""(['"])(?:\\.|(?!\1).)*\1""", re.DOTALL)
        for m in pattern.finditer(entry):
            s = m.group(0)
            if len(s) < 2: continue
            s = s[1:-1]
            s = s.replace("\\/", "/").replace("\\\\", "\\").replace("\\'", "'").replace('\\"', '"')
            s = re.sub(r"\\u00([0-9a-fA-F]{2})", lambda x: chr(int(x.group(1), 16)), s)
            s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda x: chr(int(x.group(1), 16)), s)
            s = html.unescape(s).strip()
            if s: out.append(s)
        return out

    def _pick_url_candidates(self, strings):
        bad_schemes = ("javascript:", "data:", "file:", "vbscript:")
        candidates = []
        for s in strings:
            if not s: continue
            ss = s.strip()
            if not ss: continue
            low = ss.lower()
            if low.startswith(bad_schemes): continue
            if "." in ss or "/" in ss:
                candidates.append(ss)
        return candidates

    def _update_list(self, stations, has_next, is_append):
        if not self._ui_alive():
            return
        if wx.IsBusy():
            wx.EndBusyCursor()
        try:
            self.btn_search.Enable()
        except RuntimeError:
            return
        
        main_frame = self.GetParent()
        saved_names = {normalize_radio_name(r.name) for r in main_frame.radios}

        if is_append:
            if self.stations and self.stations[-1].get("type") == "next":
                self.list.DeleteItem(self.list.GetItemCount() - 1)
                self.stations.pop()
        else:
            self.list.DeleteAllItems()
            self.stations = []

        start_index = self.list.GetItemCount()
        count = 0
        
        for st in stations:
            original_name = st.get("name", "").strip()
            display_name = original_name
            
            if normalize_radio_name(original_name) in saved_names:
                display_name = f"{original_name} [Kayıtlı]"

            list_index = self.list.InsertItem(self.list.GetItemCount(), display_name)
            location = st.get("state", "") or st.get("country", "")
            self.list.SetItem(list_index, 1, location)
            
            st_copy = st.copy()
            st_copy["name"] = original_name
            st_copy["type"] = "station"
            self.stations.append(st_copy)
            count += 1

        if has_next:
            idx = self.list.InsertItem(self.list.GetItemCount(), "Daha Fazla Sonuç Getir")
            self.list.SetItem(idx, 1, "")
            self.stations.append({"type": "next"})

        if count > 0:
            if is_append:
                speak(self.GetParent(), f"{count} yeni sonuç eklendi.")
                self.list.SetFocus()
                self.list.Select(start_index)
                self.list.EnsureVisible(start_index)
            else:
                speak(self.GetParent(), f"Arama tamamlandı. {count} sonuç listelendi.")
                self.list.SetFocus()
                self.list.Select(0)
            self._update_add_button(self.list.GetFirstSelected())
        elif not is_append:
            if getattr(self, "fmstream_rate_limited", False):
                speak(self.GetParent(), "FMStream geçici olarak çok fazla istek hatası verdi. Birkaç saniye sonra tekrar deneyin.")
            else:
                speak(self.GetParent(), "Arama tamamlandı. Sonuç bulunamadı.")
            self.txt_term.SetFocus()
            self._update_add_button(-1)
        else:
            if getattr(self, "fmstream_rate_limited", False):
                speak(self.GetParent(), "FMStream hız sınırına takıldı. Birkaç saniye bekleyip tekrar deneyin.")
            elif has_next:
                speak(self.GetParent(), "Yeni sonuçlar hazır değil. Biraz sonra tekrar deneyin.")
            else:
                speak(self.GetParent(), "Daha fazla sonuç bulunamadı.")
            self.list.SetFocus()

    def on_ctx_menu(self, event):
        screen_pos = event.GetPosition()
        client_pos = self.list.ScreenToClient(screen_pos)
        idx, flags = self.list.HitTest(client_pos)

        if idx == wx.NOT_FOUND:
            idx = self.list.GetFirstSelected()
            if idx == wx.NOT_FOUND:
                return
                
        if self.stations[idx].get("type") != "station":
            return

        menu = wx.Menu()
        mi = menu.Append(wx.ID_ANY, "Akış Adresini Kopyala")

        def on_copy(evt):
            u = self.stations[idx].get("url", "")
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(u))
                wx.TheClipboard.Close()
                speak(self.GetParent(), "Akış adresi kopyalandı.")

        self.Bind(wx.EVT_MENU, on_copy, mi)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_list_key(self, event):
        key = event.GetKeyCode()
        if (key == wx.WXK_F10 and event.ShiftDown()) or key == wx.WXK_MENU:
            idx = self.list.GetFirstSelected()
            if idx < 0 and self.list.GetItemCount() > 0:
                idx = 0
                self.list.Select(0)

            if idx >= 0:
                if self.stations[idx].get("type") == "station":
                    rect = self.list.GetItemRect(idx)
                    screen_pt = self.list.ClientToScreen(
                        (rect.x + rect.width // 2, rect.y + rect.height // 2)
                    )
                    evt = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, self.list.GetId(), screen_pt)
                    self.on_ctx_menu(evt)
        else:
            event.Skip()


class ShortcutsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Klavye Kısayolları", size=(480, 580))
        pnl = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        shortcuts_data = [
            ("Oynat / Duraklat (Canlı Yayın)", "Space"),
            ("Ses Artır", "Sağ Ok"),
            ("Ses Azalt", "Sol Ok"),
            ("Kayıtta İleri Alma (Kayıtları Yönet)", "Sağ Ok"),
            ("Kayıtta Geri Alma (Kayıtları Yönet)", "Sol Ok"),
            ("Listede Yukarı/Aşağı Taşı", "Sağ Tık Menüsü"),
            ("Listeyi Sırala", "Sağ Tık Menüsü"),
            ("Yeni Radyo Ekle", "Ctrl+N"),
            ("Radyoyu Düzenle", "F2"),
            ("Radyo Ara (Filtrele)", "F3"),
            ("Arama Filtresini Temizle", "Esc"),
            ("Web'de Radyo Ara", "F4"),
            ("Radyoyu Sil", "Delete"),
            ("Tüm Radyoları Sil", "Shift+Delete"),
            ("Radyo Taşı (Belirli Sıraya)", "Ctrl+M"),
            ("Yeni Favori Listesi", "Ctrl+Shift+N"),
            ("Favori Listelerini Yönet", "Ctrl+Shift+M"),
            ("Normal Kayıt Başlat", "Ctrl+R"),
            ("Herhangi bir Kaydı Durdur", "Shift+R"),
            ("Zamanlı Kayıt Ayarla", "Ctrl+Shift+R"),
            ("Ayarlar", "Ctrl+P"),
            ("Kapanma Zamanlayıcısı", "Ctrl+T"),
            ("Sistem Tepsisine Küçült", "Alt+Ctrl+M"),
            ("Kayıtları Yönet", "Ctrl+L"),
            ("Klavye Kısayolları", "Shift+F1"),
            ("Program Hakkında", "F1"),
            ("Yardım (HTML)", "Ctrl+Shift+F1"),
            ("İletişim", "Ctrl+I"),
            ("Çıkış", "Ctrl+Q"),
        ]

        self.list_ctrl = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "İşlev", width=280)
        self.list_ctrl.InsertColumn(1, "Kısayol", width=150)

        for func, key in shortcuts_data:
            index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), func)
            self.list_ctrl.SetItem(index, 1, key)

        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        close_button = wx.Button(pnl, wx.ID_CANCEL, "Kapat")
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(close_button)
        btn_sizer.AddStretchSpacer()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)

        pnl.SetSizer(sizer)
        self.Centre()


class ManageRecordingsDialog(wx.Dialog):
    def __init__(self, parent, record_dir):
        super().__init__(parent, title="Kayıtları Yönet", size=(650, 420))
        self.parent = parent
        self.record_dir = record_dir
        self.files = []

        pnl = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        main_sizer.Add(wx.StaticText(pnl, label="Kayıtlar:"), 0, wx.ALL, 10)

        self.list = wx.ListCtrl(pnl, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list.InsertColumn(0, "Dosya Adı", width=380)
        self.list.InsertColumn(1, "Tarih", width=220)
        main_sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play = wx.Button(pnl, wx.ID_ANY, "Oynat / Duraklat (Boşluk)")
        self.btn_delete = wx.Button(pnl, wx.ID_ANY, "Seçili Kaydı Sil (Del)")
        self.btn_open_folder = wx.Button(pnl, wx.ID_ANY, "Klasörü Aç")
        btn_close = wx.Button(pnl, wx.ID_CANCEL, "Kapat")

        btn_sizer.Add(self.btn_play, 0, wx.RIGHT, 5)
        btn_sizer.Add(self.btn_delete, 0, wx.RIGHT, 5)
        btn_sizer.Add(self.btn_open_folder, 0, wx.RIGHT, 5)
        btn_sizer.Add(btn_close, 0)

        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        pnl.SetSizer(main_sizer)

        self.btn_play.Bind(wx.EVT_BUTTON, self.on_play)
        self.btn_delete.Bind(wx.EVT_BUTTON, self.on_delete)
        self.btn_open_folder.Bind(wx.EVT_BUTTON, self.on_open_folder)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_play)
        self.list.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)

        self.refresh_files()
        if self.list.GetItemCount() > 0:
            self.list.Select(0)
            self.list.Focus(0)

    def refresh_files(self):
        self.list.DeleteAllItems()
        self.files = []

        if not os.path.isdir(self.record_dir):
            return

        all_files = []
        for name in os.listdir(self.record_dir):
            if name.lower().endswith((".mp3", ".wav")):
                full_path = os.path.join(self.record_dir, name)
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    continue
                all_files.append((full_path, mtime))

        all_files.sort(key=lambda x: x[1], reverse=True)

        for full_path, mtime in all_files:
            fname = os.path.basename(full_path)
            dt = datetime.datetime.fromtimestamp(mtime)
            idx = self.list.InsertItem(self.list.GetItemCount(), fname)
            self.list.SetItem(idx, 1, dt.strftime("%Y-%m-%d %H:%M"))
            self.files.append(full_path)

    def _get_selected_file(self):
        idx = self.list.GetFirstSelected()
        if idx < 0 or idx >= len(self.files):
            return None
        return self.files[idx]

    def on_play(self, event):
        path = self._get_selected_file()
        if not path:
            return
        self.parent.play_recording_file(path, toggle=True)

    def on_delete(self, event):
        path = self._get_selected_file()
        if not path:
            return

        fname = os.path.basename(path)
        with wx.MessageDialog(
            self,
            f"'{fname}' kaydını kalıcı olarak silmek istediğinizden emin misiniz?",
            "Kayıt Silme Onayı",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return

        try:
            if getattr(self.parent, "current_record_path", None) and \
               os.path.normpath(self.parent.current_record_path) == os.path.normpath(path):
                self.parent.stop_recording_playback()

            if os.path.exists(path):
                os.remove(path)
            speak(self.parent, f"'{fname}' kaydı silindi.")
        except Exception as e:
            logging.error(f"Kayıt silinirken hata: {e}")
            speak_or_dialog(self, "Kayıt silinirken bir hata oluştu.", "Hata", wx.ICON_ERROR)

        self.refresh_files()

    def on_open_folder(self, event):
        try:
            if not os.path.isdir(self.record_dir):
                speak_or_dialog(self, "Kayıt klasörü mevcut değil.", "Hata", wx.ICON_ERROR)
                return
            os.startfile(self.record_dir)
        except Exception as e:
            logging.error(f"Klasör açılırken hata: {e}")
            speak_or_dialog(self, "Kayıt klasörü açılamadı.", "Hata", wx.ICON_ERROR)

    def on_rename(self, event):
        path = self._get_selected_file()
        if not path:
            return

        fname = os.path.basename(path)
        base, ext = os.path.splitext(fname)

        with wx.TextEntryDialog(
            self,
            "Yeni dosya adını girin:",
            "Kaydı Yeniden Adlandır",
            value=base,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_base = dlg.GetValue().strip()
            if not new_base:
                speak_or_dialog(self, "Geçerli bir ad girin.", "Uyarı", wx.ICON_WARNING)
                return
            new_base = re.sub(r'[\\/*?:"<>|]', "", new_base)
            new_path = os.path.join(self.record_dir, new_base + ext)
            if os.path.normpath(new_path) == os.path.normpath(path):
                return
            if os.path.exists(new_path):
                speak_or_dialog(self, "Bu isimde bir kayıt zaten var.", "Uyarı", wx.ICON_WARNING)
                return

            try:
                os.rename(path, new_path)
                if getattr(self.parent, "current_record_path", None) and \
                   os.path.normpath(self.parent.current_record_path) == os.path.normpath(path):
                    self.parent.current_record_path = new_path
                speak(self.parent, "Kayıt yeniden adlandırıldı.")
            except Exception as e:
                logging.error(f"Kayıt yeniden adlandırılamadı: {e}")
                speak_or_dialog(self, "Kayıt yeniden adlandırılırken hata oluştu.", "Hata", wx.ICON_ERROR)

        self.refresh_files()
        for i, f in enumerate(self.files):
            if os.path.normpath(f) == os.path.normpath(new_path):
                self.list.Select(i)
                self.list.Focus(i)
                self.list.EnsureVisible(i)
                break

    def on_context_menu(self, event):
        if self.list.GetItemCount() == 0:
            return

        idx = self.list.GetFirstSelected()
        if idx < 0:
            idx = 0
            self.list.Select(0)

        menu = wx.Menu()
        mi_play = menu.Append(wx.ID_ANY, "Oynat / Duraklat")
        mi_rename = menu.Append(wx.ID_ANY, "Yeniden Adlandır...")
        mi_delete = menu.Append(wx.ID_ANY, "Sil")

        self.Bind(wx.EVT_MENU, self.on_play, mi_play)
        self.Bind(wx.EVT_MENU, self.on_rename, mi_rename)
        self.Bind(wx.EVT_MENU, self.on_delete, mi_delete)

        self.PopupMenu(menu)
        menu.Destroy()

    def on_list_key(self, event):
        key = event.GetKeyCode()
        ctrl = event.ControlDown()
        sh = event.ShiftDown()
        alt = event.AltDown()

        if key == wx.WXK_SPACE and not ctrl and not sh and not alt:
            self.on_play(event)
        elif key == wx.WXK_DELETE and not ctrl and not sh and not alt:
            self.on_delete(event)
        elif key == wx.WXK_F2 and not ctrl and not sh and not alt:
            self.on_rename(event)
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT) and not ctrl and not sh and not alt:
            delta = self.parent.record_seek_seconds if key == wx.WXK_RIGHT else -self.parent.record_seek_seconds
            self.parent.seek_recording(delta)
        elif ctrl and not sh and not alt and key == wx.WXK_RIGHT:
            self.parent.seek_recording(self.parent.record_seek_seconds)
        elif ctrl and not sh and not alt and key == wx.WXK_LEFT:
            self.parent.seek_recording(-self.parent.record_seek_seconds)
        else:
            event.Skip()


class TrayIcon(TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.SetIcon(self.create_icon(), "Basit Radyo")
        self.ID_RESTORE, self.ID_EXIT = wx.NewIdRef(), wx.NewIdRef()

        self.Bind(wx.EVT_MENU, self.on_restore, id=self.ID_RESTORE)
        self.Bind(wx.EVT_MENU, self.on_exit, id=self.ID_EXIT)
        self.Bind(EVT_TASKBAR_LEFT_DCLICK, self.on_restore)

    def create_icon(self):
        xpm_data_str = [
            "16 16 3 1",
            "B c #0000FF",
            "W c #FFFFFF",
            ". c None",
            "................",
            "................",
            ".......BB.......",
            "......B..B......",
            ".....B....B.....",
            "....B.WWWW.B....",
            "...B..WWWW..B...",
            "..B...WWWW...B..",
            ".B....WWWW....B.",
            "B.....WWWW.....B",
            "B.....WWWW.....B",
            ".B....BBBB....B.",
            "..B..........B..",
            "...BBBBBBBBBB...",
            "................",
            "................",
        ]
        xpm_data_bytes = [s.encode("utf-8") for s in xpm_data_str]
        return wx.Icon(wx.Bitmap(xpm_data_bytes))

    def update_tooltip(self, text):
        tooltip = text or "Basit Radyo"
        self.SetIcon(self.create_icon(), tooltip)

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(self.ID_RESTORE, "Geri Yükle")
        menu.AppendSeparator()
        menu.Append(self.ID_EXIT, "Çıkış")
        return menu

    def on_restore(self, event):
        self.frame.Show()
        self.frame.Restore()
        self.frame.Raise()
        speak(self.frame, "Pencere geri yüklendi.")
        self.frame.tray_icon = None
        self.Destroy()

    def on_exit(self, event):
        self.frame.Close()


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Basit Radyo", size=(600, 700))
        pnl = wx.Panel(self)
        self.CreateStatusBar()

        self.accessibility_enabled = config.getboolean("General", "accessibility")
        self.show_now_playing_in_list = config.getboolean(
            "General", "show_now_playing_in_list", fallback=False
        )
        self.record_seek_seconds = config.getint("General", "record_seek_seconds", fallback=5)

        self.tray_icon = None
        self.current_list_name = ""
        self.current_stream_title = ""
        self.current_search_term = ""
        self.play_request_id = 0
        self.is_connecting_stream = False
        self.is_shutting_down = False

        self.menu_ids = {
            "NEW": wx.NewIdRef(),
            "NEW_FAV_LIST": wx.NewIdRef(),
            "TIMER": wx.NewIdRef(),
            "SETTINGS": wx.NewIdRef(),
            "EXIT": wx.ID_EXIT,
            "SEARCH": wx.NewIdRef(),
            "EDIT": wx.NewIdRef(),
            "MOVE": wx.NewIdRef(),
            "DELETE": wx.NewIdRef(),
            "DELALL": wx.NewIdRef(),
            "WEB": wx.NewIdRef(),
            "RECORD": wx.NewIdRef(),
            "TIMED_RECORD": wx.NewIdRef(),
            "ABOUT": wx.NewIdRef(),
            "CTX_PLAY_PAUSE": wx.NewIdRef(),
            "CTX_MOVE_UP": wx.NewIdRef(),
            "CTX_MOVE_DOWN": wx.NewIdRef(),
            "CTX_SORT_NAME": wx.NewIdRef(),
            "CTX_SORT_DATE_ASC": wx.NewIdRef(),
            "CTX_SORT_DATE_DESC": wx.NewIdRef(),
            "SHORTCUTS": wx.NewIdRef(),
            "CONTACT": wx.NewIdRef(),
            "MINIMIZE_TRAY": wx.NewIdRef(),
            "MANAGE_FAVORITES": wx.NewIdRef(),
            "MANAGE_RECORDINGS": wx.NewIdRef(),
            "HELP_HTML": wx.NewIdRef(),
            "CHECK_UPDATES": wx.NewIdRef(),
        }

        fm = wx.Menu()
        fm.Append(self.menu_ids["NEW"], "Yeni Radyo Ekle\tCtrl+N")
        fm.Append(self.menu_ids["NEW_FAV_LIST"], "Yeni Favori Listesi Oluştur...\tCtrl+Shift+N")
        fm.Append(self.menu_ids["TIMER"], "Kapanma Zamanlayıcısı...\tCtrl+T")
        fm.Append(self.menu_ids["SETTINGS"], "Ayarlar...\tCtrl+P")
        fm.AppendSeparator()
        fm.Append(self.menu_ids["MINIMIZE_TRAY"], "Sistem Tepsisine Küçült\tAlt+Ctrl+M")
        fm.AppendSeparator()
        fm.Append(self.menu_ids["EXIT"], "Çıkış\tCtrl+Q")

        om = wx.Menu()
        om.Append(self.menu_ids["SEARCH"], "Radyo Ara (Filtrele)\tF3")
        om.Append(self.menu_ids["EDIT"], "Düzenle\tF2")
        om.Append(self.menu_ids["MOVE"], "Taşı\tCtrl+M")
        om.AppendSeparator()
        om.Append(self.menu_ids["DELETE"], "Sil\tDel")
        om.Append(self.menu_ids["DELALL"], "Tümünü Sil\tShift+Del")
        om.AppendSeparator()
        om.Append(self.menu_ids["MANAGE_FAVORITES"], "Favori Listelerini Yönet...\tCtrl+Shift+M")
        om.AppendSeparator()
        om.Append(self.menu_ids["WEB"], "Web'de Ara\tF4")

        rm = wx.Menu()
        self.record_menu_item = rm.Append(self.menu_ids["RECORD"], "Normal Kayıt\tCtrl+R")
        rm.Append(self.menu_ids["TIMED_RECORD"], "Zamanlı Kayıt...\tCtrl+Shift+R")
        rm.Append(self.menu_ids["MANAGE_RECORDINGS"], "Kayıtları Yönet...\tCtrl+L")

        hm = wx.Menu()
        hm.Append(self.menu_ids["ABOUT"], "Hakkında\tF1")
        hm.Append(self.menu_ids["SHORTCUTS"], "Klavye Kısayolları\tShift+F1")
        hm.Append(self.menu_ids["HELP_HTML"], "Yardım (HTML)\tCtrl+Shift+F1")
        hm.Append(self.menu_ids["CHECK_UPDATES"], "Güncellemeleri Kontrol Et")
        hm.AppendSeparator()
        hm.Append(self.menu_ids["CONTACT"], "İletişim\tCtrl+I")

        mb = wx.MenuBar()
        mb.Append(fm, "Dosya")
        mb.Append(om, "Radyo İşlemleri")
        mb.Append(rm, "Kayıt İşlemleri")
        mb.Append(hm, "Yardım")
        self.SetMenuBar(mb)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        h_sizer.Add(wx.StaticText(pnl, label="Gösterilen Liste:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.combo_lists = wx.ComboBox(pnl, style=wx.CB_READONLY)
        h_sizer.Add(self.combo_lists, 1, wx.EXPAND)
        main_sizer.Add(h_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.list_ctrl = wx.ListCtrl(pnl, wx.ID_ANY, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "Radyo Adı", width=560)
        main_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        pnl.SetSizer(main_sizer)

        self.radios = []
        self.favorites = {}
        self.current_stream = ctypes.c_uint(0)
        self.current_index = None
        self.volume = 50

        self.is_recording = False
        self.recording_process = None
        self.current_wav_path = None

        self.shutdown_timer = wx.Timer(self)
        self.timed_record_timer = wx.Timer(self)
        self.timed_record_start = None
        self.timed_record_end = None
        self.timed_record_station = None

        self.meta_timer = wx.Timer(self)
        self.record_play_stream = ctypes.c_uint(0)
        self.current_record_path = None

        self.bind_events()
        self.load_favorites()
        self.load_playlist()
        self.apply_saved_sort()
        self.update_favorites_combo()

        default_list = config.get("General", "default_list", fallback="Tüm Radyolar")
        if self.combo_lists.FindString(default_list) != wx.NOT_FOUND:
            self.combo_lists.SetValue(default_list)
        else:
            self.combo_lists.SetValue("Tüm Radyolar")

        self.current_list_name = self.combo_lists.GetValue()
        self.refresh_list_ctrl(self.current_list_name)

        self.Show()
        wx.CallAfter(self.play_last_station_on_startup)
        if config.getboolean("General", "auto_update_check", fallback=True):
            wx.CallLater(3000, self.check_for_updates, False)

        speak(self, "Basit Radyo'ya hoş geldiniz.")
        self.list_ctrl.SetFocus()
        if self.list_ctrl.GetItemCount() > 0:
            self.list_ctrl.Select(0)

    def bind_events(self):
        menu_handlers = {
            "NEW": self.on_new,
            "NEW_FAV_LIST": self.on_new_favorite_list,
            "TIMER": self.on_timer,
            "SETTINGS": self.on_settings,
            "EXIT": self.on_exit,
            "SEARCH": self.on_search,
            "EDIT": self.on_edit,
            "MOVE": self.on_move,
            "DELETE": self.on_delete,
            "DELALL": self.on_delete_all,
            "WEB": self.on_web_search,
            "MANAGE_FAVORITES": self.on_manage_favorites,
            "RECORD": self.on_record_toggle,
            "TIMED_RECORD": self.on_timed_record,
            "ABOUT": self.on_about,
            "SHORTCUTS": self.on_show_shortcuts,
            "CONTACT": self.on_contact,
            "MINIMIZE_TRAY": self.on_minimize_to_tray,
            "MANAGE_RECORDINGS": self.on_manage_recordings,
            "HELP_HTML": self.on_help_html,
            "CHECK_UPDATES": self.on_check_updates,
        }
        for key, handler in menu_handlers.items():
            self.Bind(wx.EVT_MENU, handler, id=self.menu_ids[key])

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)
        self.combo_lists.Bind(wx.EVT_COMBOBOX, self.on_select_favorite_list)

        self.Bind(wx.EVT_TIMER, self.on_shutdown, self.shutdown_timer)
        self.Bind(wx.EVT_TIMER, self.on_timed_record_check, self.timed_record_timer)
        self.Bind(wx.EVT_TIMER, self.on_meta_timer, self.meta_timer)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def load_playlist(self):
        self.radios = []
        if not os.path.exists(PLAYLIST_FILE):
            return
        with open(PLAYLIST_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        i = 0
        base_time = datetime.datetime.now()
        index_counter = 0

        while i < len(lines):
            if lines[i].startswith("#EXTINF"):
                try:
                    name = lines[i].split(",", 1)[1]
                    url = lines[i + 1] if i + 1 < len(lines) else ""
                    if name and url:
                        creation_time = base_time + datetime.timedelta(seconds=index_counter)
                        index_counter += 1
                        station = RadioStation(name, url, creation_time)
                        self.radios.append(station)
                    i += 2
                except (IndexError, ValueError):
                    i += 1
            else:
                i += 1

    def save_playlist(self):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for station in self.radios:
                f.write(f"#EXTINF:-1,{station.name}\n{station.url}\n")

    def apply_saved_sort(self):
        last_sort = config.get("General", "last_sort_order", fallback="date_asc")
        if last_sort == "name":
            self.radios.sort(key=lambda s: s.name.lower())
        elif last_sort == "date_asc":
            self.radios.sort(key=lambda s: s.creation_time)
        elif last_sort == "date_desc":
            self.radios.sort(key=lambda s: s.creation_time, reverse=True)

    def load_favorites(self):
        if os.path.exists(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                    self.favorites = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self.favorites = {}
        else:
            self.favorites = {}

    def save_favorites(self):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.favorites, f, ensure_ascii=False, indent=2)

    def update_favorites_combo(self):
        lists = ["Tüm Radyolar"] + sorted(list(self.favorites.keys()))
        current_selection = self.combo_lists.GetValue()
        self.combo_lists.Set(lists)
        if current_selection in lists:
            self.combo_lists.SetValue(current_selection)
        else:
            self.combo_lists.SetSelection(0)

    def get_station_display_name(self, station, is_current):
        base = station.name
        if is_current and self.show_now_playing_in_list and self.current_stream_title:
            meta = self.current_stream_title.strip()
            max_len = 80
            if len(meta) > max_len:
                meta = meta[: max_len - 3] + "..."
            return f"{base} - {meta}"
        return base

    def refresh_list_ctrl(self, list_to_show):
        self.current_list_name = list_to_show
        display_radios = []
        playing_station = None

        if self.current_index is not None and 0 <= self.current_index < len(self.radios):
            playing_station = self.radios[self.current_index]

        if list_to_show == "Tüm Radyolar":
            display_radios = self.radios
        elif list_to_show in self.favorites:
            favorite_urls = self.favorites[list_to_show]
            fav_radio_map = {station.url: station for station in self.radios}
            display_radios = [fav_radio_map[url] for url in favorite_urls if url in fav_radio_map]

        if self.current_search_term:
            search_clean = normalize_radio_name(self.current_search_term)
            display_radios = [r for r in display_radios if search_clean in normalize_radio_name(r.name)]

        current_selection_index = self.list_ctrl.GetFirstSelected()
        self.list_ctrl.DeleteAllItems()

        for station in display_radios:
            try:
                original_index = self.radios.index(station)
                is_current = playing_station is not None and station is playing_station
                display_name = self.get_station_display_name(station, is_current)
                list_index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), display_name)
                self.list_ctrl.SetItemData(list_index, original_index)
            except ValueError:
                continue

        if playing_station:
            try:
                self.current_index = self.radios.index(playing_station)
            except ValueError:
                self.current_index = None

        if self.list_ctrl.GetItemCount() > 0:
            if not (0 <= current_selection_index < self.list_ctrl.GetItemCount()):
                new_selection = 0
            else:
                new_selection = current_selection_index
            self.list_ctrl.Select(new_selection)
            self.list_ctrl.Focus(new_selection)
            self.list_ctrl.EnsureVisible(new_selection)

    def update_tray_tooltip(self):
        if not self.tray_icon:
            return
        tooltip = "Basit Radyo"
        if self.current_index is not None and 0 <= self.current_index < len(self.radios):
            station = self.radios[self.current_index]
            if self.current_stream_title:
                tooltip = f"{station.name} - {self.current_stream_title}"
            else:
                tooltip = station.name
        self.tray_icon.update_tooltip(tooltip)

    def toggle_play_pause(self, idx_in_view):
        if idx_in_view < 0:
            return
        original_idx = self.list_ctrl.GetItemData(idx_in_view)
        if not (0 <= original_idx < len(self.radios)):
            return
        station = self.radios[original_idx]
        self.play_station_by_object(station, toggle=True)

    def play_station_by_object(self, station, toggle=False):
        global bass
        try:
            original_idx = self.radios.index(station)
        except ValueError:
            speak_or_dialog(self, "Radyo listede bulunamadı.", "Hata", wx.ICON_ERROR)
            return

        is_playing = (
            self.current_index == original_idx
            and self.current_stream.value != 0
            and bass.BASS_ChannelIsActive(self.current_stream) == 1
        )

        if toggle and is_playing:
            bass.BASS_ChannelPause(self.current_stream)
            self.SetStatusText(f"Duraklatıldı: {station.name}")
            speak(self, f"{station.name} duraklatıldı")
            return

        self.play_request_id += 1
        request_id = self.play_request_id
        self.is_connecting_stream = True

        if self.current_stream.value != 0:
            with BASS_LOCK:
                bass.BASS_StreamFree(self.current_stream)
            self.current_stream = ctypes.c_uint(0)
            self.current_index = None

        self.current_stream_title = ""
        self.SetStatusText(f"Bağlanılıyor: {station.name}...")
        logging.info("Yayın bağlantı denemesi başladı: ad=%s url=%s", station.name, station.url)
        threading.Thread(
            target=self._connect_station_thread,
            args=(request_id, original_idx, station),
            daemon=True,
        ).start()
        return

    def _connect_station_thread(self, request_id, original_idx, station):
        global bass
        stream_handle = 0
        err_code = 0
        started_at = time.time()
        try:
            with BASS_LOCK:
                stream_handle = bass.BASS_StreamCreateURL(station.url.encode("utf-8"), 0, 0, None, None)
                if stream_handle == 0:
                    err_code = bass.BASS_ErrorGetCode()
        except Exception as e:
            logging.exception("Yayın bağlantısı sırasında beklenmeyen hata: ad=%s url=%s hata=%s", station.name, station.url, e)
            err_code = -1

        elapsed = time.time() - started_at
        logging.info(
            "Yayın bağlantı denemesi bitti: ad=%s url=%s sonuc=%s hata=%s sure=%.2fs",
            station.name,
            station.url,
            "başarılı" if stream_handle else "başarısız",
            err_code,
            elapsed,
        )
        wx.CallAfter(self._finish_station_connection, request_id, original_idx, station, stream_handle, err_code)

    def _finish_station_connection(self, request_id, original_idx, station, stream_handle, err_code):
        global bass
        if self.is_shutting_down or request_id != self.play_request_id:
            if stream_handle:
                try:
                    with BASS_LOCK:
                        bass.BASS_StreamFree(ctypes.c_uint(stream_handle))
                except Exception:
                    pass
            return

        self.is_connecting_stream = False

        if stream_handle == 0:
            if err_code == 40:
                hata_mesaji = "Bağlantı zaman aşımına uğradı. Yayın şu an aktif olmayabilir veya ayarlardan bağlantı zaman aşımı süresini artırabilirsiniz."
            elif err_code == 2:
                hata_mesaji = "Akış adresi açılamadı. Lütfen URL'nin doğru ve güncel olduğundan emin olun."
            elif err_code == 41:
                hata_mesaji = "Bu radyonun yayın formatı desteklenmiyor (Ek eklenti gerekebilir)."
            elif err_code == -1:
                hata_mesaji = "Akış açılırken beklenmeyen bir hata oluştu. Ayrıntılar log dosyasına yazıldı."
            else:
                hata_mesaji = f"Akış açılamadı (Hata Kodu: {err_code})"

            speak_or_dialog(self, hata_mesaji, "Bağlantı Hatası", wx.ICON_WARNING)
            self.SetStatusText("Boşta")
            self.current_stream = ctypes.c_uint(0)
            self.current_index = None
            return

        self.current_stream = ctypes.c_uint(stream_handle)
        self.current_index = original_idx
        bass.BASS_ChannelPlay(self.current_stream, False)
        bass.BASS_ChannelSetAttribute(
            self.current_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume / 100.0)
        )
        self.SetStatusText(f"Oynatılıyor: {station.name}")
        speak(self, f"{station.name} oynatılıyor")

        config["General"]["last_played_index"] = str(original_idx)
        save_config()

        if not self.meta_timer.IsRunning():
            self.meta_timer.Start(3000)

        self.refresh_list_ctrl(self.current_list_name)
        self.update_tray_tooltip()

    def on_manage_recordings(self, event):
        with ManageRecordingsDialog(self, get_record_path()) as dlg:
            dlg.ShowModal()

    def stop_recording_playback(self):
        global bass
        if self.record_play_stream.value != 0:
            try:
                bass.BASS_StreamFree(self.record_play_stream)
            except Exception:
                pass
            self.record_play_stream = ctypes.c_uint(0)
        self.current_record_path = None
        if self.current_stream.value == 0 and not self.is_recording:
            self.SetStatusText("Boşta")

    def play_recording_file(self, file_path, toggle=False):
        global bass

        if not os.path.exists(file_path):
            speak_or_dialog(self, "Kayıt dosyası bulunamadı.", "Hata", wx.ICON_ERROR)
            return

        if (
            self.current_record_path
            and os.path.normpath(self.current_record_path) == os.path.normpath(file_path)
            and self.record_play_stream.value != 0
        ):
            status = bass.BASS_ChannelIsActive(self.record_play_stream)
            if toggle and status == 1:
                bass.BASS_ChannelPause(self.record_play_stream)
                self.SetStatusText("Kayıt duraklatıldı.")
                speak(self, "Kayıt duraklatıldı.")
                return
            elif toggle and status != 1:
                bass.BASS_ChannelPlay(self.record_play_stream, False)
                base = os.path.basename(file_path)
                self.SetStatusText(f"Kayıt oynatılıyor: {base}")
                speak(self, f"Kayıt oynatılıyor: {base}")
                return

        if self.record_play_stream.value != 0:
            try:
                bass.BASS_StreamFree(self.record_play_stream)
            except Exception:
                pass
            self.record_play_stream = ctypes.c_uint(0)

        if self.current_stream.value != 0:
            if bass.BASS_ChannelIsActive(self.current_stream) == 1:
                bass.BASS_ChannelPause(self.current_stream)
                speak(self, "Canlı radyo duraklatıldı, kayıt oynatılıyor.")

        try:
            wpath = ctypes.c_wchar_p(file_path)
            stream = bass.BASS_StreamCreateFile(False, wpath, 0, 0, BASS_UNICODE)
        except Exception as e:
            logging.error(f"Kayıt çalarken istisna: {e}")
            speak_or_dialog(self, "Kayıt çalınamadı.", "Hata", wx.ICON_ERROR)
            return

        if stream == 0:
            err = bass.BASS_ErrorGetCode()
            logging.error(f"BASS_StreamCreateFile hata kodu: {err}")
            speak_or_dialog(self, "Kayıt çalınamadı.", "Hata", wx.ICON_ERROR)
            return

        self.record_play_stream = ctypes.c_uint(stream)
        self.current_record_path = file_path

        bass.BASS_ChannelSetAttribute(
            self.record_play_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume / 100.0)
        )
        bass.BASS_ChannelPlay(self.record_play_stream, False)

        base = os.path.basename(file_path)
        self.SetStatusText(f"Kayıt oynatılıyor: {base}")
        speak(self, f"Kayıt oynatılıyor: {base}")

    def seek_recording(self, delta_seconds):
        global bass
        if self.record_play_stream.value == 0:
            return
        try:
            handle = self.record_play_stream

            pos_bytes = bass.BASS_ChannelGetPosition(handle, BASS_POS_BYTE)
            length_bytes = bass.BASS_ChannelGetLength(handle, BASS_POS_BYTE)
            if length_bytes == 0:
                return

            pos_secs = bass.BASS_ChannelBytes2Seconds(handle, pos_bytes)
            length_secs = bass.BASS_ChannelBytes2Seconds(handle, length_bytes)

            new_secs = pos_secs + float(delta_seconds)
            if new_secs < 0:
                new_secs = 0.0
            if new_secs > length_secs:
                new_secs = length_secs

            new_bytes = bass.BASS_ChannelSeconds2Bytes(handle, new_secs)
            bass.BASS_ChannelSetPosition(handle, new_bytes, BASS_POS_BYTE)

            direction_word = "ileri" if delta_seconds > 0 else "geri"
            speak(self, f"Kayıt {abs(int(delta_seconds))} saniye {direction_word} alındı.")
        except Exception as e:
            logging.error(f"Kayıt ileri/geri alma hatası: {e}")

    def on_list_context_menu(self, event):
        idx_in_view = self.list_ctrl.GetFirstSelected()
        if idx_in_view < 0:
            return
        original_idx = self.list_ctrl.GetItemData(idx_in_view)
        if not (0 <= original_idx < len(self.radios)):
            return
        station = self.radios[original_idx]

        menu = wx.Menu()
        is_playing = (
            self.current_index == original_idx
            and self.current_stream.value != 0
            and bass.BASS_ChannelIsActive(self.current_stream) == 1
        )
        menu.Append(
            self.menu_ids["CTX_PLAY_PAUSE"],
            "Duraklat" if is_playing else "Oynat",
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self.toggle_play_pause(idx_in_view),
            id=self.menu_ids["CTX_PLAY_PAUSE"],
        )

        menu.AppendSeparator()

        item_up = menu.Append(self.menu_ids["CTX_MOVE_UP"], "Yukarı Taşı")
        item_up.Enable(idx_in_view > 0)
        self.Bind(wx.EVT_MENU, self.on_move_up, id=self.menu_ids["CTX_MOVE_UP"])

        item_down = menu.Append(self.menu_ids["CTX_MOVE_DOWN"], "Aşağı Taşı")
        item_down.Enable(idx_in_view < self.list_ctrl.GetItemCount() - 1)
        self.Bind(wx.EVT_MENU, self.on_move_down, id=self.menu_ids["CTX_MOVE_DOWN"])

        sort_menu = wx.Menu()
        sort_menu.Append(self.menu_ids["CTX_SORT_NAME"], "Ada göre sırala")
        sort_menu.Append(self.menu_ids["CTX_SORT_DATE_ASC"], "Tarihe göre sırala (En eski üstte)")
        sort_menu.Append(self.menu_ids["CTX_SORT_DATE_DESC"], "Tarihe göre sırala (En yeni üstte)")
        menu.AppendSubMenu(sort_menu, "Sırala")
        self.Bind(wx.EVT_MENU, self.on_sort_by_name, id=self.menu_ids["CTX_SORT_NAME"])
        self.Bind(wx.EVT_MENU, self.on_sort_by_date_asc, id=self.menu_ids["CTX_SORT_DATE_ASC"])
        self.Bind(wx.EVT_MENU, self.on_sort_by_date_desc, id=self.menu_ids["CTX_SORT_DATE_DESC"])

        menu.AppendSeparator()

        if self.current_list_name == "Tüm Radyolar":
            if self.favorites:
                fav_submenu = wx.Menu()
                added_to_submenu = False
                for list_name in sorted(self.favorites.keys()):
                    if station.url not in self.favorites.get(list_name, []):
                        add_id = wx.NewIdRef()
                        fav_submenu.Append(add_id, list_name)
                        self.Bind(
                            wx.EVT_MENU,
                            lambda e, name=list_name, u=station.url: self.on_add_to_favorite(
                                e, name, u
                            ),
                            id=add_id,
                        )
                        added_to_submenu = True
                if added_to_submenu:
                    menu.AppendSubMenu(fav_submenu, "Favorilere Ekle")
        else:
            remove_id = wx.NewIdRef()
            menu.Append(remove_id, f"'{self.current_list_name}' listesinden kaldır")
            self.Bind(
                wx.EVT_MENU,
                lambda e, cl=self.current_list_name, i=idx_in_view: self.on_remove_from_favorite(e, cl, i),
                id=remove_id,
            )

        self.PopupMenu(menu)
        menu.Destroy()

    def on_add_to_favorite(self, event, list_name, radio_url):
        if radio_url not in self.favorites.get(list_name, []):
            self.favorites[list_name].append(radio_url)
            self.save_favorites()
            speak_or_dialog(self, f"Radyo '{list_name}' listesine eklendi.")

    def on_remove_from_favorite(self, event, list_name, item_index_in_view):
        if list_name not in self.favorites:
            return
        original_idx = self.list_ctrl.GetItemData(item_index_in_view)
        if not (0 <= original_idx < len(self.radios)):
            return
        station_to_remove = self.radios[original_idx]
        fav_urls = self.favorites[list_name]
        if station_to_remove.url in fav_urls:
            fav_urls.remove(station_to_remove.url)
            self.save_favorites()
            speak_or_dialog(self, f"'{station_to_remove.name}', '{list_name}' listesinden kaldırıldı.")
            self.refresh_list_ctrl(list_name)

    def on_show_shortcuts(self, event):
        with ShortcutsDialog(self) as dlg:
            dlg.ShowModal()

    def on_contact(self, event):
        try:
            webbrowser.open(f"mailto:{CONTACT_EMAIL}")
            speak(self, "E-posta istemciniz açılıyor...")
        except Exception as e:
            speak_or_dialog(self, f"E-posta istemcisi açılamadı.\nHata: {e}", "Hata", wx.ICON_ERROR)

    def on_minimize_to_tray(self, event):
        if self.tray_icon:
            return
        self.tray_icon = TrayIcon(self)
        self.update_tray_tooltip()
        self.Hide()
        speak(self, "Sistem tepsisine küçültüldü.")

    def on_key(self, event):
        key = event.GetKeyCode()
        sh = event.ShiftDown()
        ctrl = event.ControlDown()
        alt = event.AltDown()

        if not ctrl and not sh and not alt and key == wx.WXK_SPACE:
            idx = self.list_ctrl.GetFirstSelected()
            if idx >= 0:
                self.toggle_play_pause(idx)
        elif ctrl and not sh and not alt and key == wx.WXK_RIGHT:
            self.seek_recording(self.record_seek_seconds)
        elif ctrl and not sh and not alt and key == wx.WXK_LEFT:
            self.seek_recording(-self.record_seek_seconds)
        elif not ctrl and not sh and not alt and key in (wx.WXK_LEFT, wx.WXK_RIGHT):
            delta = 2 if key == wx.WXK_RIGHT else -2
            self.change_volume(delta)
        elif key == wx.WXK_ESCAPE and not ctrl and not sh and not alt:
            if self.current_search_term:
                self.current_search_term = ""
                self.refresh_list_ctrl(self.current_list_name)
                speak(self, "Arama filtresi temizlendi, liste eski haline döndü.")
                if self.list_ctrl.GetItemCount() > 0:
                    self.list_ctrl.SetFocus()
                    self.list_ctrl.Select(0)
            else:
                event.Skip()
        elif ctrl and not sh and not alt and key == ord("N"):
            self.on_new(None)
        elif ctrl and sh and not alt and key == ord("N"):
            self.on_new_favorite_list(None)
        elif ctrl and not sh and not alt and key == ord("T"):
            self.on_timer(None)
        elif ctrl and not sh and not alt and key == ord("P"):
            self.on_settings(None)
        elif alt and ctrl and not sh and key == ord("M"):
            self.on_minimize_to_tray(None)
        elif ctrl and not sh and not alt and key == ord("Q"):
            self.on_exit(None)
        elif not ctrl and not sh and not alt and key == wx.WXK_F3:
            self.on_search(None)
        elif not ctrl and not sh and not alt and key == wx.WXK_F2:
            self.on_edit(None)
        elif ctrl and not sh and not alt and key == ord("M"):
            self.on_move(None)
        elif not ctrl and not sh and not alt and key == wx.WXK_DELETE:
            self.on_delete(None)
        elif not ctrl and sh and not alt and key == wx.WXK_DELETE:
            self.on_delete_all(None)
        elif ctrl and sh and not alt and key == ord("M"):
            self.on_manage_favorites(None)
        elif not ctrl and not sh and not alt and key == wx.WXK_F4:
            self.on_web_search(None)
        elif ctrl and not sh and not alt and key == ord("R"):
            self.on_record_toggle(None)
        elif ctrl and sh and not alt and key == ord("R"):
            self.on_timed_record(None)
        elif not ctrl and sh and not alt and key == ord("R"):
            self.stop_recording(confirm=True)
        elif not ctrl and not sh and not alt and key == wx.WXK_F1:
            self.on_about(None)
        elif not ctrl and sh and not alt and key == wx.WXK_F1:
            self.on_show_shortcuts(None)
        elif ctrl and sh and not alt and key == wx.WXK_F1:
            self.on_help_html(None)
        elif ctrl and not sh and not alt and key == ord("I"):
            self.on_contact(None)
        elif ctrl and not sh and not alt and key == ord("L"):
            self.on_manage_recordings(None)
        else:
            event.Skip()

    def change_volume(self, delta):
        global bass
        self.volume = max(0, min(100, self.volume + delta))
        if self.current_stream.value != 0:
            bass.BASS_ChannelSetAttribute(
                self.current_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume / 100.0)
            )
        if self.record_play_stream.value != 0:
            bass.BASS_ChannelSetAttribute(
                self.record_play_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume / 100.0)
            )
        speak(self, f"Ses yüzde {self.volume}")

    def on_exit(self, event):
        speak(self, "Program kapatılıyor.")
        self.Close()

    def on_close(self, event):
        global bass
        self.is_shutting_down = True
        self.play_request_id += 1

        if self.tray_icon:
            self.tray_icon.Destroy()
            self.tray_icon = None

        if self.is_recording:
            if self.recording_process:
                self.recording_process.terminate()
                try:
                    self.recording_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logging.warning("ffmpeg kapanırken zaman aşımına uğradı.")
            self.is_recording = False
            if self.current_wav_path and os.path.exists(self.current_wav_path):
                mp3_path = self.current_wav_path.replace(".wav", ".mp3")
                self._convert_to_mp3_thread(self.current_wav_path, mp3_path, synchronous=True)

        self.stop_recording_playback()

        with BASS_LOCK:
            if self.current_stream.value != 0:
                bass.BASS_StreamFree(self.current_stream)
            bass.BASS_Free()
        self.Destroy()

    def on_settings(self, event):
        with SettingsDialog(self, sorted(list(self.favorites.keys()))) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                vals = dlg.get_values()
                config["General"]["accessibility"] = str(vals["accessibility"])
                config["General"]["play_on_startup"] = str(vals["play_on_startup"])
                config["General"]["filter_web_duplicates"] = str(vals["filter_web_duplicates"])
                config["General"]["fallback_to_radio_browser"] = str(vals["fallback_to_radio_browser"])
                config["General"]["record_path"] = vals["record_path"]
                config["General"]["default_list"] = vals["default_list"]
                config["General"]["show_now_playing_in_list"] = str(vals["show_now_playing_in_list"])
                config["General"]["record_seek_seconds"] = str(vals["record_seek_seconds"])
                config["General"]["net_timeout_seconds"] = str(vals["net_timeout_seconds"])
                config["General"]["search_source"] = str(vals["search_source"])
                config["General"]["enable_logging"] = str(vals["enable_logging"])
                config["General"]["auto_update_check"] = str(vals["auto_update_check"])

                new_path_from_dialog = vals["record_path"]
                default_path_at_moment = os.path.join(BASE_DIR, "kayıtlar")

                if os.path.normpath(new_path_from_dialog) == os.path.normpath(default_path_at_moment):
                    config["General"]["record_path"] = DEFAULT_PATH_PLACEHOLDER
                else:
                    config["General"]["record_path"] = new_path_from_dialog

                save_config()
                configure_file_logging()
                
                global bass
                bass.BASS_SetConfig(BASS_CONFIG_NET_TIMEOUT, vals["net_timeout_seconds"] * 1000)

                self.accessibility_enabled = vals["accessibility"]
                self.show_now_playing_in_list = vals["show_now_playing_in_list"]
                self.record_seek_seconds = vals["record_seek_seconds"]

                record_path_to_create = get_record_path()
                if not os.path.isdir(record_path_to_create):
                    try:
                        os.makedirs(record_path_to_create, exist_ok=True)
                    except Exception as e:
                        speak_or_dialog(self, f"Kayıt klasörü oluşturulamadı.\n{e}", "Hata", wx.ICON_ERROR)

                self.refresh_list_ctrl(self.current_list_name)
                speak(self, "Ayarlar kaydedildi.")

    def on_record_toggle(self, event):
        if self.is_recording:
            self.stop_recording(confirm=True)
        else:
            self.start_recording()

    def start_recording(self, target_station=None, skip_playback_check=False):
        global bass

        if self.is_recording:
            speak_or_dialog(self, "Zaten bir kayıt devam ediyor.", "Uyarı", wx.ICON_WARNING)
            return

        if not os.path.exists(FFMPEG_EXE):
            speak_or_dialog(self, f"ffmpeg.exe, '{BIN_DIR}' klasöründe bulunamadı!", "Hata", wx.ICON_ERROR)
            return

        station_to_record = None
        if target_station:
            station_to_record = target_station
        else:
            idx = self.list_ctrl.GetFirstSelected()
            if idx < 0:
                speak_or_dialog(self, "Kayda başlamak için önce bir radyo seçip oynatın.", "Uyarı", wx.ICON_WARNING)
                return
            original_idx = self.list_ctrl.GetItemData(idx)
            station_to_record = self.radios[original_idx]

        is_current_station = (
            self.current_index is not None
            and self.radios[self.current_index] == station_to_record
        )
        is_playing = (
            is_current_station
            and self.current_stream.value != 0
            and bass.BASS_ChannelIsActive(self.current_stream) == 1
        )
        can_record_in_background = target_station is not None and not is_current_station
        if not skip_playback_check and not is_playing and not can_record_in_background:
            speak_or_dialog(self, "Kayda başlamak için radyonun çalıyor olması gerekir.", "Uyarı", wx.ICON_WARNING)
            return

        threading.Thread(target=self._start_recording_thread, args=(station_to_record,), daemon=True).start()

    def _start_recording_thread(self, station):
        wx.CallAfter(self.SetStatusText, f"'{station.name}' için kayıt başlatılıyor...")
        safe_name = re.sub(r'[\\/*?:"<>|]', "", station.name)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_wav_path = os.path.join(get_record_path(), f"{safe_name}_{timestamp}.wav")

        command = [FFMPEG_EXE, "-i", station.url, "-y", self.current_wav_path]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.recording_process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo
            )
            self.is_recording = True
            wx.CallAfter(self.record_menu_item.SetItemLabel, "Kaydı Durdur\tCtrl+R")
            wx.CallAfter(self.SetStatusText, f"Kayıt sürüyor: {os.path.basename(self.current_wav_path)}")
            speak(self, f"'{station.name}' kaydı başladı.")
        except Exception as e:
            logging.error(f"FFmpeg başlatılamadı: {e}")
            speak_or_dialog(self, f"Kayıt başlatılamadı: {e}", "Hata", wx.ICON_ERROR)
            wx.CallAfter(self.SetStatusText, "Boşta")

    def stop_recording(self, confirm=True, stop_playback=False):
        global bass

        is_active_record = self.is_recording
        is_pending_timed_record = self.timed_record_start or self.timed_record_end

        if not is_active_record and not is_pending_timed_record:
            return

        if confirm:
            msg = (
                "Devam eden kaydı durdurmak istediğinizden emin misiniz?"
                if is_active_record
                else "Zamanlanmış kaydı iptal etmek istediğinizden emin misiniz?"
            )
            with wx.MessageDialog(self, msg, "Kaydı Durdur/İptal Et", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) as dlg:
                if dlg.ShowModal() != wx.ID_YES:
                    return

        if is_active_record:
            if self.recording_process:
                self.recording_process.terminate()
            self.is_recording = False
            speak(self, "Kayıt durduruldu.")
            self.record_menu_item.SetItemLabel("Normal Kayıt\tCtrl+R")

            self.SetStatusText("Kayıt durduruldu. MP3'e dönüştürülüyor...")
            if self.current_wav_path:
                mp3_path = self.current_wav_path.replace(".wav", ".mp3")
                threading.Thread(
                    target=self._convert_to_mp3_thread, args=(self.current_wav_path, mp3_path), daemon=True
                ).start()
            self.recording_process = None
            self.current_wav_path = None
            self.timed_record_end = None
            if self.timed_record_timer.IsRunning():
                self.timed_record_timer.Stop()

            if stop_playback and self.current_stream.value != 0:
                bass.BASS_StreamFree(self.current_stream)
                self.current_stream = ctypes.c_uint(0)
                self.current_index = None
                self.SetStatusText("Boşta")

        if is_pending_timed_record and not is_active_record:
            self.timed_record_start = None
            self.timed_record_end = None
            self.timed_record_station = None
            if self.timed_record_timer.IsRunning():
                self.timed_record_timer.Stop()
            self.SetStatusText("Zamanlı kayıt iptal edildi.")
            speak(self, "Zamanlı kayıt iptal edildi.")

    def _convert_to_mp3_thread(self, wav_path, mp3_path, synchronous=False):
        if not synchronous:
            speak(self, "MP3'e dönüştürülüyor...")

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        command = [FFMPEG_EXE, "-i", wav_path, "-b:a", "128k", "-y", mp3_path]

        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            if not synchronous:
                speak(self, f"Dönüştürme tamamlandı: {os.path.basename(mp3_path)}")
            if os.path.exists(wav_path):
                os.remove(wav_path)
        except Exception as e:
            logging.error(f"MP3 dönüştürme hatası: {e}")
            if not synchronous:
                speak_or_dialog(self, "MP3 dönüştürme sırasında bir hata oluştu.", "Hata", wx.ICON_ERROR)
        finally:
            if not synchronous and not self.is_recording and self.current_stream.value == 0:
                wx.CallAfter(self.SetStatusText, "Boşta")

    def on_timed_record(self, event):
        if self.is_recording:
            speak_or_dialog(self, "Zamanlı kayıt başlatmak için önce mevcut kaydı durdurun.", "Uyarı", wx.ICON_WARNING)
            return

        with TimedRecordDialog(self, self.radios) as dlg:
            res = dlg.ShowModal()
            if res == wx.ID_OK:
                try:
                    start_dt, end_dt, station = dlg.get_values()
                    self.timed_record_start = start_dt
                    self.timed_record_end = end_dt
                    self.timed_record_station = station
                    self.timed_record_timer.Start(1000)

                    station_name = f"'{station.name}' radyosu" if station else "O an çalan radyo"
                    msg = f"Zamanlı kayıt ayarlandı: {station_name}. Başlangıç: {self.timed_record_start:%H:%M}, Bitiş: {self.timed_record_end:%H:%M}"
                    self.SetStatusText(msg)
                    speak(self, msg)
                except ValueError as e:
                    speak_or_dialog(self, str(e), "Geçersiz Zaman", wx.ICON_ERROR)
            elif res == wx.ID_DELETE:
                self.stop_recording(confirm=False)

    def on_timed_record_check(self, event):
        now = datetime.datetime.now()

        if self.timed_record_start and now >= self.timed_record_start:
            station_to_record = self.timed_record_station
            if station_to_record:
                speak(self, f"Zamanlı kayıt başlıyor: {station_to_record.name}")
                self.start_recording(station_to_record, True)
            else:
                speak(self, "Zamanlı kayıt başlıyor.")
                self.start_recording()
            self.timed_record_start = None

        if self.timed_record_end and now >= self.timed_record_end:
            speak(self, "Zamanlı kayıt bitiyor.")
            self.stop_recording(confirm=False, stop_playback=False)
            self.timed_record_end = None
            self.timed_record_station = None
            self.timed_record_timer.Stop()

    def on_meta_timer(self, event):
        global bass
        if self.current_stream.value == 0:
            return

        try:
            tags_ptr = bass.BASS_ChannelGetTags(self.current_stream, BASS_TAG_META)
        except Exception:
            return

        if not tags_ptr:
            return

        try:
            meta_str = tags_ptr.decode("utf-8")
        except UnicodeDecodeError:
            meta_str = tags_ptr.decode("latin-1", errors="ignore")

        title = None
        key = "StreamTitle='"
        idx = meta_str.find(key)
        if idx != -1:
            start = idx + len(key)
            end = meta_str.find("';", start)
            if end == -1:
                end = len(meta_str)
            title = meta_str[start:end].strip()

        if not title or title == self.current_stream_title:
            return

        self.current_stream_title = title
        self.refresh_list_ctrl(self.current_list_name)
        self.update_tray_tooltip()

    def _is_duplicate_url(self, url):
        check_url = url.strip().lower().rstrip('/')
        for station in self.radios:
            existing_url = station.url.strip().lower().rstrip('/')
            if existing_url == check_url:
                return station.name
        return None

    def add_radio_station(self, name, url):
        existing_name = self._is_duplicate_url(url)
        if existing_name:
            speak_or_dialog(self, f"Bu akış adresi zaten listenizde '{existing_name}' adıyla mevcut!\nLütfen farklı bir adres girin.", "Kopya Akış Adresi", wx.ICON_WARNING)
            return

        now = datetime.datetime.now()
        new_station = RadioStation(name, url, now)
        self.radios.append(new_station)
        self.save_playlist()
        self.apply_saved_sort()
        self.refresh_list_ctrl(self.current_list_name)
        speak_or_dialog(self, f"'{name}' başarıyla eklendi.")

    def on_new(self, event):
        with RadioDialog(self, "Yeni Radyo Ekle", ok_label="Ekle") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                name, url = dlg.get_values()
                if name and url:
                    self.add_radio_station(name, url)

    def on_search(self, event):
        with SearchDialog(self, self.current_search_term) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                term = dlg.get_term()
                self.current_search_term = term
                
                self.refresh_list_ctrl(self.current_list_name)
                
                count = self.list_ctrl.GetItemCount()
                if term:
                    if count > 0:
                        speak(self, f"Arama tamamlandı. {count} adet radyo listelendi.")
                    else:
                        speak_or_dialog(self, "Aradığınız kelimeye uygun radyo bulunamadı.", "Bulunamadı", wx.ICON_INFORMATION)
                else:
                    speak(self, "Arama filtresi temizlendi, tüm liste gösteriliyor.")

    def on_edit(self, event):
        idx_in_view = self.list_ctrl.GetFirstSelected()
        if idx_in_view < 0:
            speak_or_dialog(self, "Önce bir radyo seçin.", "Uyarı", wx.ICON_WARNING)
            return
        original_idx = self.list_ctrl.GetItemData(idx_in_view)
        if not (0 <= original_idx < len(self.radios)):
            return

        station = self.radios[original_idx]
        old_url = station.url

        with RadioDialog(self, "Radyoyu Düzenle", station.name, station.url, ok_label="Kaydet") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                n, u = dlg.get_values()
                if n and u:
                    station.name = n
                    station.url = u
                    if old_url != u:
                        for key in self.favorites:
                            fav_list = self.favorites[key]
                            for i, fav_url in enumerate(fav_list):
                                if fav_url == old_url:
                                    fav_list[i] = u
                                    break
                        self.save_favorites()
                    self.save_playlist()
                    self.refresh_list_ctrl(self.combo_lists.GetValue())
                    speak(self, "Radyo güncellendi.")

    def on_move(self, event):
        if self.current_search_term:
            speak_or_dialog(self, "Arama filtresi aktifken radyolar taşınamaz. İşlem yapmak için lütfen önce aramayı (F3) temizleyin.", "Uyarı", wx.ICON_WARNING)
            return

        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            speak_or_dialog(self, "Önce taşımak istediğiniz bir radyo seçin.", "Uyarı", wx.ICON_WARNING)
            return

        list_name = self.current_list_name
        radio_count = self.list_ctrl.GetItemCount()

        with MoveDialog(self, radio_count) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                try:
                    new_pos = dlg.get_position()
                    if not (1 <= new_pos <= radio_count):
                        raise ValueError("Geçersiz sıra numarası.")
                    new_idx = new_pos - 1

                    if list_name == "Tüm Radyolar":
                        original_idx = self.list_ctrl.GetItemData(idx)
                        station_to_move = self.radios.pop(original_idx)
                        self.radios.insert(new_idx, station_to_move)
                        config["General"]["last_sort_order"] = "manual"
                        save_config()
                        self.save_playlist()
                    else:
                        fav_urls = self.favorites[list_name]
                        url_to_move = fav_urls.pop(idx)
                        fav_urls.insert(new_idx, url_to_move)
                        self.save_favorites()

                    self.refresh_list_ctrl(list_name)
                    self.list_ctrl.Select(new_idx)
                    self.list_ctrl.Focus(new_idx)
                    self.list_ctrl.EnsureVisible(new_idx)
                    speak(self, f"Radyo {new_pos}. sıraya taşındı.")
                except (ValueError, TypeError):
                    speak_or_dialog(self, f"Lütfen 1 ile {radio_count} arasında geçerli bir sayı girin.", "Hata", wx.ICON_ERROR)

    def on_move_up(self, event):
        if self.current_search_term:
            speak_or_dialog(self, "Arama filtresi aktifken radyolar taşınamaz. İşlem yapmak için lütfen önce aramayı (F3) temizleyin.", "Uyarı", wx.ICON_WARNING)
            return

        idx = self.list_ctrl.GetFirstSelected()
        if idx <= 0:
            return
        list_name = self.current_list_name
        if list_name == "Tüm Radyolar":
            original_idx_current = self.list_ctrl.GetItemData(idx)
            original_idx_prev = self.list_ctrl.GetItemData(idx - 1)
            self.radios[original_idx_current], self.radios[original_idx_prev] = (
                self.radios[original_idx_prev], self.radios[original_idx_current],
            )
            config["General"]["last_sort_order"] = "manual"
            save_config()
            self.save_playlist()
        else:
            fav_urls = self.favorites[list_name]
            fav_urls[idx], fav_urls[idx - 1] = fav_urls[idx - 1], fav_urls[idx]
            self.save_favorites()
        self.refresh_list_ctrl(list_name)
        self.list_ctrl.Select(idx - 1)
        self.list_ctrl.Focus(idx - 1)

    def on_move_down(self, event):
        if self.current_search_term:
            speak_or_dialog(self, "Arama filtresi aktifken radyolar taşınamaz. İşlem yapmak için lütfen önce aramayı (F3) temizleyin.", "Uyarı", wx.ICON_WARNING)
            return

        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0 or idx >= self.list_ctrl.GetItemCount() - 1:
            return
        list_name = self.current_list_name
        if list_name == "Tüm Radyolar":
            original_idx_current = self.list_ctrl.GetItemData(idx)
            original_idx_next = self.list_ctrl.GetItemData(idx + 1)
            self.radios[original_idx_current], self.radios[original_idx_next] = (
                self.radios[original_idx_next], self.radios[original_idx_current],
            )
            config["General"]["last_sort_order"] = "manual"
            save_config()
            self.save_playlist()
        else:
            fav_urls = self.favorites[list_name]
            fav_urls[idx], fav_urls[idx + 1] = fav_urls[idx + 1], fav_urls[idx]
            self.save_favorites()
        self.refresh_list_ctrl(list_name)
        self.list_ctrl.Select(idx + 1)
        self.list_ctrl.Focus(idx + 1)

    def on_sort_by_name(self, event):
        list_name = self.current_list_name
        if list_name == "Tüm Radyolar":
            self.radios.sort(key=lambda station: station.name.lower())
            config["General"]["last_sort_order"] = "name"
            save_config()
            speak(self, "Liste ada göre sıralandı ve bu tercih kaydedildi.")
        else:
            fav_urls = self.favorites[list_name]
            url_to_name_map = {s.url: s.name for s in self.radios}
            fav_urls.sort(key=lambda url: url_to_name_map.get(url, "").lower())
            self.save_favorites()
            speak(self, f"'{list_name}' listesi ada göre sıralandı.")
        self.refresh_list_ctrl(list_name)

    def on_sort_by_date_asc(self, event):
        list_name = self.current_list_name
        if list_name == "Tüm Radyolar":
            self.radios.sort(key=lambda station: station.creation_time)
            config["General"]["last_sort_order"] = "date_asc"
            save_config()
            speak(self, "Liste eklenme tarihine göre (en eski üstte) sıralandı ve bu tercih kaydedildi.")
        else:
            fav_urls = self.favorites[list_name]
            url_to_station_map = {s.url: s for s in self.radios}
            fav_urls.sort(key=lambda url: url_to_station_map.get(url).creation_time if url in url_to_station_map else datetime.datetime.max)
            self.save_favorites()
            speak(self, f"'{list_name}' listesi tarihe göre (en eski üstte) sıralandı.")
        self.refresh_list_ctrl(list_name)

    def on_sort_by_date_desc(self, event):
        list_name = self.current_list_name
        if list_name == "Tüm Radyolar":
            self.radios.sort(key=lambda station: station.creation_time, reverse=True)
            config["General"]["last_sort_order"] = "date_desc"
            save_config()
            speak(self, "Liste eklenme tarihine göre (en yeni üstte) sıralandı ve bu tercih kaydedildi.")
        else:
            fav_urls = self.favorites[list_name]
            url_to_station_map = {s.url: s for s in self.radios}
            fav_urls.sort(key=lambda url: url_to_station_map.get(url).creation_time if url in url_to_station_map else datetime.datetime.min, reverse=True)
            self.save_favorites()
            speak(self, f"'{list_name}' listesi tarihe göre (en yeni üstte) sıralandı.")
        self.refresh_list_ctrl(list_name)

    def on_delete(self, event):
        global bass
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            return
        original_idx = self.list_ctrl.GetItemData(idx)
        if not (0 <= original_idx < len(self.radios)):
            return
        station_to_delete = self.radios[original_idx]

        with wx.MessageDialog(
            self,
            f"'{station_to_delete.name}' radyosunu kalıcı olarak silmek istediğinizden emin misiniz?\nBu işlem radyoyu tüm favori listelerinden de kaldıracaktır.",
            "Onay",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_YES:
                if self.current_index == original_idx:
                    if self.current_stream.value != 0:
                        bass.BASS_StreamFree(self.current_stream)
                    self.current_stream = ctypes.c_uint(0)
                    self.current_index = None
                    self.current_stream_title = ""
                    self.SetStatusText("Boşta")
                elif self.current_index is not None and self.current_index > original_idx:
                    self.current_index -= 1

                url_to_delete = station_to_delete.url
                self.radios.pop(original_idx)

                for key in self.favorites:
                    self.favorites[key] = [fav_url for fav_url in self.favorites[key] if fav_url != url_to_delete]
                self.save_playlist()
                self.save_favorites()
                self.refresh_list_ctrl(self.current_list_name)
                speak(self, f"'{station_to_delete.name}' silindi.")

    def on_delete_all(self, event):
        global bass
        if not self.radios:
            return
        with wx.MessageDialog(
            self,
            "Tüm radyoları ve favori listelerini KALICI olarak silmek istediğinizden emin misiniz?",
            "Tümünü Sil Onayı",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_YES:
                if self.current_stream.value != 0:
                    bass.BASS_StreamFree(self.current_stream)
                self.current_stream = ctypes.c_uint(0)
                self.current_index = None
                self.current_stream_title = ""
                self.SetStatusText("Boşta")

                self.radios.clear()
                self.favorites.clear()
                self.save_playlist()
                self.save_favorites()
                self.update_favorites_combo()
                self.refresh_list_ctrl(self.combo_lists.GetValue())
                speak(self, "Tüm radyolar ve favori listeleri silindi.")

    def on_timer(self, event):
        with TimerDialog(self) as dlg:
            res = dlg.ShowModal()
            if res == wx.ID_OK:
                try:
                    hh, mm = dlg.get_time()
                except Exception as ex:
                    speak_or_dialog(self, str(ex), "Hata", wx.ICON_ERROR)
                    return
                now = datetime.datetime.now()
                tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if tgt <= now:
                    tgt += datetime.timedelta(days=1)
                ms = int((tgt - now).total_seconds() * 1000)
                self.shutdown_timer.Start(ms, oneShot=True)
                speak(self, f"Kapanma zamanlayıcısı {hh:02d}:{mm:02d} saatine ayarlandı.")
            elif res == wx.ID_DELETE:
                self.shutdown_timer.Stop()
                speak(self, "Kapanma zamanlayıcısı iptal edildi.")

    def on_web_search(self, event):
        with WebSearchDialog(self) as dlg:
            dlg.ShowModal()

    def on_new_favorite_list(self, event):
        with wx.TextEntryDialog(self, "Yeni favori listesinin adını girin:", "Yeni Liste Oluştur") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                name = dlg.GetValue().strip()
                if name and name not in self.favorites and name != "Tüm Radyolar":
                    self.favorites[name] = []
                    self.save_favorites()
                    self.update_favorites_combo()
                    self.combo_lists.SetValue(name)
                    self.refresh_list_ctrl(name)
                    speak_or_dialog(self, f"'{name}' adlı yeni favori listesi oluşturuldu.")
                elif name in self.favorites or name == "Tüm Radyolar":
                    speak_or_dialog(self, "Bu isimde bir liste zaten mevcut veya bu isim kullanılamaz.", "Uyarı", wx.ICON_WARNING)

    def on_select_favorite_list(self, event):
        selected_list = event.GetString()
        if self.current_list_name == selected_list and not self.current_search_term:
            return
        self.current_list_name = selected_list
        self.current_search_term = ""
        speak(self, f"{selected_list} listesi gösteriliyor.")
        self.refresh_list_ctrl(self.current_list_name)
        wx.CallAfter(self.list_ctrl.SetFocus)
        if self.list_ctrl.GetItemCount() > 0:
            self.list_ctrl.Select(0)
        event.Skip()

    def on_manage_favorites(self, event):
        with ManageFavoritesDialog(self, self.favorites) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                current_list_in_combo = self.combo_lists.GetValue()
                self.favorites = dlg.get_updated_favorites()
                self.save_favorites()
                self.update_favorites_combo()
                if current_list_in_combo not in self.favorites and current_list_in_combo != "Tüm Radyolar":
                    self.combo_lists.SetValue("Tüm Radyolar")
                self.current_list_name = self.combo_lists.GetValue()
                self.refresh_list_ctrl(self.current_list_name)
                speak(self, "Favori listeleri güncellendi.")

    def on_check_updates(self, event):
        self.check_for_updates(manual=True)

    def check_for_updates(self, manual=False):
        if getattr(self, "is_checking_updates", False):
            if manual:
                speak_or_dialog(self, "Güncelleme denetimi zaten devam ediyor.", "Güncelleme", wx.ICON_INFORMATION)
            return
        self.is_checking_updates = True
        if manual:
            self.SetStatusText("Güncellemeler denetleniyor...")
            speak(self, "Güncellemeler denetleniyor.")
        threading.Thread(target=self._check_for_updates_thread, args=(manual,), daemon=True).start()

    def _check_for_updates_thread(self, manual):
        try:
            response = requests.get(
                GITHUB_LATEST_RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": f"Basit-Radyo/{APP_VERSION}"},
                timeout=15,
            )
            if response.status_code == 404:
                wx.CallAfter(self._finish_update_check, manual, None, "GitHub'da henüz yayınlanmış sürüm bulunamadı.")
                return
            response.raise_for_status()
            release = response.json()
            latest_version = release.get("tag_name") or release.get("name") or ""
            if not is_newer_version(latest_version, APP_VERSION):
                wx.CallAfter(self._finish_update_check, manual, None, None)
                return

            asset = self._find_update_asset(release)
            release_info = {
                "version": latest_version.lstrip("v"),
                "tag": latest_version,
                "url": release.get("html_url") or GITHUB_RELEASES_URL,
                "notes": release.get("body") or "",
                "asset_name": asset.get("name") if asset else "",
                "asset_url": asset.get("browser_download_url") if asset else "",
            }
            wx.CallAfter(self._finish_update_check, manual, release_info, None)
        except Exception as exc:
            logging.error(f"Güncelleme denetimi hatası: {exc}")
            wx.CallAfter(self._finish_update_check, manual, None, str(exc))

    def _find_update_asset(self, release):
        assets = release.get("assets") or []
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name == "basit_radyo.exe":
                return asset
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name.endswith(".exe"):
                return asset
        return None

    def _finish_update_check(self, manual, release_info, error):
        self.is_checking_updates = False
        if manual:
            self.SetStatusText("Boşta")

        if error:
            if manual:
                speak_or_dialog(self, f"Güncelleme denetlenemedi.\n{error}", "Güncelleme Hatası", wx.ICON_WARNING)
            return

        if not release_info:
            if manual:
                speak_or_dialog(self, f"Basit Radyo zaten güncel. Mevcut sürüm: {APP_VERSION}", "Güncelleme", wx.ICON_INFORMATION)
            return

        msg = (
            f"Yeni Basit Radyo sürümü bulundu.\n\n"
            f"Mevcut sürüm: {APP_VERSION}\n"
            f"Yeni sürüm: {release_info['version']}\n\n"
        )
        if release_info.get("asset_url"):
            msg += "İndirip kurmak ister misiniz?"
        else:
            msg += "Bu sürüm için indirilebilir exe dosyası bulunamadı. GitHub sayfası açılsın mı?"

        with wx.MessageDialog(self, msg, "Güncelleme Bulundu", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return

        if release_info.get("asset_url"):
            self.download_and_install_update(release_info)
        else:
            webbrowser.open(release_info.get("url") or GITHUB_RELEASES_URL)

    def download_and_install_update(self, release_info):
        if not getattr(sys, "frozen", False):
            speak_or_dialog(
                self,
                "Güncelleme kurulumu yalnızca paketlenmiş exe sürümünde yapılabilir. GitHub sayfası açılıyor.",
                "Güncelleme",
                wx.ICON_INFORMATION,
            )
            webbrowser.open(release_info.get("url") or GITHUB_RELEASES_URL)
            return

        self.SetStatusText("Güncelleme indiriliyor...")
        speak(self, "Güncelleme indiriliyor.")
        threading.Thread(target=self._download_update_thread, args=(release_info,), daemon=True).start()

    def _download_update_thread(self, release_info):
        try:
            target_path = sys.executable
            download_path = os.path.join(BASE_DIR, "Basit_Radyo_update.exe")
            with requests.get(release_info["asset_url"], stream=True, timeout=60) as response:
                response.raise_for_status()
                with open(download_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            wx.CallAfter(self._launch_updater, download_path, target_path)
        except Exception as exc:
            logging.error(f"Güncelleme indirme hatası: {exc}")
            wx.CallAfter(self.SetStatusText, "Boşta")
            wx.CallAfter(
                speak_or_dialog,
                self,
                f"Güncelleme indirilemedi.\n{exc}",
                "Güncelleme Hatası",
                wx.ICON_ERROR,
            )

    def _launch_updater(self, download_path, target_path):
        updater_path = os.path.join(BASE_DIR, "Basit_Radyo_updater.bat")
        app_dir = BASE_DIR
        exe_name = os.path.basename(target_path)
        bat = f"""@echo off
chcp 65001 >nul
timeout /t 2 /nobreak >nul
:waitloop
tasklist /FI "IMAGENAME eq {exe_name}" | find /I "{exe_name}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
copy /Y "{download_path}" "{target_path}" >nul
del "{download_path}" >nul 2>nul
start "" /D "{app_dir}" "{target_path}"
del "%~f0"
"""
        try:
            with open(updater_path, "w", encoding="utf-8") as f:
                f.write(bat)
            speak(self, "Güncelleme kurulumu için program yeniden başlatılıyor.")
            subprocess.Popen(["cmd", "/c", updater_path], cwd=BASE_DIR, creationflags=subprocess.CREATE_NO_WINDOW)
            self.Close()
        except Exception as exc:
            logging.error(f"Güncelleyici başlatma hatası: {exc}")
            speak_or_dialog(self, f"Güncelleyici başlatılamadı.\n{exc}", "Güncelleme Hatası", wx.ICON_ERROR)

    def on_about(self, event):
        about_text = (
            f"Basit Radyo v{APP_VERSION}\n\n"
            "Basit Radyo, internet üzerinden canlı radyo yayınlarını dinlemenizi, "
            "kaydetmenizi ve favori listeleri oluşturmanızı sağlayan sade, "
            "erişilebilir ve işlevsel bir uygulamadır.\n\n"
            "Görme engelli kullanıcılar düşünülerek tasarlanmış bu program, "
            "ekran okuyucularla uyumlu çalışır ve klavye ile kolayca kontrol edilebilir.\n\n"
            "Proje ve fikir sahibi: Mehmet Demir\n"
            "Geliştiriciler: ChatGPT ve Gemini\n\n"
            "İyi dinlemeler!"
        )
        wx.MessageBox(about_text, "Basit Radyo Hakkında", wx.OK | wx.ICON_INFORMATION)

    def on_shutdown(self, event):
        self.Close()

    def on_help_html(self, event):
        help_path = os.path.join(BIN_DIR, "help.html")
        if not os.path.exists(help_path):
            speak_or_dialog(self, "help.html dosyası bulunamadı. Lütfen 'bin' klasörüne ekleyin.", "Yardım Dosyası Bulunamadı", wx.ICON_WARNING)
            return
        try:
            webbrowser.open(help_path)
            speak(self, "Yardım dosyası açılıyor.")
        except Exception as e:
            speak_or_dialog(self, f"Yardım dosyası açılamadı.\nHata: {e}", "Hata", wx.ICON_ERROR)

    def play_last_station_on_startup(self):
        if not config.getboolean("General", "play_on_startup", fallback=False):
            return
        try:
            last_index = config.getint("General", "last_played_index", fallback=-1)
            if 0 <= last_index < len(self.radios):
                view_index = -1
                for i in range(self.list_ctrl.GetItemCount()):
                    if self.list_ctrl.GetItemData(i) == last_index:
                        view_index = i
                        break
                if view_index != -1:
                    self.list_ctrl.Select(view_index)
                    self.list_ctrl.EnsureVisible(view_index)
                    self.toggle_play_pause(view_index)
                    speak(self, "Son çalınan radyo oynatılıyor.")
        except Exception as e:
            logging.error(f"Başlangıçta son radyo çalınırken hata oluştu: {e}")


class MyApp(wx.App):
    def OnInit(self):
        global bass
        logging.info("Basit Radyo başlatılıyor. BASE_DIR=%s", BASE_DIR)
        bass = init_bass()
        self.frame = MainFrame()
        return True


if __name__ == "__main__":
    app = MyApp(False)
    app.MainLoop()
