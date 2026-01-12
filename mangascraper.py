import platform
import threading
import requests
import os
import shutil
import tkinter as tk
from tkinter import messagebox, filedialog
from io import BytesIO
from urllib.parse import urljoin
import json
import sys

# Librerie Esterne
import customtkinter as ctk
from bs4 import BeautifulSoup
from PIL import Image, ImageTk
from ebooklib import epub

# =========================
# CONFIGURAZIONE & UTILS
# =========================

MAX_WIDTH = 1264
MAX_HEIGHT = 1680

APP_VERSION = "1.0.0"


def bring_to_front(win):
    """Bring a Tk/CTk window to the foreground (best-effort).

    macOS sometimes needs a short -topmost toggle to reliably focus.
    """
    try:
        win.lift()
    except Exception:
        pass
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass
    try:
        win.after(200, lambda: (win.attributes("-topmost", False)))
    except Exception:
        pass

def setup_window_centered(win, width, height):
    """Centra la finestra su schermo e la imposta sempre in primo piano."""
    try:
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        # Calcolo coordinate centro
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        
        # Always on top e focus
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
    except Exception:
        pass

# --- COLORI STILE BLUE LOCK / WEB ---
COLOR_PRIMARY = "#3B82F6"      # Blu acceso
COLOR_BG = "#F3F4F6"           # Grigio sfondo
COLOR_CARD = "#FFFFFF"         # Bianco card
COLOR_TEXT = "#1F2937"         # Grigio scuro
COLOR_TEXT_LIGHT = "#6B7280"   # Grigio chiaro

# --- COLORI BADGE (TAGS) ---
BADGE_STATUS_BG = "#DCFCE7"    # Verde chiaro (Sfondo)
BADGE_STATUS_FG = "#166534"    # Verde scuro (Testo)
BADGE_GENRE_BG = "#DBEAFE"     # Blu chiaro (Sfondo)
BADGE_GENRE_FG = "#1E40AF"     # Blu scuro (Testo)

# Provider status badge colors (reuse existing palette)
PROVIDER_ONLINE_BG = BADGE_STATUS_BG
PROVIDER_ONLINE_FG = BADGE_STATUS_FG
PROVIDER_OFFLINE_BG = "#FEE2E2"  # già usato altrove (rosso chiaro)
PROVIDER_OFFLINE_FG = COLOR_TEXT
PROVIDER_UNKNOWN_BG = "#F3F4F6"
PROVIDER_UNKNOWN_FG = COLOR_TEXT_LIGHT

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


def get_app_dir():
    """Return the directory where app data should be stored.

    - When running as a PyInstaller exe, store next to the executable.
    - When running as a script, store next to this file.
    """
    try:
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
    except Exception:
        pass

    base = os.path.abspath(os.path.dirname(__file__))
    # If running from a typical project layout (root/src/mangascraper.py), use root as app dir.
    try:
        if os.path.basename(base).lower() == 'src':
            return os.path.dirname(base)
    except Exception:
        pass
    return base


def get_data_path(filename: str) -> str:
    """Return a writable path for user data files (favorites/meta)."""
    data_dir = os.path.join(get_app_dir(), 'data')
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(data_dir, filename)


def _migrate_data_file(filename: str):
    """Move existing data file into data/ folder (best-effort)."""
    try:
        new_path = get_data_path(filename)
        if os.path.exists(new_path):
            return new_path

        # Old locations we used in previous layouts
        candidates = [
            os.path.join(get_app_dir(), filename),
            os.path.abspath(os.path.dirname(__file__)),
        ]
        old_paths = [
            os.path.join(p, filename) if not p.lower().endswith(filename.lower()) else p
            for p in candidates
        ]
        for old_path in old_paths:
            if old_path != new_path and os.path.exists(old_path):
                try:
                    shutil.move(old_path, new_path)
                except Exception:
                    # If move fails (e.g. cross-device), try copy+remove
                    try:
                        with open(old_path, 'rb') as rf:
                            data = rf.read()
                        with open(new_path, 'wb') as wf:
                            wf.write(data)
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass
                    except Exception:
                        pass
                break
        return new_path
    except Exception:
        return get_data_path(filename)

def resize_for_kindle(image_bytes):
    """Ridimensiona e centra l'immagine per Kindle Paperwhite 7''"""
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        
        # Ridimensionamento
        img_ratio = img.width / img.height
        target_ratio = MAX_WIDTH / MAX_HEIGHT

        if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
            if img_ratio > target_ratio:
                # Limitato dalla larghezza
                new_width = MAX_WIDTH
                new_height = int(MAX_WIDTH / img_ratio)
            else:
                # Limitato dall'altezza
                new_height = MAX_HEIGHT
                new_width = int(MAX_HEIGHT * img_ratio)
            
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Creazione pagina bianca centrata (Opzionale, se vuoi riempire lo schermo)
        # Se preferisci solo l'immagine ridimensionata senza bordi aggiunti, 
        # puoi commentare la parte sotto e ritornare img direttamente.
        
        page = Image.new("RGB", (MAX_WIDTH, MAX_HEIGHT), "white")
        # Calcola posizione per centrare
        x = (MAX_WIDTH - img.width) // 2
        y = (MAX_HEIGHT - img.height) // 2
        page.paste(img, (x, y))

        buf = BytesIO()
        page.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), page # Ritorna bytes e oggetto Image
    except Exception as e:
        print(f"Errore resize: {e}")
        return image_bytes, None

# =========================
# SCRAPER LOGIC
# =========================
class MangaWorld:
    def __init__(self):
        self.url = 'https://www.mangaworld.mx/'
        self.session = requests.Session()
        # Simple in-memory caches to reduce network requests
        self._chapters_cache = {}  # manga_id -> (chapters, cover_url, author, desc, status, genres)
        self._pages_cache = {}     # chapter_id -> [page_urls]
        # persistent meta info (e.g., total chapters) to avoid refetching
        self.meta_file = _migrate_data_file("manga_meta.json")
        self._meta = {}
        try:
            if os.path.exists(self.meta_file):
                with open(self.meta_file, 'r', encoding='utf-8') as mf:
                    data = json.load(mf)
                    # backward compatibility: file may contain only meta dict
                    if isinstance(data, dict) and ('chapters_cache' in data or 'meta' in data):
                        # new format: { 'meta': {...}, 'chapters_cache': {...} }
                        self._meta = data.get('meta', {})
                        self._chapters_cache = data.get('chapters_cache', {})
                    else:
                        self._meta = data
        except Exception:
            self._meta = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
        }

    def fetchDOM(self, url, selector):
        """Fetch a URL and return selected DOM elements and soup."""
        resp = self.session.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.select(selector), soup

    def _save_meta(self):
        """Persist metadata and chapters cache to disk."""
        try:
            # persist both compact meta and the chapters cache to avoid refetching across restarts
            payload = {
                'meta': self._meta,
                'chapters_cache': self._chapters_cache
            }
            with open(self.meta_file, 'w', encoding='utf-8') as mf:
                json.dump(payload, mf, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def getRootRelativeOrAbsoluteLink(self, element, base_url):
        """Resolve a link from an element relative to base URL."""
        href = element.get('href')
        return urljoin(base_url, href)

    def getAbsolutePath(self, element, page_url):
        """Resolve an image source URL."""
        src = element.get('src')
        return urljoin(page_url, src)

    def search_manga(self, keyword):
        """Search for manga by keyword and return list of dicts with id and title."""
        uri = f"{self.url}/archive?keyword={keyword}"
        # Nota: il selettore potrebbe cambiare nel tempo, verifica se il sito aggiorna il DOM
        elements, _ = self.fetchDOM(uri, 'div.comics-grid div.entry div.content a.manga-title')
        
        # Fallback se il selettore precedente non trova nulla (layout alternativi)
        if not elements:
             elements, _ = self.fetchDOM(uri, 'div.comics-grid .entry .content .manga-title')

        return [
            {"id": self.getRootRelativeOrAbsoluteLink(el, self.url), "title": el.text.strip()}
            for el in elements
        ]

    def get_chapters(self, manga):
        """Fetch list of chapters and metadata (cover, author, description, status) for a manga."""
        uri = urljoin(self.url, manga["id"])
        mid = manga.get('id')
        if mid in self._chapters_cache:
            return self._chapters_cache[mid]
        # Selettore capitoli
        elements, soup = self.fetchDOM(uri, 'div.chapters-wrapper div.chapter a.chap')

        # Ricavo della copertina
        cover_img = soup.select_one('div.comic-info img')
        cover_url = None
        if cover_img:
            cover_url = urljoin(self.url, cover_img.get('src'))

        # Ricavo il tag dell'autore
        author_tag = soup.select_one('div.meta-data a[href*="author="]')
        author_name = author_tag.text.strip() if author_tag else "Sconosciuto"

        # Descrizione (MODIFICA: Rimozione parola "TRAMA")
        description_tag = soup.select_one('.has-shadow.comic-description.px-3.mt-4')
        if description_tag:
            raw_text = description_tag.text.strip()
            # Se inizia con TRAMA, lo rimuoviamo
            if raw_text.startswith("TRAMA"):
                description_text = raw_text.replace("TRAMA", "", 1).strip()
            else:
                description_text = raw_text
        else:
            description_text = "-"

        # --- ESTRAZIONE NUOVI DATI (Stato e Generi) ---
        # Stato: Cerca un <a> che contenga "status=" nell'href
        status_tag = soup.select_one('div.meta-data a[href*="status="]')
        status_text = status_tag.text.strip() if status_tag else "Sconosciuto"

        # Generi: Cerca tutti gli <a> che contengono "genre="
        genre_tags = soup.select('div.meta-data a[href*="genre="]')
        genres_list = [g.text.strip() for g in genre_tags]

        chapters = [
            {"id": self.getRootRelativeOrAbsoluteLink(el, self.url),
             "title": el.select_one('span').text.strip() if el.select_one('span') else el.text.strip()}
            for el in elements
        ]
        # Invertiamo per avere l'ordine cronologico (di solito gli elementi vengono dal più recente al più vecchio)
        # Assicuriamoci che la lista sia cronologica (vecchio -> nuovo) in modo che 'next' aumenti l'indice
        try:
            chapters.reverse()
        except Exception:
            pass
        
        result = (chapters, cover_url, author_name, description_text, status_text, genres_list)
        try:
            if mid:
                self._chapters_cache[mid] = result
                # persist total chapters count so we don't need to reload repeatedly
                try:
                    self._meta[mid] = self._meta.get(mid, {})
                    self._meta[mid]['total_chapters'] = len(chapters)
                    self._save_meta()
                except Exception:
                    pass
        except Exception:
            pass
        return result
        
    def get_pages(self, chapter):
        """Fetch image URLs for all pages in a chapter."""
        uri = urljoin(self.url, chapter["id"])
        cid = chapter.get('id')
        if cid in self._pages_cache:
            return self._pages_cache[cid]
        if '?' in uri:
            uri += '&style=list'
        else:
            uri += '?style=list'

        elements, _ = self.fetchDOM(uri, 'div#page img.page-image')
        pages = [self.getAbsolutePath(img, uri) for img in elements]
        try:
            if cid:
                self._pages_cache[cid] = pages
        except Exception:
            pass
        return pages

class MangaReader(ctk.CTkToplevel):
    def __init__(self, parent, chapter_data, scraper_instance, mark_read_callback=None, start_percent=0, start_page=None, is_fullscreen=False):
        """Initialize the manga reader window."""
        super().__init__(parent)
        
        # Gestione priorità finestre:
        # Quando si apre il reader, l'app principale (parent) perde il topmost
        self.parent_app = parent
        try:
            self.parent_app.attributes("-topmost", False)
        except Exception:
            pass
            
        # Gestione chiusura 'X' finestra: ripristina topmost del parent
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # include manga title in window title if available
        try:
            manga_name = getattr(parent, 'current_manga_title', '') or ''
            if manga_name:
                self.title(f"{manga_name} - {chapter_data.get('title','')}")
            else:
                self.title(f"Lettura: {chapter_data.get('title','')}")
        except Exception:
            try:
                self.title(f"Lettura: {chapter_data.get('title','')}")
            except Exception:
                pass
        
        if is_fullscreen:
            try:
                self.attributes('-fullscreen', True)
                self.attributes("-topmost", True)
            except Exception:
                pass
        else:
            setup_window_centered(self, 900, 1000)
        
        self.scraper = scraper_instance
        self.chapter = chapter_data
        self.pages_urls = []
        self.current_index = 0
        self.images_cache = {}
        # Zoom state (1.0 = 100%)
        self.zoom_scale = 1.0
        self.max_zoom = 2.0
        self.min_zoom = 0.5
        
        # Segna come letto automaticamente all'apertura
        # Se viene passato il callback on_chapter_finished, lo riceviamo come kwarg opzionale
        self.on_chapter_finished = None
        self.on_chapter_prev = None
        # starting percent (0-100) to resume reading
        try:
            self.start_percent = int(start_percent) if start_percent is not None else 0
        except Exception:
            self.start_percent = 0
        try:
            self.start_page = None if start_page is None else int(start_page)
        except Exception:
            self.start_page = None
        if isinstance(mark_read_callback, dict):
            # compatibilità: se viene passato un dict (non previsto), ignora
            pass
        # mark_read_callback may be a tuple (mark_cb, finished_cb) in new usage
        if isinstance(mark_read_callback, tuple):
            # support (mark_progress_cb, finished_cb, prev_cb)
            if len(mark_read_callback) >= 2:
                mark_cb, finished_cb = mark_read_callback[0], mark_read_callback[1]
            else:
                mark_cb, finished_cb = (None, None)
            prev_cb = mark_read_callback[2] if len(mark_read_callback) >= 3 else None
            # store the progress callback; the reader will call it with (chapter_id, percent)
            self.mark_progress_cb = mark_cb if callable(mark_cb) else None
            self.on_chapter_finished = finished_cb
            self.on_chapter_prev = prev_cb
        else:
            if mark_read_callback:
                mark_read_callback(chapter_data['id'])

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Barra superiore (HUD) - sticky, visuale minimal
        self.top_bar = ctk.CTkFrame(self, height=56, fg_color=COLOR_CARD, corner_radius=0)
        self.top_bar.grid(row=0, column=0, sticky="ew")
        self.top_bar.grid_columnconfigure(0, weight=1)

        # Left area: back / title
        left_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self.btn_back = ctk.CTkButton(left_frame, text="←", width=36, height=36, fg_color="transparent", text_color=COLOR_TEXT, command=self.destroy)
        self.btn_back.pack(side="left", padx=(0,8))
        # stack manga name (uppercase) above chapter title
        title_stack = ctk.CTkFrame(left_frame, fg_color="transparent")
        title_stack.pack(side="left")
        try:
            manga_name = getattr(parent, 'current_manga_title', '') or ''
            mg_text = manga_name.upper() if manga_name else ''
        except Exception:
            mg_text = ''
        self.lbl_manga_title = ctk.CTkLabel(title_stack, text=mg_text, font=("Inter", 10, "bold"), text_color=COLOR_TEXT_LIGHT)
        self.lbl_manga_title.pack(anchor='w')
        self.lbl_title_small = ctk.CTkLabel(title_stack, text=chapter_data.get('title',''), font=("Inter", 14, "bold"), text_color=COLOR_TEXT)
        self.lbl_title_small.pack(anchor='w')

        # Right actions (chapter selector, settings, fullscreen)
        right_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="e", padx=12, pady=8)
        # Chapter dropdown (shows numbers + titles) - uses OptionMenu for quick selection
        try:
            values = []
            self._chapter_map = {}
            try:
                chapters = self.master.current_chapters_data if hasattr(self.master, 'current_chapters_data') else []
                for i, ch in enumerate(chapters):
                    label = f"#{i+1} - {ch.get('title','')[:60]}"
                    values.append(label)
                    self._chapter_map[label] = ch
            except Exception:
                values = ["Nessuno"]
            if not values:
                values = ["Nessuno"]
            self.chapter_menu = ctk.CTkOptionMenu(right_frame, values=values, command=self._on_chapter_select)
            try:
                # try to set the option to the currently opened chapter
                selected_label = None
                try:
                    for lbl, ch in self._chapter_map.items():
                        if ch.get('id') == chapter_data.get('id'):
                            selected_label = lbl
                            break
                except Exception:
                    selected_label = None
                if selected_label:
                    self.chapter_menu.set(selected_label)
                else:
                    self.chapter_menu.set(values[0])
            except Exception:
                pass
            self.chapter_menu.pack(side="right", padx=(8,0))
        except Exception:
            pass
        self.btn_settings = ctk.CTkButton(right_frame, text="⚙", width=36, height=36, fg_color="transparent", text_color=COLOR_TEXT)
        self.btn_settings.pack(side="right", padx=8)
        self.btn_fullscreen = ctk.CTkButton(right_frame, text="⤢", width=36, height=36, fg_color="transparent", text_color=COLOR_TEXT, command=lambda: self.attributes('-fullscreen', not self.attributes('-fullscreen')))
        self.btn_fullscreen.pack(side="right")

        # 2. Area Immagine principale
        self.main_area = ctk.CTkFrame(self, fg_color=COLOR_BG)
        self.main_area.grid(row=1, column=0, sticky="nsew", padx=0, pady=(6,0))
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        # Center container for image with padding and dark background like reader
        self.image_container = ctk.CTkFrame(self.main_area, fg_color=COLOR_CARD, corner_radius=8)
        self.image_container.grid(row=0, column=0, sticky="nsew", padx=24, pady=12)
        self.image_container.grid_rowconfigure(0, weight=1)
        self.image_container.grid_columnconfigure(0, weight=1)

        self.lbl_image = ctk.CTkLabel(self.image_container, text="", text_color=COLOR_TEXT)
        self.lbl_image.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        # Left and right invisible navigation overlays (hover areas)
        # Parent these to the image_container so they only overlay the image
        self.left_nav = ctk.CTkFrame(self.image_container, fg_color="transparent")
        # cover left 12% of the image container height-wise
        self.left_nav.place(relx=0.0, rely=0.0, relheight=1.0, relwidth=0.12, anchor='nw')
        self.left_nav.bind("<Button-1>", lambda e: self.prev_page())
        self.right_nav = ctk.CTkFrame(self.image_container, fg_color="transparent")
        self.right_nav.place(relx=1.0, rely=0.0, relheight=1.0, relwidth=0.12, anchor='ne')
        self.right_nav.bind("<Button-1>", lambda e: self.next_page())

        # Floating zoom controls (right) - parented to image_container to avoid side-band artifacts
        self.zoom_ctrl = ctk.CTkFrame(self.image_container, fg_color="transparent", corner_radius=0, border_width=0)
        # place at the right inside the image container
        self.zoom_ctrl.place(relx=1.0, rely=0.5, anchor='e', x=-8)
        try:
            # Use transparent buttons container; buttons themselves keep minimal styling
            self.zoom_plus = ctk.CTkButton(self.zoom_ctrl, text="+", width=36, height=36, fg_color=COLOR_PRIMARY, text_color='white', command=lambda: self._adjust_zoom(1))
            self.zoom_plus.pack(pady=4)
            # Make minus/fit use a visible bg so they appear on top of images
            self.zoom_minus = ctk.CTkButton(self.zoom_ctrl, text="-", width=36, height=36, fg_color=COLOR_CARD, text_color=COLOR_TEXT, command=lambda: self._adjust_zoom(-1))
            self.zoom_minus.pack(pady=4)
            self.zoom_fit = ctk.CTkButton(self.zoom_ctrl, text="Fit", width=36, height=28, fg_color=COLOR_CARD, text_color=COLOR_TEXT, command=self._fit_image)
            self.zoom_fit.pack(pady=4)
            # small zoom percent label
            self.zoom_label = ctk.CTkLabel(self.zoom_ctrl, text=f"{int(self.zoom_scale*100)}%", text_color=COLOR_TEXT, font=("Inter",10))
            self.zoom_label.pack(pady=2)
        except Exception:
            pass
        # ensure zoom controls are above the image label so they're visible
        try:
            self.zoom_ctrl.lift()
        except Exception:
            try:
                self.zoom_ctrl.tkraise()
            except Exception:
                pass

        # Bottom HUD: prev / counter / next and a slider-like progress
        self.bottom_hud = ctk.CTkFrame(self, fg_color=COLOR_CARD, height=72, corner_radius=12)
        self.bottom_hud.grid(row=2, column=0, sticky="ew", padx=24, pady=12)
        self.bottom_hud.grid_columnconfigure(0, weight=1)
        self.bottom_hud.grid_columnconfigure(1, weight=1)
        self.bottom_hud.grid_columnconfigure(2, weight=1)

        self.hud_prev = ctk.CTkButton(self.bottom_hud, text="Prev", fg_color=COLOR_PRIMARY, text_color='white', command=self.prev_page)
        self.hud_prev.grid(row=0, column=0, padx=12, pady=12, sticky='w')

        self.hud_center = ctk.CTkFrame(self.bottom_hud, fg_color="transparent")
        self.hud_center.grid(row=0, column=1)
        self.hud_label = ctk.CTkLabel(self.hud_center, text="Pagina 0 di 0", font=("Inter", 12, "bold"), text_color=COLOR_TEXT)
        self.hud_label.pack()
        self.hud_slider = ctk.CTkProgressBar(self.hud_center, orientation="horizontal", mode="determinate", height=8, progress_color=COLOR_PRIMARY)
        self.hud_slider.pack(fill='x', padx=8, pady=(6,0))

        self.hud_next = ctk.CTkButton(self.bottom_hud, text="Next", fg_color=COLOR_PRIMARY, text_color='white', command=self.next_page)
        self.hud_next.grid(row=0, column=2, padx=12, pady=12, sticky='e')

        # Key bindings
        self.bind("<Right>", lambda e: self.next_page())
        self.bind("<Left>", lambda e: self.prev_page())
        # Mouse wheel for zooming when hovering the image area
        try:
            self.lbl_image.bind("<MouseWheel>", self._on_mouse_wheel)
            self.lbl_image.bind("<Button-4>", self._on_mouse_wheel)
            self.lbl_image.bind("<Button-5>", self._on_mouse_wheel)
        except Exception:
            pass

        threading.Thread(target=self.load_pages_list, daemon=True).start()

    def destroy(self):
        """Override destroy to restore parent window priority."""
        try:
            # Ripristina l'app principale sempre in primo piano
            self.parent_app.attributes("-topmost", True)
            self.parent_app.lift()
            self.parent_app.focus_force()
        except Exception:
            pass
        super().destroy()

    def load_pages_list(self):
        """Fetch list of page URLs for the chapter in a background thread."""
        try:
            self.pages_urls = self.scraper.get_pages(self.chapter)
            if self.pages_urls:
                self.after(0, self.enable_controls)
                # compute start index from saved page or percent if provided
                try:
                    total = len(self.pages_urls)
                    idx = 0
                    if hasattr(self, 'start_page') and self.start_page is not None:
                        # clamp
                        try:
                            idx = max(0, min(self.start_page, total - 1))
                        except Exception:
                            idx = 0
                    else:
                        try:
                            pct = max(0, min(100, int(self.start_percent)))
                        except Exception:
                            pct = 0
                        idx = min(total - 1, max(0, int((total * pct) / 100))) if total else 0
                except Exception:
                    idx = 0
                self.load_image_index(idx)
            else:
                self.after(0, lambda: self.hud_label.configure(text="Nessuna pagina trovata."))
        except Exception as e:
            print(f"Errore reader: {e}")

    def enable_controls(self):
        """Enable navigation buttons once pages are loaded."""
        try:
            self.hud_next.configure(state="normal")
            self.hud_prev.configure(state="normal")
        except Exception:
            pass
        self.update_info_label()

    def update_info_label(self):
        """Update HUD labels (page counter, zoom percent) and slider."""
        try:
            total = len(self.pages_urls)
            # chapter completion percent (1-based page index)
            chapter_pct = int(((self.current_index + 1) / max(1, total)) * 100) if total else 0
            zoom_pct = int(self.zoom_scale * 100)
            try:
                # Show chapter completion percent in HUD; zoom percent shown on zoom label
                self.hud_label.configure(text=f"Pagina {self.current_index + 1} di {total}  ({chapter_pct}%)")
            except Exception:
                pass
            try:
                self.hud_slider.set((self.current_index + 1) / max(1, total))
            except Exception:
                pass
            # Aggiorna testo del bottone next quando siamo all'ultima pagina (HUD)
            try:
                if self.current_index >= total - 1:
                    self.hud_next.configure(text="Capitolo successivo")
                else:
                    self.hud_next.configure(text="Next")
            except Exception:
                pass
            # persist reading progress for the current chapter (if callback provided)
            try:
                if hasattr(self, 'mark_progress_cb') and callable(self.mark_progress_cb):
                    try:
                        # pass chapter id, percent, and current page index
                        self.mark_progress_cb(self.chapter.get('id'), chapter_pct, self.current_index)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

    def load_image_index(self, index):
        """Load and display a specific page index."""
        if index < 0 or index >= len(self.pages_urls): return
        self.current_index = index
        self.update_info_label()
        self.lbl_image.configure(image=None, text="Caricamento...")
        threading.Thread(target=self._download_and_show, args=(index,), daemon=True).start()

    def _download_and_show(self, index):
        """Background worker to download image data and prepare CTkImage."""
        url = self.pages_urls[index]
        if url in self.images_cache:
            entry = self.images_cache[url]
            img_ctk = entry.get('ctk')
        else:
            try:
                resp = requests.get(url, headers=self.scraper.headers)
                img_data = Image.open(BytesIO(resp.content)).convert('RGB')
                win_h = self.main_area.winfo_height()
                if win_h < 100: win_h = 800
                ratio = img_data.width / img_data.height if img_data.height else 1
                new_h = win_h - 20
                new_w = int(new_h * ratio)
                # keep a copy of the PIL image and the base display size for zooming
                try:
                    pil_copy = img_data.copy()
                except Exception:
                    pil_copy = img_data
                resized = pil_copy.resize((new_w, new_h), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=resized, size=(new_w, new_h))
                # store original PIL size for accurate zooming
                self.images_cache[url] = {"pil": pil_copy, "orig_size": (pil_copy.width, pil_copy.height), "ctk": ctk_img}
                img_ctk = ctk_img
            except Exception: return
        self.after(0, lambda: self._display_image(img_ctk))

    def _display_image(self, img):
        """Update the UI with the prepared image."""
        try:
            self.lbl_image.configure(text="", image=img)
        except Exception:
            try:
                self.lbl_image.configure(image=img)
            except Exception:
                pass
        # update HUD info and progress when an image is displayed
        try:
            # Use centralized updater to ensure consistent behavior
            self.update_info_label()
        except Exception:
            pass

    def _on_mouse_wheel(self, event):
        """Handle mouse wheel events for zooming the image."""
        try:
            delta = 0
            if hasattr(event, 'delta') and event.delta:
                # Windows: delta usually multiples of 120
                delta = event.delta / 120
            elif str(event.type) == '4' or getattr(event, 'num', None) == 4:
                delta = 1
            elif getattr(event, 'num', None) == 5:
                delta = -1
            if delta == 0:
                return
            # adjust zoom step
            step = 0.1
            new_zoom = self.zoom_scale + (step * (1 if delta > 0 else -1))
            new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
            if abs(new_zoom - self.zoom_scale) < 1e-6:
                return
            self.zoom_scale = new_zoom
            # Recreate CTkImage for current page using stored PIL
            try:
                if not self.pages_urls or self.current_index >= len(self.pages_urls):
                    return
                url = self.pages_urls[self.current_index]
                entry = self.images_cache.get(url)
                if not entry:
                    return
                pil = entry.get('pil')
                orig_w, orig_h = entry.get('orig_size', (pil.width, pil.height))
                new_w = max(1, int(orig_w * self.zoom_scale))
                new_h = max(1, int(orig_h * self.zoom_scale))
                resized = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=resized, size=(new_w, new_h))
                entry['ctk'] = ctk_img
                # update display
                self.lbl_image.configure(text="", image=ctk_img)
                # update HUD label/slider and zoom label
                try:
                    self.update_info_label()
                except Exception:
                    pass
                try:
                    if hasattr(self, 'zoom_label'):
                        self.zoom_label.configure(text=f"{int(self.zoom_scale*100)}%")
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _on_chapter_select(self, selection):
        """Handle chapter selection from the dropdown menu."""
        try:
            if not selection:
                return
            ch = None
            try:
                ch = self._chapter_map.get(selection)
            except Exception:
                ch = None
            if ch:
                # Delegate to parent to open the selected chapter (it will destroy this reader)
                try:
                    self.master.start_reading_chapter(ch)
                except Exception:
                    pass
        except Exception:
            pass

    def _adjust_zoom(self, delta):
        """Increase or decrease zoom scale by delta."""
        try:
            step = 0.1
            new_zoom = self.zoom_scale + (step if delta > 0 else -step)
            new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
            if abs(new_zoom - self.zoom_scale) < 1e-6:
                return
            self.zoom_scale = new_zoom
            # reuse mouse wheel logic to re-render
            try:
                if not self.pages_urls or self.current_index >= len(self.pages_urls):
                    return
                url = self.pages_urls[self.current_index]
                entry = self.images_cache.get(url)
                if not entry:
                    return
                pil = entry.get('pil')
                orig_w, orig_h = entry.get('orig_size', (pil.width, pil.height))
                new_w = max(1, int(orig_w * self.zoom_scale))
                new_h = max(1, int(orig_h * self.zoom_scale))
                resized = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=resized, size=(new_w, new_h))
                entry['ctk'] = ctk_img
                self.lbl_image.configure(text="", image=ctk_img)
                try:
                    self.update_info_label()
                except Exception:
                    pass
                try:
                    if hasattr(self, 'zoom_label'):
                        self.zoom_label.configure(text=f"{int(self.zoom_scale*100)}%")
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _set_zoom(self, value):
        """Set an exact zoom scale."""
        try:
            self.zoom_scale = max(self.min_zoom, min(self.max_zoom, float(value)))
            # force re-render via adjust with delta 0-like behavior
            try:
                url = self.pages_urls[self.current_index]
                entry = self.images_cache.get(url)
                if not entry:
                    return
                pil = entry.get('pil')
                orig_w, orig_h = entry.get('orig_size', (pil.width, pil.height))
                new_w = max(1, int(orig_w * self.zoom_scale))
                new_h = max(1, int(orig_h * self.zoom_scale))
                resized = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=resized, size=(new_w, new_h))
                entry['ctk'] = ctk_img
                self.lbl_image.configure(text="", image=ctk_img)
                try:
                    self.update_info_label()
                except Exception:
                    pass
                try:
                    if hasattr(self, 'zoom_label'):
                        self.zoom_label.configure(text=f"{int(self.zoom_scale*100)}%")
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _fit_image(self):
        """Adjust zoom to fit the image within the window."""
        try:
            if not self.pages_urls or self.current_index >= len(self.pages_urls):
                return
            url = self.pages_urls[self.current_index]
            entry = self.images_cache.get(url)
            if not entry:
                return
            pil = entry.get('pil')
            orig_w, orig_h = entry.get('orig_size', (pil.width, pil.height))
            # determine available container size
            try:
                cont_w = max(10, self.image_container.winfo_width() - 24)
                cont_h = max(10, self.image_container.winfo_height() - 24)
            except Exception:
                cont_w, cont_h = 800, 900
            # compute scale to fit while preserving aspect
            scale_w = cont_w / orig_w
            scale_h = cont_h / orig_h
            scale = min(scale_w, scale_h, self.max_zoom)
            scale = max(self.min_zoom, scale)
            self.zoom_scale = scale
            new_w = max(1, int(orig_w * self.zoom_scale))
            new_h = max(1, int(orig_h * self.zoom_scale))
            resized = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=resized, size=(new_w, new_h))
            entry['ctk'] = ctk_img
            self.lbl_image.configure(text="", image=ctk_img)
            try:
                self.update_info_label()
            except Exception:
                pass
            try:
                if hasattr(self, 'zoom_label'):
                    self.zoom_label.configure(text=f"{int(self.zoom_scale*100)}%")
            except Exception:
                pass
        except Exception:
            pass

    def next_page(self):
        """Go to the next page, or trigger next chapter callback if at end."""
        if self.current_index < len(self.pages_urls) - 1:
            self.load_image_index(self.current_index + 1)
        else:
            # Fine del capitolo: se fornito, chiamiamo il callback per aprire il capitolo successivo
            try:
                if callable(self.on_chapter_finished):
                    cid = self.chapter.get('id')
                    # Chiamiamo la callback PRIMA di distruggere la finestra per evitare race
                    try:
                        self.on_chapter_finished(cid)
                    except Exception as e:
                        pass
                    # Distruggi la finestra reader (se ancora esiste)
                    try:
                        if self.winfo_exists():
                            self.destroy()
                    except Exception:
                        pass
            except Exception:
                try:
                    self.destroy()
                except Exception:
                    pass
    
    def prev_page(self):
        """Go to the previous page, or trigger prev chapter callback if at start."""
        if self.current_index > 0:
            self.load_image_index(self.current_index - 1)
        else:
            # All first page: if provided, call previous-chapter callback
            try:
                if callable(self.on_chapter_prev):
                    cid = self.chapter.get('id')
                    try:
                        self.on_chapter_prev(cid)
                    except Exception as e:
                        pass
                    try:
                        if self.winfo_exists():
                            self.destroy()
                    except Exception:
                        pass
            except Exception:
                try:
                    self.destroy()
                except Exception:
                    pass

class ChapterSelector(ctk.CTkToplevel):
    def __init__(self, parent, chapters_data, on_select_callback, progress_map=None):
        super().__init__(parent)
        self.title("Seleziona Capitolo da Leggere")
        setup_window_centered(self, 400, 600)
        self.chapters = chapters_data
        self.on_select = on_select_callback
        # progress_map: dict chapter_id -> percent (0-100), optional
        self.progress_map = progress_map or {}
        
        # Barra di ricerca
        self.search_var = ctk.StringVar()
        self.search_var.trace("w", self.filter_list)
        self.entry_filter = ctk.CTkEntry(self, placeholder_text="Filtra capitolo (es. 10)", textvariable=self.search_var)
        self.entry_filter.pack(fill="x", padx=10, pady=10)

        # Scroll area
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.populate(self.chapters)

    def populate(self, data):
        """Create buttons for each chapter in the scrollable list."""
        # Pulisce vecchi widget
        for w in self.scroll.winfo_children(): w.destroy()
        
        # Crea bottoni per tutti i capitoli (se necessario si può reintrodurre un limite)
        for chap in data:
            # show per-chapter progress in this selector without touching sidebar
            val = self.progress_map.get(chap.get('id'), 0)
            # support either stored int percent or dict {percent,page}
            if isinstance(val, dict):
                pct = val.get('percent', 0)
            else:
                try:
                    pct = int(val)
                except Exception:
                    pct = 0
            title = chap['title']
            if pct:
                title = f"{title} ({pct}%)"
            fg = "transparent"
            txt = "black"
            if pct >= 100:
                # dim fully-read chapters
                fg = "#F3F4F6"
                txt = COLOR_TEXT_LIGHT
            btn = ctk.CTkButton(
                self.scroll,
                text=title,
                fg_color=fg,
                border_width=1,
                border_color="#E5E7EB",
                text_color=txt,
                hover_color="#DBEAFE",
                anchor="w",
                command=lambda c=chap: self.select_chapter(c)
            )
            btn.pack(fill="x", pady=2)
            

    def filter_list(self, *args):
        """Filter the chapter list based on search entry."""
        query = self.search_var.get().lower()
        if not query:
            self.populate(self.chapters)
        else:
            filtered = [c for c in self.chapters if query in c['title'].lower()]
            self.populate(filtered)

    def select_chapter(self, chapter):
        """Invoke callback with selected chapter and close window."""
        self.destroy() # Chiude il popup
        self.on_select(chapter) # Avvia la lettura


class ChapterDownloadSelector(ctk.CTkToplevel):
    def __init__(self, parent, chapters_data, on_confirm_callback):
        super().__init__(parent)
        self.title("Seleziona capitoli da scaricare")
        self.geometry("500x600")
        self.chapters = chapters_data or []
        self.on_confirm = on_confirm_callback

        self.vars = []

        lbl = ctk.CTkLabel(self, text="Seleziona i capitoli da includere nel download", font=("Inter", 12, "bold"))
        lbl.pack(anchor="w", padx=10, pady=(10,5))

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0,10))

        for ch in self.chapters:
            v = ctk.BooleanVar(value=False)
            self.vars.append((v, ch))
            # customtkinter.CTkCheckBox does not accept 'anchor' kwarg; use pack options instead
            chk = ctk.CTkCheckBox(self.scroll, text=ch.get('title', ''), variable=v)
            chk.pack(fill='x', pady=2, padx=5)

        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill='x', padx=10, pady=10)
        
        # Pulsante Annulla (Sinistra)
        ctk.CTkButton(ctrl, text="Annulla", command=self.destroy, fg_color=COLOR_PRIMARY).pack(side='left')
        
        # Pulsante Conferma (Destra)
        ctk.CTkButton(ctrl, text="Conferma", command=self._on_confirm, fg_color=COLOR_PRIMARY).pack(side='right')

        setup_window_centered(self, 500, 600)

    def _on_confirm(self):
        """Collect selected chapters and invoke confirmation callback."""
        # Disabilita topmost su popup e main window per evitare freeze con filedialog
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass
        try:
            if self.master:
                self.master.attributes("-topmost", False)
        except Exception:
            pass

        selected = [ch for (v, ch) in self.vars if v.get()]
        try:
            self.on_confirm(selected)
        except Exception:
            pass
        self.destroy()
# =========================
# GUI LOGIC
# =========================
class MangaWorldGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configurazione Finestra
        self.title("MangaScraper - Downloader & Reader")
        setup_window_centered(self, 1250, 1100)
        self.configure(fg_color=COLOR_BG)

        # --- CARICAMENTO LOGO/ICONA (logo.png) ---
        try:
            # Cerca logo.png nella cartella assets
            logo_path = os.path.join(get_app_dir(), "assets", "logo.png")
            if not os.path.exists(logo_path):
                 # Fallback per compatibilità (se fosse nella root)
                 logo_path = os.path.join(get_app_dir(), "logo.png")

            if os.path.exists(logo_path):
                icon_img = Image.open(logo_path)
                # Imposta icona della finestra
                icon_photo = ImageTk.PhotoImage(icon_img)
                self.wm_iconphoto(False, icon_photo)
                # Mantiene riferimento per evitare garbage collection
                self._app_icon = icon_photo
        except Exception as e:
            print(f"[WARN] Impossibile caricare logo.png: {e}")

        # Inizializzazione Logica Backend
        self.mw = MangaWorld()
        
        self.manga_list_data = []
        self.chapter_widgets = [] 
        self.current_manga_title = ""
        self.current_cover_url = None
        self.current_author = ""
        self.current_manga_id = None

        # favorites storage
        self.favorites = []
        self.fav_file = _migrate_data_file("favorites.json")
        # Persistent reference to the CTkImage to avoid Tkinter 'pyimage' GC/race errors
        self.cover_ctk_img = None

        # UI generation token to ignore stale background updates (e.g., after clicking "Svuota")
        self._ui_token = 0
        self._active_manga_request_id = None
        self._active_manga_request_token = None

        # Provider status (online/offline) state
        self._providers = {
            "MangaWorld": "https://www.mangaworld.mx/",
        }

        self._provider_status = {k: None for k in self._providers.keys()}  # None=unknown, True=online, False=offline
        self._provider_badges = {}
        self._provider_check_interval_ms = 60_000

        # Live search dropdown (tendina)
        self._suggest_after_id = None
        self._suggest_token = 0
        self._suggest_max_items = 10

        # Layout Griglia Principale
        self.grid_columnconfigure(1, weight=1)
        # row 0: top search bar, row 1: main content (sidebar + main)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._init_top_bar()
        self._start_provider_status_checks()

        self._init_sidebar()
        # load favorites after sidebar exists
        try:
            self.load_favorites()
        except Exception:
            self.favorites = []
        self._init_main_area()

        # Footer with author and version
        try:
            # Ensure a non-stretching row for footer
            try:
                self.grid_rowconfigure(2, weight=0)
            except Exception:
                pass
            footer = ctk.CTkFrame(self, fg_color="transparent")
            footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0,12))
            lbl_left = ctk.CTkLabel(footer, text="Creato da Larus54", text_color=COLOR_TEXT_LIGHT, font=("Inter", 10))
            lbl_left.pack(side="left")

            # Right side container for Version + Beta Badge
            ver_box = ctk.CTkFrame(footer, fg_color="transparent")
            ver_box.pack(side="right")
            
            # Beta Badge (Styled like chapter pills)
            lbl_beta = ctk.CTkLabel(
                ver_box, 
                text="BETA", 
                text_color=BADGE_GENRE_FG, 
                fg_color=BADGE_GENRE_BG, 
                font=("Inter", 9, "bold"), 
                corner_radius=4,
                padx=6, 
                pady=1
            )
            lbl_beta.pack(side="left", padx=(0, 8))
            # Version Label

                        # OS Badge (Requested)
            os_name = "MACOS" if platform.system() == 'Darwin' else platform.system().upper()
            lbl_os = ctk.CTkLabel(
                ver_box,
                text=os_name,
                text_color=BADGE_GENRE_FG,
                fg_color=BADGE_GENRE_BG,
                font=("Inter", 9, "bold"),
                corner_radius=4,
                padx=6,
                pady=1
            )
            lbl_os.pack(side="left", padx=(0, 8))
            lbl_version = ctk.CTkLabel(ver_box, text=f"Versione {APP_VERSION}", text_color=COLOR_TEXT_LIGHT, font=("Inter", 10))
            lbl_version.pack(side="left")
        except Exception:
            pass

        # Initial UI state: no manga selected yet
        try:
            self._set_manga_details_visible(False)
        except Exception:
            pass

        # Ensure the app starts in the foreground
        # Non richiamiamo bring_to_front qui perché resetterebbe topmost=False. 
        # setup_window_centered ha già impostato topmost=True.
                    
    def _init_top_bar(self):
        """Top search bar (provider + search + actions), styled after the provided mock."""
        self.top_bar = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=15)
        self.top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(20, 10))
        self.top_bar.grid_columnconfigure(1, weight=1)

        # Colore di sfondo per simulare l'input del web (Grigio chiarissimo)
        INPUT_BG_COLOR = "#F9FAFB"
        
        # Altezza uniforme per tutti gli elementi della barra
        BAR_HEIGHT = 52

        # --- ROW 0: HEADER (Status & Title) ---
        header_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent", height=30)
        header_frame.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(15, 5))
        
        ctk.CTkLabel(header_frame, text="RICERCA & STATO", font=("Inter", 12, "bold"), text_color=COLOR_TEXT_LIGHT).pack(side="left")

        status_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        status_box.pack(side="right")
        
        # Label "STATO SERVER"
        ctk.CTkLabel(status_box, text="STATO SERVER:", font=("Inter", 10, "bold"), text_color=COLOR_TEXT_LIGHT).pack(side="left", padx=(0, 10))
        
        # Container for pills
        self.provider_status_row = ctk.CTkFrame(status_box, fg_color="transparent")
        self.provider_status_row.pack(side="left")

        # Create Badges inside header
        self._provider_badges = {}
        for provider_name in self._providers.keys():
            badge = ctk.CTkLabel(
                self.provider_status_row,
                text=f"{provider_name}: ...",
                fg_color=PROVIDER_UNKNOWN_BG,
                text_color=PROVIDER_UNKNOWN_FG,
                font=("Inter", 11, "bold"),
                corner_radius=6,
                padx=8,
                pady=2, # More compact
            )
            badge.pack(side="left", padx=(0, 6))
            self._provider_badges[provider_name] = badge


        # --- ROW 1: CONTROLS (Provider Selection + Search + Buttons) ---

        # --- 1. PROVIDER SECTION (Custom Styled Box) ---
        provider_container = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        provider_container.grid(row=1, column=0, sticky="w", padx=(20, 10), pady=(5, 20))

        # Box contenitore
        self.provider_box = ctk.CTkFrame(provider_container, 
                                         fg_color=INPUT_BG_COLOR,
                                         border_width=1, 
                                         border_color="#E5E7EB", 
                                         width=200,                
                                         height=BAR_HEIGHT,
                                         corner_radius=8)
        self.provider_box.pack()
        # Importante: blocca il ridimensionamento per usare .place()
        self.provider_box.grid_propagate(False) 

        # Etichetta "PROVIDER" - Spostata giù a y=6 per evitare il taglio superiore
        ctk.CTkLabel(self.provider_box, 
                     text="PROVIDER", 
                     font=("Inter", 9, "bold"),
                     text_color=COLOR_PRIMARY,
                     bg_color="transparent",
                     height=12).place(x=12, y=6) 

        # Dropdown Menu - Spostato giù a y=22 per non sovrapporsi
        self.provider_var = ctk.StringVar(value="🇮🇹 MangaWorld")
        self.provider_menu = ctk.CTkOptionMenu(self.provider_box, 
                                               values=["🇮🇹 MangaWorld", "Coming Soon..."], 
                                               variable=self.provider_var,
                                               fg_color=INPUT_BG_COLOR,
                                               button_color=INPUT_BG_COLOR,
                                               button_hover_color=INPUT_BG_COLOR,
                                               text_color=COLOR_TEXT,
                                               font=("Inter", 13, "bold"),
                                               dropdown_fg_color=COLOR_CARD,
                                               dropdown_text_color=COLOR_TEXT,
                                               width=180,
                                               height=24, # Altezza ridotta per stare nel box
                                               anchor="w")
        self.provider_menu.place(x=8, y=22)


        # --- 2. SEARCH ENTRY (Aligned) ---
        search_wrap = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        search_wrap.grid(row=1, column=1, sticky="ew", padx=10, pady=(5, 20))
        search_wrap.grid_columnconfigure(0, weight=1)
        
        self.search_entry = ctk.CTkEntry(search_wrap, 
                                         placeholder_text="Cerca titolo del manga...", 
                                         border_color="#E5E7EB", 
                                         fg_color=INPUT_BG_COLOR,
                                         text_color=COLOR_TEXT,
                                         height=BAR_HEIGHT, 
                                         font=("Inter", 13))
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self.search_thread())

        # Dropdown results (tendina) shown while typing - Using Toplevel for guaranteed z-index
        self.search_dropdown = ctk.CTkToplevel(self)
        self.search_dropdown.withdraw()
        self.search_dropdown.overrideredirect(True)
        # On macOS a topmost overrideredirect Toplevel can sometimes keep intercepting clicks
        # even after being withdrawn; we toggle -topmost only while visible.
        try:
            self.search_dropdown.attributes("-topmost", False)
        except Exception:
            pass
        try:
            self.search_dropdown.transient(self)
        except Exception:
            pass
        self.search_dropdown.configure(fg_color=COLOR_CARD)
        
        # Track buttons to clear them properly without destroying internal frame structures
        self._search_result_widgets = []

        self.search_dropdown_scroll = ctk.CTkScrollableFrame(
            self.search_dropdown,
            fg_color="transparent",
        )
        self.search_dropdown_scroll.pack(fill="both", expand=True, padx=2, pady=2)

        self.search_entry.bind("<KeyRelease>", self._on_search_key_release)
        # Hide tendina when clicking outside
        try:
            self.bind("<Button-1>", self._on_global_click, add="+")
            self.bind("<Configure>", self._on_window_move, add="+")
        except Exception:
            pass

        # --- 3. ACTIONS ---
        actions = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        actions.grid(row=1, column=2, sticky="e", padx=(10, 20), pady=(5, 20))
        
        # Pulsante Cerca rimosso su richiesta (ricerca automatica)
                      
        ctk.CTkButton(actions, text="Svuota", fg_color=COLOR_PRIMARY, 
                      text_color="white", # Prima era COLOR_TEXT
                      height=BAR_HEIGHT, width=100, font=("Inter", 13, "bold"),
                      command=self.clear_all).pack(side="left")

    def _bump_suggest_token(self):
        """Increment and return the suggestion token to invalidate old requests."""
        try:
            self._suggest_token += 1
        except Exception:
            self._suggest_token = 1
        return self._suggest_token

    def _ensure_search_dropdown(self):
        """Ensure the search dropdown window exists.

        On macOS, an overrideredirect/topmost Toplevel may sometimes keep intercepting
        clicks even after withdraw(). To make this robust we recreate it when needed.
        """
        try:
            dd = getattr(self, 'search_dropdown', None)
            try:
                if dd is not None and dd.winfo_exists():
                    return
            except Exception:
                pass

            self.search_dropdown = ctk.CTkToplevel(self)
            self.search_dropdown.withdraw()
            self.search_dropdown.overrideredirect(True)
            try:
                self.search_dropdown.attributes("-topmost", False)
            except Exception:
                pass
            try:
                self.search_dropdown.transient(self)
            except Exception:
                pass
            self.search_dropdown.configure(fg_color=COLOR_CARD)

            # Track widgets to clear them cleanly
            self._search_result_widgets = []

            self.search_dropdown_scroll = ctk.CTkScrollableFrame(
                self.search_dropdown,
                fg_color="transparent",
            )
            self.search_dropdown_scroll.pack(fill="both", expand=True, padx=2, pady=2)
        except Exception:
            self.search_dropdown = None
            self.search_dropdown_scroll = None

    def _show_search_dropdown(self, height=None, update_only=False):
        """Show and position the search suggestions dropdown."""
        try:
            self._ensure_search_dropdown()
            if getattr(self, 'search_dropdown', None) is None:
                return
            # Use absolute screen coordinates for Toplevel
            x = self.search_entry.winfo_rootx()
            y = self.search_entry.winfo_rooty() + self.search_entry.winfo_height() + 5
            w = self.search_entry.winfo_width()
            
            if height:
                h = height
            else:
                 h = self.search_dropdown.winfo_height()
                 if h < 10: h = 200

            # Update geometry
            self.search_dropdown.geometry(f"{w}x{h}+{x}+{y}")
            
            if not update_only:
                try:
                    self.search_dropdown.attributes("-topmost", True)
                except Exception:
                    pass
                self.search_dropdown.deiconify()
                self.search_dropdown.lift()
        except Exception as e:
            print(f"Dropdown error: {e}")

    def _hide_search_dropdown(self):
        """Hidden safely the search suggestions dropdown."""
        # On macOS, be aggressive: destroy the dropdown so it cannot keep intercepting clicks.
        dd = getattr(self, 'search_dropdown', None)
        try:
            if dd is not None:
                try:
                    dd.attributes("-topmost", False)
                except Exception:
                    pass
                try:
                    dd.withdraw()
                except Exception:
                    pass
                try:
                    dd.destroy()
                except Exception:
                    pass
        finally:
            self.search_dropdown = None
            self.search_dropdown_scroll = None
            try:
                self._search_result_widgets = []
            except Exception:
                pass

    def _clear_search_dropdown(self):
        """Remove all suggestion items from the dropdown."""
        try:
            widgets = getattr(self, '_search_result_widgets', [])
            for w in widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._search_result_widgets = []
        except Exception:
            pass

    def _populate_search_dropdown(self, results, token, query):
        """Fill the dropdown with search results."""
        # Ensure dropdown exists (it may have been destroyed after a previous selection)
        self._ensure_search_dropdown()
        if getattr(self, 'search_dropdown_scroll', None) is None:
            return

        # Only apply if still current
        try:
            current = getattr(self, '_suggest_token', 0)
            if token != current:
                return
        except Exception:
            return

        self._clear_search_dropdown()

        if not results:
            if query and len(query) > 1:
                # Show no results message
                lbl = ctk.CTkLabel(
                    self.search_dropdown_scroll, 
                    text="Nessun risultato trovato", 
                    text_color=COLOR_TEXT_LIGHT,
                    font=("Inter", 12, "italic")
                )
                lbl.pack(pady=10)
                # Keep track of it so it gets cleared
                if not hasattr(self, '_search_result_widgets'):
                    self._search_result_widgets = []
                self._search_result_widgets.append(lbl)
                self._show_search_dropdown(height=50)
            else:
                self._hide_search_dropdown()
            return

        # Calculate Height dynamically
        row_h = 32
        total_h = min(len(results) * row_h + 24, 400) # Max height 400

        # Ensure widgets list exists
        if not hasattr(self, '_search_result_widgets'):
            self._search_result_widgets = []

        # Show more items if it's a full search
        for manga in results:
            def make_row(m=manga):
                btn = ctk.CTkButton(
                    self.search_dropdown_scroll,
                    text=m.get('title', ''),
                    fg_color="transparent",
                    text_color=COLOR_TEXT,
                    hover_color="#E0F2FE",
                    anchor="w",
                    height=28,
                    command=lambda: self._open_manga_from_suggestion(m),
                )
                btn.pack(fill="x", pady=1)
                self._search_result_widgets.append(btn)

            make_row()

        self._show_search_dropdown(height=total_h)

    def _open_manga_from_suggestion(self, manga):
        """Handle click on a search suggestion."""
        try:
            # Put the selected title into the entry (nice for clarity)
            self.search_entry.delete(0, 'end')
            self.search_entry.insert(0, manga.get('title', ''))
        except Exception:
            pass
        self._hide_search_dropdown()
        token = getattr(self, '_ui_token', 0)
        threading.Thread(target=self.load_chapters_for_manga, args=(manga, token), daemon=True).start()

    def _on_search_key_release(self, event=None):
        """Handle typing in search box with debounce."""
        query = (self.search_entry.get() or '').strip()
        token = self._bump_suggest_token()

        # cancel previous debounce
        try:
            if self._suggest_after_id is not None:
                self.after_cancel(self._suggest_after_id)
        except Exception:
            pass
        self._suggest_after_id = None

        if not query:
            self._clear_search_dropdown()
            self._hide_search_dropdown()
            return

        def run():
            self._suggest_after_id = None
            threading.Thread(target=self._suggest_search_worker, args=(query, token), daemon=True).start()

        try:
            self._suggest_after_id = self.after(250, run)
        except Exception:
            run()

    def _suggest_search_worker(self, query: str, token: int):
        """Background thread for fetching search suggestions."""
        try:
            results = self.mw.search_manga(query)
        except Exception:
            results = []

        try:
            self.after(0, lambda: self._populate_search_dropdown(results, token, query))
        except Exception:
            pass

    def _is_descendant(self, widget, ancestor) -> bool:
        """Check if widget is a descendant of ancestor."""
        try:
            if ancestor is None:
                return False
            w = widget
            while w is not None:
                if w == ancestor:
                    return True
                w = getattr(w, 'master', None)
        except Exception:
            return False
        return False
    
    def _on_window_move(self, event):
        """Update dropdown position when main window moves."""
        try:
                # Only react if the main window moved (event.widget is self)
            if event.widget == self:
                 dd = getattr(self, 'search_dropdown', None)
                 if dd is not None and dd.winfo_exists() and dd.winfo_viewable():
                     self._show_search_dropdown(update_only=True)
        except Exception:
            pass

    def _on_global_click(self, event):
        try:
            w = event.widget
            # customtkinter wraps widgets; on macOS the click target can be an internal Entry widget.
            if self._is_descendant(w, self.search_entry) or w == self.search_entry or self._is_descendant(w, self.search_dropdown):
                return
            self._hide_search_dropdown()
        except Exception:
            pass

    def _set_provider_badge(self, provider_name: str, status):
        """Update a provider badge. status: None=unknown, True=online, False=offline."""
        badge = self._provider_badges.get(provider_name)
        if not badge:
            return

        if status is True:
            badge.configure(
                text=f"{provider_name}: Online",
                fg_color=PROVIDER_ONLINE_BG,
                text_color=PROVIDER_ONLINE_FG,
            )
        elif status is False:
            badge.configure(
                text=f"{provider_name}: Offline",
                fg_color=PROVIDER_OFFLINE_BG,
                text_color=PROVIDER_OFFLINE_FG,
            )
        else:
            badge.configure(
                text=f"{provider_name}: ...",
                fg_color=PROVIDER_UNKNOWN_BG,
                text_color=PROVIDER_UNKNOWN_FG,
            )

    def _start_provider_status_checks(self):
        """Kick off periodic provider HTTP checks (non-blocking)."""
        # Set all badges to unknown initially
        try:
            for name in self._providers.keys():
                self._set_provider_badge(name, None)
        except Exception:
            pass

        def tick():
            self._check_providers_async()
            try:
                self.after(self._provider_check_interval_ms, tick)
            except Exception:
                pass

        # first run immediately
        tick()

    def _check_providers_async(self):
        """Run provider status checks in a background thread and update UI safely."""
        def worker():
            statuses = {}
            for name, url in self._providers.items():
                if not url:
                    statuses[name] = False
                    continue
                try:
                    # Keep it lightweight and fast; treat 4xx/3xx as 'online'
                    resp = self.mw.session.get(url, headers=self.mw.headers, timeout=6)
                    statuses[name] = bool(resp.status_code and resp.status_code < 500)
                except Exception:
                    statuses[name] = False

            def apply():
                for name, st in statuses.items():
                    self._provider_status[name] = st
                    try:
                        self._set_provider_badge(name, st)
                    except Exception:
                        pass

            try:
                self.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
                
    def _populate_chapters(self, chapters):
        """Populate the sidebar chapter list with checkboxes (async batching)."""
        # Generazione token per invalidare batch precedenti
        self._populate_token = getattr(self, '_populate_token', 0) + 1
        current_token = self._populate_token

        # 1. Recuperiamo la lista dei capitoli già letti
        read_list = []
        if self.current_manga_id:
            for fav in self.favorites:
                if fav['id'] == self.current_manga_id:
                    read_list = fav.get("read_chapters", [])
                    break

        # 2. Ciclo sui capitoli - VERSIONE LEGGERA PER EVITARE LAG
        # Usiamo self.current_chapters_data per conservare i dati grezzi per il lettore
        self.current_chapters_data = chapters 

        # Create widgets in small batches to keep UI responsive
        batch_size = 20
        total = len(chapters)
        self.chapter_widgets = []

        def make_batch(start):
            # Se il token è cambiato, interrompiamo (un'altra popolazione è iniziata)
            if getattr(self, '_populate_token', 0) != current_token:
                return

            end = min(start + batch_size, total)
            for chap in chapters[start:end]:
                var = ctk.BooleanVar()
                # Only mark as read if it's in read_list (fully read). Partial progress is shown in the reader popup only.
                if chap['id'] in read_list:
                    var.set(True)

                m_id = self.current_manga_id
                def click_handler(m_id=m_id, c_id=chap['id'], v=var):
                    self.on_chapter_toggle(m_id, c_id, v)

                chk = ctk.CTkCheckBox(
                    self.chapters_scroll,
                    text=chap['title'],
                    variable=var,
                    text_color=COLOR_TEXT,
                    font=("Inter", 12),
                    fg_color=COLOR_PRIMARY,
                    hover_color="#2563EB",
                    command=click_handler
                )
                chk.pack(anchor="w", pady=2, padx=5)
                self.chapter_widgets.append({"widget": chk, "var": var, "data": chap})

            if end < total:
                # schedule next batch
                self.chapters_scroll.after(50, lambda: make_batch(end))
            else:
                try:
                    self.update_chapter_counters()
                except Exception:
                    pass

        make_batch(0)

    def on_chapter_toggle(self, manga_id, chapter_id, var):
        """Handle click on chapter checkbox: update read status and favorites."""
        
        # 1. Trova il manga nei preferiti
        target_fav = None
        for fav in self.favorites:
            if fav['id'] == manga_id:
                target_fav = fav
                break
        
        # 2. Creazione automatica se non esiste (Auto-add to favorites)
        if not target_fav:
            target_fav = {
                "id": manga_id, 
                "title": self.current_manga_title,
                "read_chapters": [],
                "read_count": 0,
                "total_chapters": len(self.chapter_widgets) if self.chapter_widgets else 0
            }
            self.favorites.append(target_fav)
            # Accende la stella visivamente
            try: self.btn_fav.configure(text='⭐', fg_color=COLOR_PRIMARY, text_color='white')
            except: pass

        if "read_chapters" not in target_fav:
            target_fav["read_chapters"] = []

        # 3. Leggi lo stato dalla variabile (True/False)
        is_checked = var.get()

        if is_checked:
            if chapter_id not in target_fav["read_chapters"]:
                target_fav["read_chapters"].append(chapter_id)
        else:
            if chapter_id in target_fav["read_chapters"]:
                target_fav["read_chapters"].remove(chapter_id)

        # 4. Aggiorna conteggio e salva
        target_fav["read_count"] = len(target_fav["read_chapters"])
        
        self.save_favorites()
        self._populate_favorites() # Aggiorna la lista a sinistra
        # Aggiorna i contatori dei capitoli (letti/da leggere)
        try:
            self.update_chapter_counters()
        except Exception:
            pass
    def _init_sidebar(self):
        """Initialize the leftist sidebar with Favorites and Chapters lists."""
        # Increased width slightly and fixed it to prevent layout shifts
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="transparent")
        # Reduce horizontal gap between sidebar and main panel
        # Tighten the horizontal gap between sidebar and main panel
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=(20, 2), pady=(10, 20))
        self.sidebar.grid_propagate(False) # Prevent resizing based on content (stops jumping)
        
        # Grid weights: Favorites (row 0) and Chapters (row 1) share vertical space
        self.sidebar.grid_rowconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(1, weight=1)

        # --- 1. CARD PREFERITI (Row 0) ---
        favorites_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=15)
        favorites_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        ctk.CTkLabel(favorites_card, text="PREFERITI", font=("Inter", 12, "bold"), text_color=COLOR_TEXT_LIGHT).pack(anchor="w", padx=20, pady=(10, 5))
        self.favorites_scroll = ctk.CTkScrollableFrame(favorites_card, fg_color="transparent")
        self.favorites_scroll.pack(fill="both", expand=True, padx=5, pady=(0, 10))

        # --- 2. CARD CAPITOLI (Row 1) ---
        chapters_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=15)
        chapters_card.grid(row=1, column=0, sticky="nsew") 
        
        header_chap = ctk.CTkFrame(chapters_card, fg_color="transparent")
        header_chap.pack(fill="x", padx=20, pady=(10, 4))
        # Column 0 (Title) fixed width, Column 1 (Count) expands to fill relative space
        header_chap.grid_columnconfigure(0, weight=0) 
        header_chap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header_chap, text="CAPITOLI", font=("Inter", 12, "bold"), text_color=COLOR_TEXT_LIGHT).grid(row=0, column=0, sticky="w")
        self.lbl_chap_count = ctk.CTkLabel(header_chap, text="0 totali", font=("Inter", 11), text_color=COLOR_TEXT_LIGHT, fg_color="#F3F4F6", corner_radius=5)
        # Sticky "ew" prevents it from floating right, fills the gap till "CAPITOLIS"
        self.lbl_chap_count.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        badges_row = ctk.CTkFrame(header_chap, fg_color="transparent")
        badges_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        badges_row.grid_columnconfigure(0, weight=1)
        badges_row.grid_columnconfigure(1, weight=1)

        self.lbl_read_count = ctk.CTkLabel(badges_row, text="0 letti", font=("Inter", 11, "bold"), text_color=BADGE_STATUS_FG, fg_color=BADGE_STATUS_BG, corner_radius=6, padx=8, pady=2)
        self.lbl_read_count.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.lbl_unread_count = ctk.CTkLabel(badges_row, text="0 da leggere", font=("Inter", 11), text_color=BADGE_GENRE_FG, fg_color=BADGE_GENRE_BG, corner_radius=6, padx=8, pady=2)
        self.lbl_unread_count.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.chapters_scroll = ctk.CTkScrollableFrame(chapters_card, fg_color="transparent")
        self.chapters_scroll.pack(fill="both", expand=True, padx=5, pady=(5, 15))
        
        # Removed "Tutti"/"Nessuno" buttons as requested

    
    def _init_main_area(self):
        """Initialize the central area with Manga Details and Download Options."""
        self.main_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=15)
        # Match sidebar spacing to keep the center gap small
        self.main_frame.grid(row=1, column=1, sticky="nsew", padx=(2, 10), pady=(10, 20))
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1) # Permette al contenuto di espandersi

        # Container principale scrollabile: permette di raggiungere sempre "Opzioni Download"
        content_area = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        content_area.pack(fill="both", expand=True, padx=5, pady=5)

        # === 1. SEZIONE SUPERIORE (COLONNE) ===
        # Creiamo un frame invisibile per tenere affiancate Copertina e Info
        columns_frame = ctk.CTkFrame(content_area, fg_color="transparent")
        columns_frame.pack(fill="x", expand=False, pady=(0, 6))

# ... dentro _init_main_area ...
        
        # --- Colonna Sinistra (Copertina) ---
        cover_col = ctk.CTkFrame(columns_frame, fg_color="transparent")
        cover_col.pack(side="left", fill="y", padx=(0, 8), anchor="n") 

        # Placeholder shown when no manga is selected
        self._cover_placeholder_text = "Cerca un manga per vederne i dettagli..."

        self.cover_label = ctk.CTkLabel(
            cover_col,
            text=self._cover_placeholder_text,
            width=220,
            height=330,
            fg_color="#E5E7EB",
            corner_radius=10,
            text_color=COLOR_TEXT_LIGHT,
            wraplength=200,
            justify="center"
        )
        self.cover_label.pack()

        # Action buttons: only shown after a manga is selected
        self.btn_download_cover = ctk.CTkButton(
            cover_col,
            text="Scarica Copertina",
            fg_color="#F3F4F6",
            text_color=COLOR_TEXT,
            hover_color="#E5E7EB",
            command=self.download_cover
        )
        self.btn_download_cover.pack(fill="x", pady=(15, 5))
        try:
            self.btn_download_cover.configure(state="disabled")
        except Exception:
            pass
        
        # --- NUOVO BOTTONE LEGGI ---
        self.btn_read_mode = ctk.CTkButton(
            cover_col, 
            text="📖 Leggi Manga", 
            fg_color=COLOR_PRIMARY, 
            text_color="white", 
            font=("Inter", 14, "bold"),
            command=self.open_chapter_selector_popup
        )
        self.btn_read_mode.pack(fill="x", pady=5)
        try:
            self.btn_read_mode.configure(state="disabled")
        except Exception:
            pass

        # --- Colonna Destra (Dettagli Manga) ---
        info_col = ctk.CTkFrame(columns_frame, fg_color="transparent")
        info_col.pack(side="left", fill="both", expand=True)

        # 1. TAGS FRAME (Stato e Generi) - SOPRA IL TITOLO
        self.tags_frame = ctk.CTkFrame(info_col, fg_color="transparent")
        self.tags_frame.pack(fill="x", pady=(0, 10), padx=(5, 0)) # Padding to align with Textbox text
        # Keep a stable height so the layout doesn't jump when badges are added/removed
        try:
            self.tags_frame.configure(height=44)
            self.tags_frame.pack_propagate(False)
        except Exception:
            pass

        # Title + favorite button aligned on same row
        title_row = ctk.CTkFrame(info_col, fg_color="transparent")
        title_row.pack(fill="x", padx=(5, 0)) # Padding to align with Textbox text
        self.lbl_title = ctk.CTkLabel(title_row, text="", font=("Inter", 32, "bold"), text_color=COLOR_TEXT, anchor="w", wraplength=500)
        self.lbl_title.pack(side="left", fill="x", expand=True)
        # more visible favorite button next to title
        self.btn_fav = ctk.CTkButton(
            title_row,
            text='☆',
            width=52,
            height=40,
            fg_color="transparent",
            text_color=COLOR_TEXT,
            font=("Inter", 18, "bold"),
            corner_radius=10,
            command=self._toggle_favorite_current
        )
        # Keep it always packed to avoid layout jumps; enable/disable based on selection.
        self.btn_fav.pack(side="right", padx=(8,0))
        try:
            self.btn_fav.configure(state="disabled")
        except Exception:
            pass
        self.lbl_author = ctk.CTkLabel(info_col, text="", font=("Inter", 14), text_color=COLOR_TEXT_LIGHT, anchor="w")
        self.lbl_author.pack(fill="x", pady=(0, 10), padx=(5, 0)) # Padding to align with Textbox text

        self.txt_description = ctk.CTkTextbox(info_col, fg_color="transparent", text_color=COLOR_TEXT, font=("Inter", 14), wrap="word", height=260)
        # Non espandere all'infinito: lasciamo spazio (e scroll) per la sezione download
        self.txt_description.pack(fill="both", expand=False)
        self.txt_description.insert("1.0", "")
        self.txt_description.configure(state="disabled")

        # === 2. SEZIONE INFERIORE (OPZIONI DOWNLOAD - FULL WIDTH) ===
        # Ora questo frame è figlio di 'content_area', non di 'info_col', quindi va sotto tutto
        self.options_container = ctk.CTkFrame(content_area, fg_color="#F9FAFB", corner_radius=12, border_width=1, border_color="#E5E7EB")
        self.options_container.pack(fill="x", pady=(0, 0))

        inner_options = ctk.CTkFrame(self.options_container, fg_color="transparent")
        inner_options.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(inner_options, text="Opzioni Download", font=("Inter", 14, "bold"), text_color=COLOR_TEXT).pack(anchor="w", pady=(0, 10))
        
        # Checkbox
        self.merge_epub_var = ctk.BooleanVar(value=True)
        self.chk_merge_epub = ctk.CTkCheckBox(inner_options, text="Unisci capitoli (Singolo file)", 
                variable=self.merge_epub_var, text_color=COLOR_TEXT, 
                fg_color=COLOR_PRIMARY, font=("Inter", 13))
        self.chk_merge_epub.pack(anchor="w", pady=(0, 10))

        self.split_mb_var = ctk.BooleanVar(value=False)
        self.chk_split_mb = ctk.CTkCheckBox(inner_options, text="Dividi se supera i 200 MB (Ottimale per Kindle)", 
                variable=self.split_mb_var, text_color=COLOR_TEXT, 
                fg_color=COLOR_PRIMARY, font=("Inter", 13))
        self.chk_split_mb.pack(anchor="w", pady=(0, 14))

        # Pulsanti Azione
        action_btns = ctk.CTkFrame(inner_options, fg_color="transparent")
        action_btns.pack(fill="x")

        self.btn_epub = ctk.CTkButton(action_btns, text="Scarica EPUB", font=("Inter", 14, "bold"), fg_color=COLOR_PRIMARY, height=45, command=lambda: self.start_download_thread('epub'))
        self.btn_epub.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.btn_pdf = ctk.CTkButton(action_btns, text="Scarica PDF", font=("Inter", 14, "bold"), fg_color="white", text_color=COLOR_TEXT, border_width=1, border_color="#E5E7EB", hover_color="#F3F4F6", height=45, command=lambda: self.start_download_thread('pdf'))
        self.btn_pdf.pack(side="left", fill="x", expand=True)

        # Keep download options always present to avoid layout jumps; disable until a manga is selected
        try:
            self.btn_epub.configure(state="disabled")
            self.btn_pdf.configure(state="disabled")
        except Exception:
            pass
        try:
            self.chk_merge_epub.configure(state="disabled")
            self.chk_split_mb.configure(state="disabled")
        except Exception:
            pass

        # === 3. STATUS BAR (Sotto tutto il main frame) ===
        self.status_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=50)
        self.status_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 16))
        
        # Barra lunga
        self.progressbar = ctk.CTkProgressBar(self.status_frame, orientation="horizontal", mode="determinate", progress_color="#22C55E", height=12)
        self.progressbar.pack(fill="x", expand=True, pady=(0, 8))
        self.progressbar.set(0)

        # Testo centrato sotto
        self.status_label = ctk.CTkLabel(self.status_frame, text="Pronto", text_color=COLOR_TEXT_LIGHT, font=("Inter", 12), anchor="center")
        self.status_label.pack(fill="x")    

    def _safe_destroy_children(self, parent, delay=20):
        """Schedule destruction of child widgets to avoid interfering with widget redraws."""
        try:
            children = parent.winfo_children()
            for i, w in enumerate(children):
                def _destroy_safe(widget):
                    try:
                        widget.destroy()
                    except Exception:
                        # ignore Tcl errors during async destroy (trace removal, already deleted callbacks, etc.)
                        pass

                try:
                    parent.after(delay * (i + 1), lambda widget=w: _destroy_safe(widget))
                except Exception:
                    try:
                        _destroy_safe(w)
                    except Exception:
                        pass
        except Exception:
            pass
    
    # ================= LOGICA =================
    def set_status(self, text):
        """Update the bottom status bar text."""
        self.status_label.configure(text=text)
        self.update_idletasks()

    def _bump_ui_token(self):
        try:
            self._ui_token += 1
        except Exception:
            self._ui_token = 1
        return self._ui_token

    def _run_if_token(self, token, fn):
        try:
            if token is None:
                fn()
                return
            if getattr(self, '_ui_token', 0) == token:
                fn()
        except Exception:
            pass

    def _is_request_current(self, token, manga_id):
        try:
            return (
                getattr(self, '_ui_token', 0) == token
                and getattr(self, '_active_manga_request_token', None) == token
                and getattr(self, '_active_manga_request_id', None) == manga_id
            )
        except Exception:
            return False
        
    def open_chapter_selector_popup(self):
        """Open the chapter selector popup for reading mode."""
        # Build a progress map for this manga (do not change sidebar UI)
        progress_map = {}
        try:
            if self.current_manga_id:
                for fav in self.favorites:
                    if fav.get('id') == self.current_manga_id:
                        progress_map = fav.get('chapter_progress', {}) or {}
                        break
        except Exception:
            progress_map = {}

        # Verifica se ci sono capitoli caricati; se non ci sono, prova a usare la cache
        if not hasattr(self, 'current_chapters_data') or not self.current_chapters_data:
            # try to use cached chapters from the scraper to avoid refetching
            try:
                if self.current_manga_id and self.current_manga_id in self.mw._chapters_cache:
                    cached = self.mw._chapters_cache.get(self.current_manga_id)
                    if cached:
                        chapters = cached[0]
                        self.current_chapters_data = chapters
                else:
                    # If not cached, trigger background load then open selector when ready
                    def _load_and_open():
                        token = getattr(self, '_ui_token', 0)
                        try:
                            self.load_chapters_for_manga({"id": self.current_manga_id, "title": self.current_manga_title}, token)
                        except Exception:
                            pass
                        # open selector on main thread if chapters are now available
                        try:
                            self.after(0, lambda: self._run_if_token(token, lambda: ChapterSelector(self, self.current_chapters_data or [], self.start_reading_chapter, progress_map=progress_map)))
                        except Exception:
                            pass
                    threading.Thread(target=_load_and_open, daemon=True).start()
                    return
            except Exception:
                messagebox.showinfo("Info", "Carica prima un manga per leggere.")
                return

        # Apre il selettore passando la lista dei capitoli, la funzione da eseguire alla scelta
        ChapterSelector(self, self.current_chapters_data, self.start_reading_chapter, progress_map=progress_map)

    def start_reading_chapter(self, chapter_data):
        """Open the reader window for the selected chapter."""
        # Funzione chiamata quando si clicca un capitolo nel popup
        is_fs = False
        if hasattr(self, 'reader_window') and self.reader_window is not None and self.reader_window.winfo_exists():
            try:
                is_fs = bool(self.reader_window.attributes('-fullscreen'))
            except Exception:
                pass
            self.reader_window.destroy()
        
        # Apre il lettore passando anche la callback per segnare progresso
        # e la callback per aprire automaticamente il capitolo successivo
        # determine saved progress for this chapter (percent and page)
        start_pct = 0
        start_page = None
        try:
            if self.current_manga_id:
                for fav in self.favorites:
                    if fav.get('id') == self.current_manga_id:
                        prog = fav.get('chapter_progress', {}).get(chapter_data.get('id'))
                        if isinstance(prog, dict):
                            start_pct = prog.get('percent', 0)
                            start_page = prog.get('page')
                        else:
                            try:
                                start_pct = int(prog)
                            except Exception:
                                start_pct = 0
                        break
        except Exception:
            start_pct = 0
            start_page = None

        self.reader_window = MangaReader(self, chapter_data, self.mw, mark_read_callback=(self.mark_chapter_progress, self.open_next_from_reader, self.open_prev_from_reader), start_percent=start_pct, start_page=start_page, is_fullscreen=is_fs)
        try:
            bring_to_front(self.reader_window)
        except Exception:
            pass

    def mark_chapter_as_read_from_reader(self, chapter_id):
        """Mark chapter as fully read (checkbox) triggered from Reader."""
        # 1. Trova il widget corrispondente nella lista principale e metti la spunta visiva
        for item in self.chapter_widgets:
            if item['data']['id'] == chapter_id:
                if not item['var'].get(): # Se non è già spuntato
                    item['var'].set(True)
                    # 2. Scatena la logica di salvataggio preferiti
                    self.on_chapter_toggle(self.current_manga_id, chapter_id, item['var'])
                break

    def mark_chapter_progress(self, chapter_id, percent, page_index=None):
        """Save partial reading progress (percent and page index)."""
        try:
            if not self.current_manga_id:
                return
            # find or create favorite entry
            target_fav = None
            for fav in self.favorites:
                if fav.get('id') == self.current_manga_id:
                    target_fav = fav
                    break
            if not target_fav:
                target_fav = {"id": self.current_manga_id, "title": self.current_manga_title, "read_chapters": [], "read_count": 0, "total_chapters": len(self.chapter_widgets) if self.chapter_widgets else 0, "chapter_progress": {}}
                self.favorites.append(target_fav)
            if 'chapter_progress' not in target_fav:
                target_fav['chapter_progress'] = {}
            # store percent (cap to 100) and page index
            try:
                pct = max(0, min(100, int(percent)))
            except Exception:
                pct = 0
            try:
                page_idx = None if page_index is None else int(page_index)
            except Exception:
                page_idx = None
            target_fav['chapter_progress'][chapter_id] = {"percent": pct, "page": page_idx}
            # If fully read, ensure it's in read_chapters
            if pct >= 100:
                if 'read_chapters' not in target_fav:
                    target_fav['read_chapters'] = []
                if chapter_id not in target_fav['read_chapters']:
                    target_fav['read_chapters'].append(chapter_id)
            # update read_count
            target_fav['read_count'] = len(target_fav.get('read_chapters', []))
            self.save_favorites()
            # If chapter is fully read, also mark the checkbox in the sidebar
            if pct >= 100:
                for item in self.chapter_widgets:
                    try:
                        if item['data'].get('id') == chapter_id:
                            try:
                                item['var'].set(True)
                            except Exception:
                                pass
                            break
                    except Exception:
                        pass
                try:
                    self.update_chapter_counters()
                except Exception:
                    pass
                try:
                    self._populate_favorites()
                except Exception:
                    pass
        except Exception:
            pass

    def open_next_from_reader(self, chapter_id):
        """Find the next chapter and open it in the reader."""
        # Trova il capitolo corrente nella lista e apri il successivo (se presente)
        try:
            if not hasattr(self, 'current_chapters_data') or not self.current_chapters_data:
                return
            # Try to find the current chapter index
            next_ch = None
            found_idx = None
            for idx, ch in enumerate(self.current_chapters_data):
                if ch.get('id') == chapter_id:
                    found_idx = idx
                    break
            if found_idx is None:
                return
            
            # Prefer the next index (idx+1)
            if found_idx + 1 < len(self.current_chapters_data):
                next_ch = self.current_chapters_data[found_idx + 1]
            
            if next_ch:
                is_fs = False
                try:
                    if hasattr(self, 'reader_window') and self.reader_window is not None and self.reader_window.winfo_exists():
                        try:
                            is_fs = bool(self.reader_window.attributes('-fullscreen'))
                        except Exception: pass
                        try: self.reader_window.destroy()
                        except Exception: pass
                except Exception:
                    pass
                
                # Apri il capitolo successivo (passando di nuovo le callback e is_fullscreen)
                self.reader_window = MangaReader(self, next_ch, self.mw, mark_read_callback=(self.mark_chapter_as_read_from_reader, self.open_next_from_reader, self.open_prev_from_reader), is_fullscreen=is_fs)
                try:
                    bring_to_front(self.reader_window)
                except Exception:
                    pass
        except Exception as e:
            print(f"Errore open_next_from_reader: {e}")

    def open_prev_from_reader(self, chapter_id):
        """Find the previous chapter and open it in the reader."""
        # Trova il capitolo corrente nella lista e apri il precedente (se presente)
        try:
            if not hasattr(self, 'current_chapters_data') or not self.current_chapters_data:
                return
            prev_ch = None
            found_idx = None
            for idx, ch in enumerate(self.current_chapters_data):
                if ch.get('id') == chapter_id:
                    found_idx = idx
                    break
            if found_idx is None:
                return
            if found_idx - 1 >= 0:
                prev_ch = self.current_chapters_data[found_idx - 1]
            
            if prev_ch:
                is_fs = False
                try:
                    if hasattr(self, 'reader_window') and self.reader_window is not None and self.reader_window.winfo_exists():
                        try:
                            is_fs = bool(self.reader_window.attributes('-fullscreen'))
                        except Exception: pass
                        try: self.reader_window.destroy()
                        except Exception: pass
                except Exception:
                    pass
                
                # Apri il capitolo precedente (passando di nuovo le callback e is_fullscreen)
                self.reader_window = MangaReader(self, prev_ch, self.mw, mark_read_callback=(self.mark_chapter_as_read_from_reader, self.open_next_from_reader, self.open_prev_from_reader), is_fullscreen=is_fs)
                try:
                    bring_to_front(self.reader_window)
                except Exception:
                    pass
        except Exception as e:
            print(f"Errore open_prev_from_reader: {e}")

    def update_chapter_counters(self):
        """Recalculate and display 'Read' vs 'Unread' counts."""
        try:
            total = len(self.chapter_widgets)
            read = sum(1 for it in self.chapter_widgets if it.get('var') and it['var'].get())
            unread = max(0, total - read)
            try:
                self.lbl_chap_count.configure(text=f"{total} totali")
            except Exception:
                pass
            try:
                self.lbl_read_count.configure(text=f"{read} letti")
            except Exception:
                pass
            try:
                self.lbl_unread_count.configure(text=f"{unread} da leggere")
            except Exception:
                pass
        except Exception:
            pass

    def clear_all(self):
        """Reset the UI to initial state (no manga selected)."""
        # Invalidate any pending background UI updates (searches / chapter loads / image loads)
        token = self._bump_ui_token()
        self._active_manga_request_id = None
        self._active_manga_request_token = None

        self.search_entry.delete(0, "end")
        try:
            self._clear_search_dropdown()
            self._hide_search_dropdown()
        except Exception:
            pass
        
        # Instant clear of chapters (no animation/threads to avoid "refresh" look)
        try:
            for widget in self.chapters_scroll.winfo_children():
                widget.destroy()
        except Exception:
            pass
        self.chapter_widgets.clear()

        # Reset Chapter Headers immediately
        try:
            self.lbl_chap_count.configure(text="0 totali")
            self.lbl_read_count.configure(text="0 letti")
            self.lbl_unread_count.configure(text="0 da leggere")
        except Exception:
            pass

        # Reset current manga state
        self.current_manga_title = ""
        self.current_manga_id = None
        self.current_author = ""
        try:
            self.current_chapters_data = []
        except Exception:
            pass
        
        # Pulisci tags
        for widget in self.tags_frame.winfo_children(): widget.destroy()

        self.lbl_title.configure(text="")
        self.lbl_author.configure(text="")
        # Clear stored CTkImage reference first to avoid TclError if image was GC'd
        self.cover_ctk_img = None
        try:
            self.cover_label.configure(image=None, text="")
        except Exception:
            try:
                self.cover_label.configure(image="", text="")
            except Exception:
                pass
        self.update_description("")
        self.lbl_chap_count.configure(text="0 totali")
        self.progressbar.set(0)
        self.current_cover_url = None
        # Reset cover placeholder and hide cover actions
        try:
            self._set_manga_details_visible(False)
        except Exception:
            pass

        # Reset download options defaults
        try:
            self.merge_epub_var.set(True)
        except Exception:
            pass
        try:
            self.split_mb_var.set(False)
        except Exception:
            pass
        # Favorite button stays packed; just disable/reset it
        try:
            self.btn_fav.configure(state="disabled", text='☆', fg_color='transparent', text_color=COLOR_TEXT)
        except Exception:
            pass

        # Reset status text (if nothing else is running)
        try:
            self._run_if_token(token, lambda: self.set_status("Pronto"))
        except Exception:
            pass

    def update_description(self, text):
        self.txt_description.configure(state="normal")
        self.txt_description.delete("1.0", "end")
        self.txt_description.insert("1.0", text)
        self.txt_description.configure(state="disabled")

    def search_thread(self):
        """Invoke search based on input text."""
        # Each search should supersede previous in-flight searches to avoid duplicated results.
        token = self._bump_ui_token()
        query = self.search_entry.get()
        try:
            self._hide_search_dropdown()
        except Exception:
            pass
        threading.Thread(target=self.search_manga, args=(query, token), daemon=True).start()

    def search_manga(self, query=None, token=None):
        """Worker thread for searching manga."""
        if query is None:
            query = self.search_entry.get()
        if not query:
            return
        
        # Use suggest token for dropdown consistency
        if token is None:
            token = self._bump_suggest_token()

        # UI updates 
        try:
            self.after(0, lambda: self.set_status("Ricerca in corso..."))
        except Exception:
            pass

        try:
            # Clear dropdown first? 
            # self.after(0, lambda: self._clear_search_dropdown())
            pass
        except Exception:
            pass

        try:
            results = self.mw.search_manga(query)
            # Reuse _populate_search_dropdown to show results in the floating menu
            self.after(0, lambda: self._populate_search_dropdown(results, token, query))
            self.after(0, lambda: self.set_status(f"Trovati {len(results)} risultati."))
        except Exception as e:
            self.after(0, lambda: self.set_status(f"Errore: {e}"))
            print(e)

    def _populate_results(self, results):
        # Ensure results list is clean before repopulating (avoids duplicates if previous clear was delayed)
        try:
            for w in self.results_scroll.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        for manga in results:
            def make_row(m=manga):
                row = ctk.CTkFrame(self.results_scroll, fg_color="transparent")
                row.pack(fill="x", pady=1)

                def on_open():
                    token = getattr(self, '_ui_token', 0)
                    threading.Thread(target=self.load_chapters_for_manga, args=(m, token), daemon=True).start()

                btn = ctk.CTkButton(
                    row,
                    text=m['title'],
                    fg_color="transparent",
                    text_color=COLOR_TEXT,
                    hover_color="#E0F2FE",
                    anchor="w",
                    command=on_open
                )
                btn.pack(side="left", fill="x", expand=True)

                def on_toggle():
                    if self.is_favorite(m['id']):
                        self.remove_favorite(m['id'])
                        try:
                            fav.configure(text='☆', fg_color="transparent", text_color=COLOR_TEXT)
                        except Exception:
                            fav.configure(text='☆')
                    else:
                        self.add_favorite(m)
                        try:
                            fav.configure(text='⭐', fg_color=COLOR_PRIMARY, text_color='white')
                        except Exception:
                            fav.configure(text='⭐')

                is_fav = self.is_favorite(m['id'])
                fav = ctk.CTkButton(
                    row,
                    text=('⭐' if is_fav else '☆'),
                    width=44,
                    height=34,
                    fg_color=(COLOR_PRIMARY if is_fav else "transparent"),
                    text_color=('white' if is_fav else COLOR_TEXT),
                    hover_color=COLOR_PRIMARY,
                    corner_radius=8,
                    font=("Inter", 14, "bold"),
                    command=on_toggle
                )
                fav.pack(side="right", padx=6)

            make_row()

    def load_chapters_for_manga(self, manga_data, token=None):
        """Fetch chapters for a selected manga and update UI."""
        if token is None:
            token = getattr(self, '_ui_token', 0)
        requested_title = manga_data.get('title', '')
        requested_id = manga_data.get('id')

        # Controllo se il manga richiesto è già quello attualmente visualizzato
        if hasattr(self, 'current_manga_id') and self.current_manga_id == requested_id:
            return

        # Track the latest request so older threads can be ignored
        self._active_manga_request_id = requested_id
        self._active_manga_request_token = token

        try:
            self.after(0, lambda: self._run_if_token(token, lambda: self.set_status(f"Caricamento {requested_title}...")))
        except Exception:
            pass

        # Removed early async clearing to prevent race conditions. 
        # We will clear synchronously right before populating.

        try:
            mid = requested_id
            # prefer cache
            if mid and mid in self.mw._chapters_cache:
                cached = self.mw._chapters_cache.get(mid)
                chapters, cover_url, author, desc, status, genres = cached
            else:
                chapters, cover_url, author, desc, status, genres = self.mw.get_chapters(manga_data)

            # If user clicked "Svuota" (token changed) or another manga was requested, ignore
            if not self._is_request_current(token, requested_id):
                return

            # Update state only if request is still current
            self.current_manga_title = requested_title
            self.current_manga_id = requested_id
            self.current_cover_url = cover_url
            self.current_author = author

            # Passa i dati alla UI
            self.after(0, lambda: self._run_if_token(token, lambda: self._update_details_ui(requested_title, author, desc, len(chapters), status, genres)))

            if cover_url:
                self._load_image_async(cover_url, token=token, manga_id=requested_id)

            # Update favorite's total chapter count if this manga is saved
            try:
                def _update_favs():
                    try:
                        for fav in self.favorites:
                            if fav.get('id') == self.current_manga_id:
                                fav['total_chapters'] = len(chapters)
                                break
                        self.save_favorites()
                        self._populate_favorites()
                    except Exception:
                        pass
                self.after(0, lambda: self._run_if_token(token, _update_favs))
            except Exception:
                pass

            # Popola capitoli (Clear + Populate atomically)
            def _refresh_chapters():
                # Synchronous clear of existing widgets
                for item in self.chapter_widgets:
                    try:
                        item['widget'].destroy()
                    except Exception:
                        pass
                self.chapter_widgets.clear()
                # Also try to clear any stray children in the scrollable frame to be safe
                try:
                    for child in self.chapters_scroll.winfo_children():
                        try: child.destroy()
                        except: pass
                except: pass
                
                self._populate_chapters(chapters)

            self.after(0, lambda: self._run_if_token(token, _refresh_chapters))
            self.after(0, lambda: self._run_if_token(token, lambda: self.set_status("Capitoli caricati.")))

        except Exception as e:
            self.after(0, lambda: self._run_if_token(token, lambda: self.set_status(f"Errore caricamento capitoli: {e}")))
            print(e)

    def _update_details_ui(self, title, author, desc, count, status, genres):
        self.lbl_title.configure(text=title)
        self.lbl_author.configure(text=author)
        self.lbl_chap_count.configure(text=f"{count} totali")
        self.update_description(desc)

        # Show cover actions and remove placeholder now that a manga is selected
        try:
            self._set_manga_details_visible(True)
        except Exception:
            pass

        # --- GESTIONE BADGE/TAGS ---
        # 1. Pulisci tags precedenti
        for widget in self.tags_frame.winfo_children():
            widget.destroy()

        # 2. Badge Stato
        is_ongoing = "corso" in status.lower()
        lbl_status = ctk.CTkLabel(
            self.tags_frame, 
            text=status, 
            fg_color=BADGE_STATUS_BG if is_ongoing else "#E5E7EB", 
            text_color=BADGE_STATUS_FG if is_ongoing else COLOR_TEXT_LIGHT,
            font=("Inter", 12, "bold"),
            corner_radius=6,
            padx=10, pady=4
        )
        lbl_status.pack(side="left", padx=(0, 8))

        # 3. Badge Generi (Max 4)
        for g in genres[:4]:
            lbl_genre = ctk.CTkLabel(
                self.tags_frame, 
                text=g, 
                fg_color=BADGE_GENRE_BG, 
                text_color=BADGE_GENRE_FG,
                font=("Inter", 12, "bold"),
                corner_radius=6,
                padx=10, pady=4
            )
            lbl_genre.pack(side="left", padx=4)
        # Update favorite button state for current manga
        try:
            if self.current_manga_id and self.is_favorite(self.current_manga_id):
                self.btn_fav.configure(text='⭐', fg_color=COLOR_PRIMARY, text_color='white')
            else:
                self.btn_fav.configure(text='☆', fg_color='transparent', text_color=COLOR_TEXT)
        except Exception:
            pass

    def _set_manga_details_visible(self, visible: bool):
        """Toggle cover actions visibility and cover placeholder based on selection state."""
        if visible:
            # Hide placeholder text (cover image will be loaded async if available)
            try:
                if getattr(self, 'cover_label', None) is not None:
                    self.cover_label.configure(text="")
            except Exception:
                pass

            # Keep widgets packed; only toggle enabled state to avoid layout jumps.
            try:
                if getattr(self, 'btn_download_cover', None) is not None:
                    self.btn_download_cover.configure(state="normal")
            except Exception:
                pass

            try:
                if getattr(self, 'btn_read_mode', None) is not None:
                    self.btn_read_mode.configure(state="normal", fg_color=COLOR_PRIMARY, text_color="white")
            except Exception:
                pass

            try:
                if getattr(self, 'btn_fav', None) is not None:
                    self.btn_fav.configure(state="normal")
            except Exception:
                pass

            # Show download options and enable actions
            try:
                if getattr(self, 'btn_epub', None) is not None:
                    self.btn_epub.configure(state="normal")
                if getattr(self, 'btn_pdf', None) is not None:
                    self.btn_pdf.configure(state="normal")
            except Exception:
                pass
            try:
                if getattr(self, 'chk_merge_epub', None) is not None:
                    self.chk_merge_epub.configure(state="normal")
                if getattr(self, 'chk_split_mb', None) is not None:
                    self.chk_split_mb.configure(state="normal")
            except Exception:
                pass
        else:
            # Clear cover image and show placeholder text
            try:
                self.cover_ctk_img = None
            except Exception:
                pass

            try:
                if getattr(self, 'cover_label', None) is not None:
                    self.cover_label.configure(image=None, text=self._cover_placeholder_text, text_color=COLOR_TEXT_LIGHT)
            except Exception:
                try:
                    self.cover_label.configure(image="", text=self._cover_placeholder_text, text_color=COLOR_TEXT_LIGHT)
                except Exception:
                    pass

            # Disable action buttons (keep layout stable)
            try:
                if getattr(self, 'btn_download_cover', None) is not None:
                    self.btn_download_cover.configure(state="disabled")
            except Exception:
                pass

            try:
                if getattr(self, 'btn_read_mode', None) is not None:
                    self.btn_read_mode.configure(state="disabled", fg_color="#F3F4F6", text_color=COLOR_TEXT)
            except Exception:
                pass

            try:
                if getattr(self, 'btn_fav', None) is not None:
                    self.btn_fav.configure(state="disabled", text='☆', fg_color='transparent', text_color=COLOR_TEXT)
            except Exception:
                pass

            # Hide download options when nothing is selected
            try:
                if getattr(self, 'btn_epub', None) is not None:
                    self.btn_epub.configure(state="disabled")
                if getattr(self, 'btn_pdf', None) is not None:
                    self.btn_pdf.configure(state="disabled")
            except Exception:
                pass
            try:
                if getattr(self, 'chk_merge_epub', None) is not None:
                    self.chk_merge_epub.configure(state="disabled")
                if getattr(self, 'chk_split_mb', None) is not None:
                    self.chk_split_mb.configure(state="disabled")
            except Exception:
                pass

    # _populate_chapters is defined earlier with closure to bind manga id correctly

    # ------------------ Favorites logic ------------------
    def load_favorites(self):
        """Load favorite manga list from JSON file."""
        try:
            if os.path.exists(self.fav_file):
                with open(self.fav_file, 'r', encoding='utf-8') as f:
                    self.favorites = json.load(f)
            else:
                self.favorites = []
        except Exception:
            self.favorites = []
        self._populate_favorites()

    def save_favorites(self):
        """Save current favorite list to JSON file."""
        try:
            with open(self.fav_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Errore salvataggio preferiti: {e}")

    def is_favorite(self, manga_id: str) -> bool:
        return any(f.get('id') == manga_id for f in self.favorites)

    def add_favorite(self, manga):
        if not self.is_favorite(manga.get('id')):
            # Try to infer total chapters if currently loaded
            total = 0
            try:
                if self.current_manga_id and self.current_manga_id == manga.get('id'):
                    total = len(self.chapter_widgets)
            except Exception:
                total = 0
            entry = {"id": manga.get('id'), "title": manga.get('title'), "read_chapters": [], "read_count": 0, "total_chapters": total}
            self.favorites.append(entry)
            self.save_favorites()
            self._populate_favorites()

    def remove_favorite(self, manga_id: str):
        before = len(self.favorites)
        self.favorites = [f for f in self.favorites if f.get('id') != manga_id]
        if len(self.favorites) != before:
            self.save_favorites()
            self._populate_favorites()

    def _populate_favorites(self):
        try:
            # clear safely to avoid race with widget redraw
            self._safe_destroy_children(self.favorites_scroll)
        except Exception: return

        for fav in self.favorites:
            def make_fav_row(f=fav):
                row = ctk.CTkFrame(self.favorites_scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)

                def on_open():
                    m = {"id": f.get('id'), "title": f.get('title')}
                    threading.Thread(target=self.load_chapters_for_manga, args=(m,), daemon=True).start()

                # Titolo
                display_title = f.get('title')
                if len(display_title) > 20: display_title = display_title[:18] + "..."
                
                btn = ctk.CTkButton(row, text=display_title, fg_color="transparent", text_color=COLOR_TEXT, anchor="w", command=on_open, width=130)
                btn.pack(side="left", padx=(0, 5))

                # Contatore automatico: mostra letti / totali quando disponibili
                read_count = len(f.get("read_chapters", []))
                total = f.get("total_chapters")
                if total and isinstance(total, int) and total > 0:
                    counter_text = f"{read_count}/{total}"
                else:
                    counter_text = f"{read_count}"
                lbl = ctk.CTkLabel(row, text=counter_text, font=("Inter", 11, "bold"), text_color=COLOR_PRIMARY, width=50)
                lbl.pack(side="left")

                # Tasto Rimuovi
                def on_remove(): self.remove_favorite(f.get('id'))
                ctk.CTkButton(row, text='❌', width=25, height=25, fg_color="transparent", hover_color="#FEE2E2", command=on_remove).pack(side="right", padx=5)

            make_fav_row()
            
    def _toggle_favorite_current(self):
        if not self.current_manga_id:
            return
        if self.is_favorite(self.current_manga_id):
            self.remove_favorite(self.current_manga_id)
            try:
                self.btn_fav.configure(text='☆')
            except Exception:
                pass
        else:
            self.add_favorite({"id": self.current_manga_id, "title": self.current_manga_title})
            try:
                self.btn_fav.configure(text='⭐')
            except Exception:
                pass

    def _load_image_async(self, url, token=None, manga_id=None):
        def _fetch():
            try:
                resp = requests.get(url, stream=True, headers=self.mw.headers)
                img_data = Image.open(BytesIO(resp.content))
                img_data.thumbnail((220, 330))
                ctk_img = ctk.CTkImage(light_image=img_data, size=img_data.size)

                # Update the widget from the main thread and keep a persistent reference
                def _set_image(img=ctk_img, tok=token, mid=manga_id):
                    # Ignore if user clicked "Svuota" or switched manga
                    try:
                        if tok is not None and getattr(self, '_ui_token', 0) != tok:
                            return
                        if mid is not None and getattr(self, 'current_manga_id', None) != mid:
                            return
                    except Exception:
                        return

                    self.cover_ctk_img = img
                    try:
                        self.cover_label.configure(image=img, text="")
                    except Exception:
                        try:
                            self.cover_label.configure(image=img)
                        except Exception:
                            pass

                self.cover_label.after(0, _set_image)
            except Exception as e:
                print(f"Img error: {e}")
        
        threading.Thread(target=_fetch, daemon=True).start()

    def select_all_chapters(self):
        for item in self.chapter_widgets:
            if not item["var"].get():
                item["var"].set(True)
                # Passiamo item["var"]
                self.on_chapter_toggle(self.current_manga_id, item["data"]["id"], item["var"])

    def deselect_all_chapters(self):
        for item in self.chapter_widgets:
            if item["var"].get():
                item["var"].set(False)
                # Passiamo item["var"]
                self.on_chapter_toggle(self.current_manga_id, item["data"]["id"], item["var"])

    def download_cover(self):
        if not self.current_cover_url: return
        file_path = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("JPEG", "*.jpg")], initialfile=f"{self.current_manga_title}_cover")
        if file_path:
            try:
                resp = requests.get(self.current_cover_url, headers=self.mw.headers)
                with open(file_path, 'wb') as f:
                    f.write(resp.content)
                messagebox.showinfo("Fatto", "Copertina salvata.")
            except Exception as e:
                messagebox.showerror("Errore", str(e))

    def start_download_thread(self, format_type):
        """Open popup to confirm download, then start background worker."""
        # Apri il selettore dedicato per il download (separato dalle spunte di lettura)
        def on_selected(chapters):
            if not chapters:
                messagebox.showwarning("Attenzione", "Seleziona almeno un capitolo")
                return

            # Chiedi dove salvare (su main thread)
            save_path = filedialog.asksaveasfilename(title="Dove salvare i file?", initialfile=self.current_manga_title, defaultextension=".epub" if format_type=='epub' else ".pdf", filetypes=[("EPUB", "*.epub") if format_type=='epub' else ("PDF", "*.pdf")])
            if not save_path:
                return

            # Invertiamo l'ordine così che il download vada dal capitolo più vecchio al più recente
            selected = list(reversed(chapters))

            # Disable download buttons to prevent concurrent runs
            try:
                self.btn_epub.configure(state="disabled")
                self.btn_pdf.configure(state="disabled")
            except Exception:
                pass

            threading.Thread(target=self.download_logic, args=(selected, format_type, save_path), daemon=True).start()
        if not hasattr(self, 'current_chapters_data') or not self.current_chapters_data:
            # try to use cached chapters first
            try:
                if self.current_manga_id and self.current_manga_id in self.mw._chapters_cache:
                    cached = self.mw._chapters_cache.get(self.current_manga_id)
                    if cached:
                        self.current_chapters_data = cached[0]
                else:
                    # load chapters in background then open selector
                    def _load_and_open():
                        token = getattr(self, '_ui_token', 0)
                        try:
                            self.load_chapters_for_manga({"id": self.current_manga_id, "title": self.current_manga_title}, token)
                        except Exception:
                            pass
                        try:
                            self.after(0, lambda: self._run_if_token(token, lambda: ChapterDownloadSelector(self, self.current_chapters_data or [], on_selected)))
                        except Exception:
                            pass
                    threading.Thread(target=_load_and_open, daemon=True).start()
                    return
            except Exception:
                messagebox.showwarning("Attenzione", "Carica prima un manga per selezionare i capitoli")
                return

        # Apri il selettore modal
        ChapterDownloadSelector(self, self.current_chapters_data, on_selected)

    def download_logic(self, chapters, format_type, save_dir):
        """Orchestrate the download process: fetch images and create EPUB/PDF."""
        total = len(chapters)
        self.set_status("Inizio download...")
        # Accumula immagini per capitolo prima di scrivere file (necessario per split)
        all_chapters = []  # each item: {'title':..., 'imgs_bytes':[...], 'size':int}

        try:
            for i, chap in enumerate(chapters):
                self.set_status(f"Scaricamento capitolo {i+1}/{total}: \n {chap['title']}")
                try:
                    page_urls = self.mw.get_pages(chap)
                    imgs_bytes = []
                    chap_size = 0
                    total_images = len(page_urls)
                    # Parallel download images per chapter to speed up
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    def fetch_and_resize(idx_url):
                        idx, url = idx_url
                        try:
                            resp = self.mw.session.get(url, headers=self.mw.headers, stream=True, timeout=20)
                            resp.raise_for_status()
                            img_bytes, img_obj = resize_for_kindle(resp.content)
                            return (idx, img_bytes)
                        except Exception as e:
                            return (idx, None)

                    # submit tasks
                    with ThreadPoolExecutor(max_workers=8) as ex:
                        futures = {ex.submit(fetch_and_resize, (idx, url)): idx for idx, url in enumerate(page_urls)}
                        for fut in as_completed(futures):
                            idx, data = fut.result()
                            if data is not None:
                                imgs_bytes.append((f"{i}_{idx}.jpg", data, idx))
                                chap_size += len(data)
                            # Update progress roughly
                            try:
                                done = len(imgs_bytes)
                                progress = (i + (done) / max(1, total_images)) / total
                                self.progressbar.set(progress)
                            except Exception:
                                pass

                    # preserve page order
                    imgs_bytes = sorted(imgs_bytes, key=lambda x: x[2])
                    imgs_bytes = [(name, b) for (name, b, _idx) in imgs_bytes]

                    all_chapters.append({'title': chap['title'], 'imgs': imgs_bytes, 'size': chap_size})

                except Exception as e:
                    print(f"Errore capitolo {chap['title']}: {e}")

                # fine capitolo: assicurati che il progresso rifletta il completamento del capitolo
                try:
                    self.progressbar.set((i + 1) / total)
                except Exception:
                    pass
        finally:
            # Alla fine del download immagini (o in caso di errore) procediamo alla scrittura
            pass

        # Ora abbiamo tutte le immagini per capitolo in memoria (in bytes). Procediamo alla creazione dei file.
        MAX_BYTES = 200 * 1024 * 1024 if self.split_mb_var.get() else None

        # Normalize save_dir for cases where asksaveasfilename returned a file path
        if os.path.isdir(save_dir):
            out_dir = save_dir
        else:
            out_dir = os.path.dirname(save_dir) or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)

        if format_type == 'epub':
            if self.merge_epub_var.get():
                # Scrivi uno o più EPUB uniti (rispettando MAX_BYTES se presente)
                self._write_merged_epubs(save_dir, all_chapters, max_bytes=MAX_BYTES)
            else:
                # Scrivi EPUB per capitolo
                for idx, ch in enumerate(all_chapters, start=1):
                    out_path = os.path.join(out_dir, f"{self.current_manga_title} - {idx:03d} - {ch['title']}.epub")
                    self.set_status(f"Scrittura EPUB {idx}/{len(all_chapters)}: {os.path.basename(out_path)}")
                    self._write_single_epub(out_path, ch['title'], ch['imgs'])

        elif format_type == 'pdf':
            if self.merge_epub_var.get():
                self._write_merged_pdfs(save_dir, all_chapters, max_bytes=MAX_BYTES)
            else:
                # PDF per capitolo
                for idx, ch in enumerate(all_chapters, start=1):
                    self.set_status(f"Scrittura PDF {idx}/{len(all_chapters)}: {ch['title']}")
                    images = [Image.open(BytesIO(b)).convert('RGB') for (_, b) in ch['imgs']]
                    if images:
                        pdf_path = os.path.join(out_dir, f"{self.current_manga_title} - {idx:03d} - {ch['title']}.pdf")
                        images[0].save(pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        self.set_status("Download Completato!")
        self.progressbar.set(1)
        try:
            messagebox.showinfo("Fatto", "Download terminato con successo.")
        except Exception:
            pass
        finally:
            # Re-enable buttons and reset UI
            try:
                self.progressbar.set(0)
                self.set_status("Pronto")
                self.btn_epub.configure(state="normal")
                self.btn_pdf.configure(state="normal")
            except Exception:
                pass

    def _write_single_epub(self, out_path, chapter_title, imgs):
        """Write a single chapter to an EPUB file."""
        book = epub.EpubBook()
        book.set_identifier(f"{self.current_manga_title}-{chapter_title}")
        book.set_title(f"{self.current_manga_title} - {chapter_title}")
        book.set_language('it')
        book.add_author(self.current_author)

        # cover
        if self.current_cover_url:
            try:
                r = requests.get(self.current_cover_url)
                book.set_cover('cover.jpg', r.content)
            except: pass

        html = "<html><body>"
        for name, data in imgs:
            item = epub.EpubItem(uid=name, file_name=f"images/{name}", media_type='image/jpeg', content=data)
            book.add_item(item)
            html += f'<div><img src="images/{name}" alt="{name}"/></div>'
        html += "</body></html>"

        chap = epub.EpubHtml(title=chapter_title, file_name='chapter.xhtml')
        chap.content = html
        book.add_item(chap)
        book.toc = [epub.Link('chapter.xhtml', chapter_title, chapter_title)]
        book.spine = ['nav', chap]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub.write_epub(out_path, book)

    def _write_merged_epubs(self, save_dir, all_chapters, max_bytes=None):
        """Write multiple chapters into one or more EPUB files (splitting by size)."""
        # Normalize save_dir in case user passed a filename instead of a directory
        if os.path.isdir(save_dir):
            out_dir = save_dir
            base_name = self.current_manga_title
        else:
            out_dir = os.path.dirname(save_dir) or os.getcwd()
            base_name = os.path.splitext(os.path.basename(save_dir))[0] or self.current_manga_title
        os.makedirs(out_dir, exist_ok=True)

        part = 1
        current_book = epub.EpubBook()
        current_book.set_identifier(f"{self.current_manga_title}")
        current_book.set_title(self.current_manga_title)
        current_book.set_language('it')
        current_book.add_author(self.current_author)
        if self.current_cover_url:
            try:
                r = requests.get(self.current_cover_url)
                current_book.set_cover('cover.jpg', r.content)
            except: pass

        current_size = 0
        chapters_items = []

        def flush_book(book, chapters_items, part):
            if not chapters_items:
                return
            book.toc = [epub.Link(chap.file_name, title, f"chap_{i}") for i, (title, chap) in enumerate(chapters_items, start=1)]
            book.spine = ['nav'] + [chap for (_, chap) in chapters_items]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            out_path = os.path.join(out_dir, f"{base_name}_part{part}.epub")
            try:
                self.set_status(f"Scrittura EPUB parte {part}...")
            except Exception:
                pass
            epub.write_epub(out_path, book)
            try:
                self.set_status(f"EPUB parte {part} salvato: {os.path.basename(out_path)}")
            except Exception:
                pass
            return out_path

        for chap_idx, ch in enumerate(all_chapters, start=1):
            ch_title = ch['title']
            imgs = ch['imgs']
            ch_size = ch['size']

            if max_bytes is not None and current_size + ch_size > max_bytes and current_size > 0:
                flush_book(current_book, chapters_items, part)
                part += 1
                current_book = epub.EpubBook()
                current_book.set_identifier(f"{self.current_manga_title}")
                current_book.set_title(self.current_manga_title)
                current_book.set_language('it')
                current_book.add_author(self.current_author)
                if self.current_cover_url:
                    try:
                        r = requests.get(self.current_cover_url)
                        current_book.set_cover('cover.jpg', r.content)
                    except: pass
                current_size = 0
                chapters_items = []

            html = "<html><body>"
            for idx, (name, data) in enumerate(imgs, start=1):
                img_name = f"chap{chap_idx}_{idx}.jpg"
                item = epub.EpubItem(uid=img_name, file_name=f"images/{img_name}", media_type='image/jpeg', content=data)
                current_book.add_item(item)
                html += f'<div><img src="images/{img_name}" alt="{img_name}"/></div>'
            html += "</body></html>"
            chap_item = epub.EpubHtml(title=ch_title, file_name=f"chap_{chap_idx}.xhtml")
            chap_item.content = html
            current_book.add_item(chap_item)
            chapters_items.append((ch_title, chap_item))
            current_size += ch_size

        if chapters_items:
            flush_book(current_book, chapters_items, part)

    def _write_merged_pdfs(self, save_dir, all_chapters, max_bytes=None):
        """Write multiple chapters into one or more PDF files (splitting by size)."""
        # Normalize save_dir in case user passed a filename
        if os.path.isdir(save_dir):
            out_dir = save_dir
            base_name = self.current_manga_title
        else:
            out_dir = os.path.dirname(save_dir) or os.getcwd()
            base_name = os.path.splitext(os.path.basename(save_dir))[0] or self.current_manga_title
        os.makedirs(out_dir, exist_ok=True)

        part = 1
        current_images = []
        current_size = 0

        for ch in all_chapters:
            imgs = ch['imgs']
            ch_size = ch['size']

            if max_bytes is not None and current_size + ch_size > max_bytes and current_images:
                out_path = os.path.join(out_dir, f"{base_name}_part{part}.pdf")
                try:
                    self.set_status(f"Scrittura PDF parte {part}...")
                except Exception:
                    pass
                images = [Image.open(BytesIO(b)).convert('RGB') for (_, b) in current_images]
                if images:
                    images[0].save(out_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
                    try:
                        self.set_status(f"PDF parte {part} salvato: {os.path.basename(out_path)}")
                    except Exception:
                        pass
                part += 1
                current_images = []
                current_size = 0

            current_images.extend(imgs)
            current_size += ch_size

        if current_images:
            out_path = os.path.join(out_dir, f"{base_name}_part{part}.pdf")
            try:
                self.set_status(f"Scrittura PDF parte {part}...")
            except Exception:
                pass
            images = [Image.open(BytesIO(b)).convert('RGB') for (_, b) in current_images]
            if images:
                images[0].save(out_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
                try:
                    self.set_status(f"PDF parte {part} salvato: {os.path.basename(out_path)}")
                except Exception:
                    pass


if __name__ == "__main__":
    app = MangaWorldGUI()
    app.mainloop()

