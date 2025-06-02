#!/usr/bin/env python3
import os
import sys
import zipfile
import rarfile
import tempfile
import mimetypes
from pathlib import Path
import hashlib
import pickle
import logging
import pygame
from PIL import Image
import threading
import gc
from pdf2image import convert_from_path
import json
import argparse
import time

# Config logger (remplace les prints de debug)
logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] %(message)s')

# Préparer Pygame avant import
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
os.environ['SDL_LOGGING'] = '0'
os.environ['SDL_VIDEODRIVER'] = os.environ.get('XDG_SESSION_TYPE', 'wayland')

def cleanup():
    pygame.display.quit()
    pygame.quit()
    gc.collect()
    sys.exit(0)

### Progression & Sauvegarde ###
class ProgressManager:
    def __init__(self):
        self.progress_file = Path.home() / ".config" / "manga_reader" / "progress.json"
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)

    def _get_chapter_key(self, chapter_number):
        try:
            return f"{float(chapter_number):.1f}"
        except Exception:
            return str(chapter_number)

    def save(self, manga_name, chapter_number, current_page, total_pages, force_save=False):
        chapter_key = self._get_chapter_key(chapter_number)
        is_completed = current_page >= total_pages
        try:
            if self.progress_file.exists():
                try:
                    with open(self.progress_file, "r", encoding='utf-8') as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

            if manga_name not in data:
                data[manga_name] = {}

            existing = data[manga_name].get(chapter_key, {})
            existing_page = existing.get("last_page", 0)
            if force_save or current_page > existing_page or is_completed:
                data[manga_name][chapter_key] = {
                    "last_page": current_page,
                    "total_pages": total_pages,
                    "read": is_completed
                }
                with open(self.progress_file, "w", encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Impossible de sauvegarder la progression: {e}")

    def load(self, manga_name, chapter_number):
        chapter_key = self._get_chapter_key(chapter_number)
        if not self.progress_file.exists():
            return 1
        try:
            with open(self.progress_file, "r", encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    return 1
            chapter = data.get(manga_name, {}).get(chapter_key, {})
            return max(1, chapter.get("last_page", 1))
        except Exception as e:
            logging.error(f"Impossible de charger la progression: {e}")
            return 1

def parse_manga_and_chapter(archive_path):
    p = Path(archive_path).expanduser().absolute()
    manga_name = p.parent.name
    chapter_raw = p.stem
    chapter_number = chapter_raw.replace("Chapitre_", "") if "Chapitre_" in chapter_raw else chapter_raw
    return manga_name, chapter_number

### Gestion d’archive et d’images ###
def get_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def extract_archive(archive_path, extract_to):
    archive_path = Path(archive_path)
    mime_type, _ = mimetypes.guess_type(archive_path)
    try:
        if mime_type == 'application/zip' or archive_path.suffix.lower() in ('.cbz', '.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            return True
        elif mime_type in ('application/x-rar-compressed', 'application/vnd.comicbook-rar') or archive_path.suffix.lower() == '.cbr':
            with rarfile.RarFile(archive_path) as rar_ref:
                rar_ref.extractall(extract_to)
            return True
        elif mime_type == 'application/pdf' or archive_path.suffix.lower() == '.pdf':
            images = convert_from_path(archive_path, dpi=150)
            Path(extract_to).mkdir(parents=True, exist_ok=True)
            for i, img in enumerate(images):
                img_path = Path(extract_to) / f"page_{i+1:03d}.png"
                img.save(img_path, 'PNG')
            return True
        else:
            logging.error(f"Format non pris en charge : {archive_path}")
            return False
    except Exception as e:
        logging.error(f"Erreur d’extraction : {e}")
        return False

def get_image_files(directory):
    return sorted(
        [f for f in Path(directory).iterdir() if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']],
        key=lambda x: (len(x.stem), x.stem)
    )

def load_image_to_pygame(image_path, screen_width, screen_height, zoom=1.0, mode='webtoon'):
    """Chargement unique pour tous les modes"""
    try:
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            iw, ih = img.size
            if mode == 'webtoon':
                target_width = int(screen_width * 0.4 * zoom)
                ratio = target_width / iw
                size = (target_width, int(ih * ratio))
            else:
                width_ratio = screen_width / iw
                height_ratio = screen_height / ih
                ratio = min(width_ratio, height_ratio) * 0.9
                size = (int(iw * ratio), int(ih * ratio))
            img = img.resize(size, Image.Resampling.LANCZOS)
            return pygame.image.fromstring(img.tobytes(), img.size, 'RGB'), img.size
    except Exception as e:
        logging.error(f"Erreur chargement image {image_path}: {e}")
        return None, (0, 0)

### Cache LRU ###
class ImageCache:
    def __init__(self, max_size=30):
        self.cache = {}
        self.order = []
        self.max_size = max_size
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                self.order.remove(key)
                self.order.append(key)
                return self.cache[key]
            return None

    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                self.order.remove(key)
            elif len(self.cache) >= self.max_size:
                for _ in range(min(10, len(self.order))):
                    old = self.order.pop(0)
                    self.cache.pop(old, None)
            self.cache[key] = value
            self.order.append(key)

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.order.clear()
            gc.collect()

    def preload(self, images, screen_width, screen_height, zoom, visible_range, mode='webtoon'):
        """Preload des images autour de la zone visible."""
        start, end = visible_range
        for i in range(max(0, start-2), min(len(images), end+5)):
            key = f"{images[i]}_{zoom:.2f}_{mode}"
            if self.get(key) is None:
                img, size = load_image_to_pygame(images[i], screen_width, screen_height, zoom, mode)
                if img:
                    self.put(key, (img, size))

### Mode détection ###
def detect_mode(images):
    webtoon, manga = 0, 0
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                w, h = img.size
                if h > 3.0 * w:
                    webtoon += 1
                else:
                    manga += 1
        except Exception:
            continue
    return 'webtoon' if webtoon >= manga else 'manga'

def calculate_scroll_speed(zoom, base_speed=100):
    return int(base_speed * (zoom ** 0.8))

def draw_gradient_rect(surface, rect, radius, progress):
    fill_width = int(rect.width * progress)
    if fill_width <= 0:
        return
    bloc_surf = pygame.Surface((fill_width, rect.height), pygame.SRCALPHA)
    block_start = (255, 0, 210, 140)   # Violet clair
    block_end = (0, 250, 10, 140)      # Vert pomme
    for x in range(fill_width):
        t = x / (fill_width - 1) if fill_width > 1 else 1.0
        r = int(block_start[0] + (block_end[0] - block_start[0]) * t)
        g = int(block_start[1] + (block_end[1] - block_start[1]) * t)
        b = int(block_start[2] + (block_end[2] - block_start[2]) * t)
        block_color = (r, g, b)
        pygame.draw.line(bloc_surf, block_color, (x, 0), (x, rect.height-1))

    # Masque arrondi
    mask = pygame.Surface((fill_width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255,255,255,255), (0,0,fill_width,rect.height), border_radius=radius)
    bloc_surf.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MULT)

    # Gloss subtil
    gloss = pygame.Surface((fill_width, int(rect.height * 0.35)), pygame.SRCALPHA)
    gloss.fill((255,255,255,32))
    bloc_surf.blit(gloss, (0,0))

    surface.blit(bloc_surf, (rect.x, rect.y))

def draw_rounded_rect(surface, color, rect, radius=10, width=0, shadow=False):
    temp_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    rect0 = pygame.Rect(0, 0, rect.width, rect.height)
    
    if shadow:
        shadow_color = (0, 0, 0, 100)
        shadow_rect = rect0.move(2, 2)
        pygame.draw.rect(temp_surf, shadow_color, shadow_rect, border_radius=radius)
    
    pygame.draw.rect(temp_surf, color, rect0, border_radius=radius)
    
    if width > 0:
        pygame.draw.rect(temp_surf, (color[0]//2, color[1]//2, color[2]//2), rect0, width=width, border_radius=radius)
    
    surface.blit(temp_surf, (rect.x, rect.y), special_flags=pygame.BLEND_PREMULTIPLIED)

### UI widgets ###
class ModernButton:
    def __init__(self, x, y, w, h, text, font, bg_color=(50, 50, 50), hover_color=(80,80,80), text_color=(255,255,255)):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.font = font
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.is_hovered = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface):
        color = self.hover_color if self.is_hovered else self.bg_color
        pygame.draw.rect(surface, color, self.rect, border_radius=10)
        text_surf = self.font.render(self.text, True, self.text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)

class Slider:
    def __init__(self, x, y, width, height, min_value, max_value, initial_value, bg_color=(50, 50, 50), handle_color=(80, 80, 80)):
        self.rect = pygame.Rect(x, y, width, height)
        self.min_value = min_value
        self.max_value = max_value
        self.value = initial_value
        self.bg_color = bg_color
        self.handle_color = handle_color
        self.handle_width = 10
        self.dragging = False
        self.update_handle_position()

    def update_handle_position(self):
        ratio = (self.value - self.min_value) / (self.max_value - self.min_value)
        self.handle_x = self.rect.x + int(ratio * (self.rect.width - self.handle_width))
        self.handle_rect = pygame.Rect(self.handle_x, self.rect.y, self.handle_width, self.rect.height)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.handle_rect.collidepoint(event.pos):
                self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            mouse_x = max(self.rect.x, min(event.pos[0], self.rect.x + self.rect.width - self.handle_width))
            ratio = (mouse_x - self.rect.x) / (self.rect.width - self.handle_width)
            self.value = self.min_value + ratio * (self.max_value - self.min_value)
            self.update_handle_position()

    def draw(self, surface):
        pygame.draw.rect(surface, self.bg_color, self.rect)
        draw_rounded_rect(surface, self.handle_color, self.handle_rect, radius=5)
        font = pygame.font.SysFont('arial', 14)
        text = font.render(f"Speed: {int(self.value)}", True, (255, 255, 255))
        text_rect = text.get_rect(center=(self.rect.centerx, self.rect.y + self.rect.height + 15))
        surface.blit(text, text_rect)
        
class ModernProgressBar:
    def __init__(self, x, y, width, height, radius=18):
        self.rect = pygame.Rect(x, y, width, height)
        self.radius = radius
        self.progress = 0.0

    def draw(self, surface, progress, current_page, total_pages, show_text=True):
        self.progress += (progress - self.progress) * 0.2

        # Ombre douce sous la barre
        shadow_rect = self.rect.copy()
        shadow_rect.y += 6
        draw_rounded_rect(surface, (30, 30, 30), shadow_rect, radius=self.radius + 3, shadow=False)

        # Bordure flashy
        draw_rounded_rect(surface, (255, 255, 255), self.rect, radius=self.radius + 3, width=3)

        # Dégradé flashy avec bords arrondis
        inner_rect = self.rect.inflate(-6, -6)
        draw_gradient_rect(surface, inner_rect, self.radius, self.progress)

        # Texte
        if show_text and total_pages > 0:
            font = pygame.font.SysFont('arial', int(self.rect.height * 0.65), bold=True)
            status = "✓" if self.progress >= 1.0 else ""
            txt = f"{status} {int(self.progress * 100)}% (Pg {current_page}/{total_pages})"
            text_surface = font.render(txt, True, (250, 255, 0) if self.progress > 0.6 else (0, 0, 50))
            text_rect = text_surface.get_rect(center=self.rect.center)
            surface.blit(text_surface, text_rect)

### Renderers ###
class BaseRenderer:
    def __init__(self, images, screen_width, screen_height, cache):
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cache = cache

    def update_screen(self, w, h):
        self.screen_width = w
        self.screen_height = h

class WebtoonRenderer(BaseRenderer):
    def __init__(self, images, screen_width, screen_height, cache):
        super().__init__(images, screen_width, screen_height, cache)
        self.zoom = 1.0
        self.gap = 10
        self.image_positions = []
        self.total_height = 0
        self.calculate_layout(self.zoom)

    def calculate_layout(self, zoom):
        self.zoom = zoom
        self.image_positions = []
        y = 0
        for img_path in self.images:
            key = f"{img_path}_{zoom:.2f}_webtoon"
            cached = self.cache.get(key)
            if cached:
                _, (w, h) = cached
            else:
                try:
                    with Image.open(img_path) as img:
                        iw, ih = img.size
                        target_width = int(self.screen_width * 0.4 * zoom)
                        ratio = target_width / iw
                        h = int(ih * ratio)
                except Exception:
                    h = 1000
            self.image_positions.append(y)
            y += h + self.gap
        self.total_height = y

    def get_visible_indices(self, offset):
        top = offset
        bottom = offset + self.screen_height
        vis = []
        for i, y in enumerate(self.image_positions):
            key = f"{self.images[i]}_{self.zoom:.2f}_webtoon"
            cached = self.cache.get(key)
            h = cached[1][1] if cached else 1000
            if y + h >= top and y <= bottom:
                vis.append(i)
        return vis

    def render(self, screen, scroll_offset):
        self.update_screen(*pygame.display.get_surface().get_size())
        indices = self.get_visible_indices(scroll_offset)
        for i in indices:
            key = f"{self.images[i]}_{self.zoom:.2f}_webtoon"
            cached = self.cache.get(key)
            if cached:
                img, (w, h) = cached
            else:
                img, (w, h) = load_image_to_pygame(self.images[i], self.screen_width, self.screen_height, self.zoom, 'webtoon')
                if img: self.cache.put(key, (img, (w, h)))
            if img:
                x = (self.screen_width - w) // 2
                y = self.image_positions[i] - scroll_offset
                if y + h >= 0 and y <= self.screen_height:
                    screen.blit(img, (x, y))
            else:
                # Placeholder
                pygame.draw.rect(screen, (50,50,50), (50, self.image_positions[i]-scroll_offset, self.screen_width-100, 100))
        return indices

    def page_from_offset(self, scroll_offset):
        screen_center = scroll_offset + self.screen_height // 2
        for i, pos in enumerate(self.image_positions):
            if pos <= screen_center:
                page = i + 1
            else:
                break
        return min(page, len(self.images))

class MangaRenderer(BaseRenderer):
    def __init__(self, images, screen_width, screen_height, cache):
        super().__init__(images, screen_width, screen_height, cache)
        self.current_page = 0

    def next_page(self):
        if self.current_page < len(self.images) - 1:
            self.current_page += 1

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1

    def go_to_page(self, page):
        self.current_page = max(0, min(page, len(self.images)-1))

    def render(self, screen):
        self.update_screen(*pygame.display.get_surface().get_size())
        i = self.current_page
        key = f"{self.images[i]}_1.0_manga"
        cached = self.cache.get(key)
        if cached:
            img, (w, h) = cached
        else:
            img, (w, h) = load_image_to_pygame(self.images[i], self.screen_width, self.screen_height, 1.0, 'manga')
            if img: self.cache.put(key, (img, (w, h)))
        if img:
            x = (self.screen_width - w) // 2
            y = (self.screen_height - h) // 2
            screen.blit(img, (x, y))
        else:
            pygame.draw.rect(screen, (50,50,50), (50,50,self.screen_width-100, self.screen_height-100))
        return [i]

### Main app loop ###
def main(archive_path, start_page=1):
    try:
        pygame.init()
        pygame.mixer.quit()

        screen_info = pygame.display.Info()
        screen_width, screen_height = screen_info.current_w - 100, screen_info.current_h - 100
        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE | pygame.DOUBLEBUF)
        pygame.display.set_caption(f"Lecteur Webtoon: {Path(archive_path).stem}")

        archive_path = Path(archive_path)
        if not archive_path.exists():
            logging.error(f"Le fichier {archive_path} n'existe pas.")
            cleanup()

        cache_dir = Path.home() / ".manga_reader_cache" / get_file_hash(archive_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "image_list.pkl"

        # Extraction/cache des images
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    images = pickle.load(f)
            except Exception as e:
                images = []
        else:
            with tempfile.TemporaryDirectory() as tmpdirname:
                tmp_path = Path(tmpdirname)
                if not extract_archive(archive_path, tmp_path):
                    logging.error(f"Échec de l'extraction de {archive_path}")
                    cleanup()
                images = get_image_files(tmp_path)
                cached_images = []
                for img in images:
                    dest = cache_dir / img.name
                    dest.write_bytes(img.read_bytes())
                    cached_images.append(dest)
                with open(cache_file, 'wb') as f:
                    pickle.dump(cached_images, f)
                images = cached_images

        images = [img for img in images if img.exists()]
        if not images:
            logging.error("Aucune image valide trouvée dans l'archive ou le cache.")
            cleanup()

        # Mode
        mode = detect_mode(images)
        image_cache = ImageCache(max_size=30)
        webtoon_renderer = WebtoonRenderer(images, screen_width, screen_height, image_cache)
        manga_renderer = MangaRenderer(images, screen_width, screen_height, image_cache)
        zoom = 1.0
        scroll_offset = 0

        # Progression
        manga_name, chapter_number = parse_manga_and_chapter(archive_path)
        progress_mgr = ProgressManager()
        start_page = start_page if start_page > 0 else progress_mgr.load(manga_name, chapter_number)
        if mode == 'manga':
            manga_renderer.go_to_page(start_page - 1)
            current_page = start_page
        else:
            webtoon_renderer.calculate_layout(zoom)
            if start_page - 1 < len(webtoon_renderer.image_positions):
                scroll_offset = webtoon_renderer.image_positions[start_page-1]
                current_page = start_page
            else:
                scroll_offset = 0
                current_page = 1

        # UI
        font = pygame.font.SysFont('arial', 18, bold=True)
        mode_button = ModernButton(screen_width - 250, 10, 120, 30, f"{mode.capitalize()}", font)
        play_button = ModernButton(screen_width - 120, 10, 100, 30, "Play", font)
        speed_slider = Slider(screen_width - 140, 50, 100, 10, 150, 1200, 500)
        progress_bar = ModernProgressBar(screen_width - 300, screen_height - 200, 200, 25)
        running = True
        is_scrolling = False
        last_scroll_time = pygame.time.get_ticks() / 1000.0

        def update_layout():
            nonlocal screen_width, screen_height
            screen_width, screen_height = pygame.display.get_surface().get_size()
            mode_button.rect.topleft = (screen_width - 250, 10)
            play_button.rect.topleft = (screen_width - 120, 10)
            speed_slider.rect.topleft = (screen_width - 240, 50)
            progress_bar.rect.topright = (screen_width - 20, screen_height - 30)
            webtoon_renderer.update_screen(screen_width, screen_height)
            manga_renderer.update_screen(screen_width, screen_height)
            webtoon_renderer.calculate_layout(zoom)
            image_cache.clear()

        clock = pygame.time.Clock()
        while running:
            current_time = pygame.time.get_ticks() / 1000.0
            delta_time = current_time - last_scroll_time
            last_scroll_time = current_time

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    update_layout()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        running = False
                    elif event.key == pygame.K_m:
                        mode = 'manga'
                        mode_button.text = "Manga"
                        update_layout()
                    elif event.key == pygame.K_w:
                        mode = 'webtoon'
                        mode_button.text = "Webtoon"
                        update_layout()
                    elif event.key == pygame.K_RETURN and mode == 'webtoon':
                        is_scrolling = not is_scrolling
                        play_button.text = "Stop" if is_scrolling else "Play"
                    elif mode == 'webtoon':
                        if event.key == pygame.K_HOME: scroll_offset = 0
                        elif event.key == pygame.K_END: scroll_offset = max(0, webtoon_renderer.total_height - screen_height)
                        elif event.key == pygame.K_PAGEDOWN: scroll_offset = min(scroll_offset + screen_height, max(0, webtoon_renderer.total_height - screen_height))
                        elif event.key == pygame.K_PAGEUP: scroll_offset = max(0, scroll_offset - screen_height)
                    elif mode == 'manga':
                        if event.key == pygame.K_HOME: manga_renderer.go_to_page(0)
                        elif event.key == pygame.K_END: manga_renderer.go_to_page(len(images)-1)
                        elif event.key in [pygame.K_PAGEDOWN, pygame.K_DOWN]: manga_renderer.next_page()
                        elif event.key in [pygame.K_PAGEUP, pygame.K_UP]: manga_renderer.prev_page()
                elif event.type == pygame.MOUSEWHEEL:
                    if mode == 'webtoon':
                        scroll_speed = calculate_scroll_speed(zoom)
                        scroll_offset = max(0, min(scroll_offset - event.y * scroll_speed * 2.0, max(0, webtoon_renderer.total_height - screen_height)))
                    elif mode == 'manga':
                        if event.y > 0: manga_renderer.prev_page()
                        elif event.y < 0: manga_renderer.next_page()
                if mode_button.handle_event(event):
                    if mode == 'webtoon':
                        mode = 'manga'
                        mode_button.text = "Manga"
                    else:
                        mode = 'webtoon'
                        mode_button.text = "Webtoon"
                    update_layout()
                elif play_button.handle_event(event) and mode == 'webtoon':
                    is_scrolling = not is_scrolling
                    play_button.text = "Stop" if is_scrolling else "Play"
                if mode == 'webtoon':
                    speed_slider.handle_event(event)

            keys = pygame.key.get_pressed()
            if mode == 'webtoon':
                scroll_speed = calculate_scroll_speed(zoom) // 3
                if keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_SPACE]:
                    scroll_offset = min(scroll_offset + scroll_speed, max(0, webtoon_renderer.total_height - screen_height))
                elif keys[pygame.K_UP] or keys[pygame.K_w]:
                    scroll_offset = max(0, scroll_offset - scroll_speed)
                if is_scrolling:
                    play_speed = speed_slider.value
                    scroll_offset = min(scroll_offset + play_speed * delta_time, max(0, webtoon_renderer.total_height - screen_height))
            elif mode == 'manga':
                if keys[pygame.K_DOWN] or keys[pygame.K_s]:
                    manga_renderer.next_page()
                elif keys[pygame.K_UP] or keys[pygame.K_w]:
                    manga_renderer.prev_page()

            screen.fill((20, 20, 20))
            if mode == 'webtoon':
                vis = webtoon_renderer.render(screen, scroll_offset)
                current_page = webtoon_renderer.page_from_offset(scroll_offset)
                total_pages = len(images)
                progress = min(1.0, scroll_offset / max(1, webtoon_renderer.total_height - screen_height)) if webtoon_renderer.total_height > screen_height else 1.0
            else:
                vis = manga_renderer.render(screen)
                current_page = manga_renderer.current_page + 1
                total_pages = len(images)
                progress = manga_renderer.current_page / max(1, len(images)-1) if len(images) > 1 else 1.0

            # Sauvegarde progression
            progress_mgr.save(manga_name, chapter_number, current_page, total_pages)
            text = font.render(f"{Path(archive_path).stem}", True, (255, 255, 255))
            screen.blit(text, (10, 10))
            mode_button.draw(screen)
            if mode == 'webtoon':
                play_button.draw(screen)
                speed_slider.draw(screen)
            progress_bar.draw(screen, progress, current_page, total_pages)
            pygame.display.flip()
            clock.tick(60)

        # Dernière sauvegarde
        progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
        cleanup()
    except Exception as e:
        logging.error(f"Exception non gérée : {e}")
        cleanup()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manga/Webtoon Reader")
    parser.add_argument("archive_path", help="Path to the manga archive file")
    parser.add_argument("--page", type=int, default=0, help="Starting page number")
    args = parser.parse_args()
    main(args.archive_path, args.page)