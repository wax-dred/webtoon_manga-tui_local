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
import io
import threading
import gc
from pdf2image import convert_from_path
import math

# Rediriger stdout et stderr vers /dev/null avant tout import
devnull = os.open(os.devnull, os.O_WRONLY)
stdout_orig = os.dup(1)
stderr_orig = os.dup(2)
os.dup2(devnull, 1)
os.dup2(devnull, 2)
os.close(devnull)

# Définir les variables d'environnement avant d'importer pygame
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
os.environ['SDL_LOGGING'] = '0'
os.environ['SDL_VIDEODRIVER'] = os.environ.get('XDG_SESSION_TYPE', 'wayland')

# Supprimer les logs
logging.getLogger().addHandler(logging.NullHandler())
logging.getLogger().setLevel(logging.CRITICAL + 1)

def cleanup():
    pygame.display.quit()
    pygame.quit()
    gc.collect()
    sys.exit(0)

def draw_rounded_rect(surface, color, rect, radius=10, width=0):
    """Dessiner un rectangle avec des coins arrondis"""
    if radius <= 0:
        pygame.draw.rect(surface, color, rect, width)
        return
    if radius > min(rect.width, rect.height) // 2:
        radius = min(rect.width, rect.height) // 2
    center_rect = pygame.Rect(rect.x + radius, rect.y, rect.width - 2 * radius, rect.height)
    if width == 0:
        pygame.draw.rect(surface, color, center_rect)
    else:
        pygame.draw.rect(surface, color, center_rect, width)
    left_rect = pygame.Rect(rect.x, rect.y + radius, radius, rect.height - 2 * radius)
    right_rect = pygame.Rect(rect.x + rect.width - radius, rect.y + radius, radius, rect.height - 2 * radius)
    if width == 0:
        pygame.draw.rect(surface, color, left_rect)
        pygame.draw.rect(surface, color, right_rect)
    else:
        pygame.draw.rect(surface, color, left_rect, width)
        pygame.draw.rect(surface, color, right_rect, width)
    corners = [
        (rect.x + radius, rect.y + radius),
        (rect.x + rect.width - radius, rect.y + radius),
        (rect.x + radius, rect.y + rect.height - radius),
        (rect.x + rect.width - radius, rect.y + rect.height - radius)
    ]
    for corner in corners:
        pygame.draw.circle(surface, color, corner, radius, width)

class ModernButton:
    def __init__(self, x, y, width, height, text, font, bg_color=(50, 50, 50), hover_color=(80, 80, 80), text_color=(255, 255, 255)):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.font = font
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.is_hovered = False
        self.is_pressed = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True
                return True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.is_pressed = False
        return False

    def draw(self, surface):
        # Utilisation d'un rectangle arrondi
        color = self.hover_color if self.is_hovered or self.is_pressed else self.bg_color
        draw_rounded_rect(surface, color, self.rect, radius=10)
        text_surface = self.font.render(self.text, True, self.text_color)
        text_rect = text_surface.get_rect(center=self.rect.center)
        surface.blit(text_surface, text_rect)

class ModernProgressBar:
    def __init__(self, x, y, width, height, radius=10):
        self.rect = pygame.Rect(x, y, width, height)
        self.radius = radius

    def draw(self, surface, progress, current_page, total_pages, show_text=True):
        # Dessiner la barre de progression avec coins arrondis
        pygame.draw.rect(surface, (100, 100, 100), self.rect)
        if progress < 0.34:
            fill_color = (0, 255, 0)
        elif progress < 0.67:
            fill_color = (255, 255, 0)
        else:
            fill_color = (255, 0, 0)
        filled_rect = pygame.Rect(self.rect.x, self.rect.y, int(self.rect.width * progress), self.rect.height)
        draw_rounded_rect(surface, fill_color, filled_rect, radius=self.radius)
        draw_rounded_rect(surface, (150, 150, 150), self.rect, radius=self.radius, width=2)  # Bordure arrondie
        if show_text:
            font = pygame.font.SysFont('arial', 14)
            text = f"{int(progress * 100)}% (Pg {current_page}/{total_pages})"
            text_surface = font.render(text, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=self.rect.center)
            surface.blit(text_surface, text_rect)

class WebtoonImageCache:
    def __init__(self, max_cache_size=30):
        self.cache = {}
        self.max_size = max_cache_size
        self.access_order = []
        self.lock = threading.Lock()
        self.loading = set()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                self.access_order.remove(key)
                self.access_order.append(key)
                return self.cache[key]
            return None

    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                self.access_order.remove(key)
            elif len(self.cache) >= self.max_size:
                for _ in range(min(10, len(self.access_order))):
                    oldest = self.access_order.pop(0)
                    if oldest in self.cache:
                        del self.cache[oldest]
                gc.collect()
            self.cache[key] = value
            self.access_order.append(key)
            if key in self.loading:
                self.loading.remove(key)

    def is_loading(self, key):
        with self.lock:
            return key in self.loading

    def mark_loading(self, key):
        with self.lock:
            self.loading.add(key)

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.access_order.clear()
            self.loading.clear()
            gc.collect()

    def aggressive_preload(self, images, screen_width, zoom, visible_range, mode='webtoon'):
        start_idx, end_idx = visible_range
        for i in range(max(0, start_idx - 2), min(len(images), end_idx + 5)):
            key = f"{images[i]}_{zoom:.2f if mode == 'webtoon' else 1.0}_{mode}"
            if self.get(key) is None and not self.is_loading(key):
                self.mark_loading(key)
                if mode == 'webtoon':
                    img_surface, size = load_image_to_pygame_webtoon(images[i], screen_width, zoom)
                else:  # mode == 'manga'
                    img_surface, size = load_image_to_pygame_manga(images[i], screen_width, screen_height)
                if img_surface:
                    self.put(key, (img_surface, size))

def get_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def extract_archive(archive_path, extract_to):
    archive_path = Path(archive_path)
    mime_type, _ = mimetypes.guess_type(archive_path)
    if mime_type == 'application/zip' or archive_path.suffix.lower() in ('.cbz', '.cbr'):
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            return True
        except zipfile.BadZipFile:
            return False
    elif mime_type in ('application/x-rar-compressed', 'application/vnd.comicbook-rar') or archive_path.suffix.lower() == '.cbr':
        try:
            with rarfile.RarFile(archive_path) as rar_ref:
                rar_ref.extractall(extract_to)
            return True
        except (rarfile.RarCannotExec, rarfile.NotRarFile):
            try:
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
                return True
            except zipfile.BadZipFile:
                return False
    elif mime_type == 'application/pdf' or archive_path.suffix.lower() == '.pdf':
        try:
            images = convert_from_path(archive_path, dpi=150)
            extract_path = Path(extract_to)
            extract_path.mkdir(parents=True, exist_ok=True)
            for i, img in enumerate(images):
                img_path = extract_path / f"page_{i+1:03d}.png"
                img.save(img_path, 'PNG')
            return True
        except Exception:
            return False
    else:
        return False

def get_image_files(directory):
    images = sorted(
        [f for f in Path(directory).iterdir() if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']],
        key=lambda x: (len(x.stem), x.stem)
    )
    return images

def load_image_to_pygame_webtoon(image_path, screen_width, zoom=1.0):
    try:
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img_width, img_height = img.size
            target_width = int(screen_width * 0.4 * zoom)
            if img_width != target_width:
                ratio = target_width / img_width
                new_height = int(img_height * ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            img_string = img.tobytes()
            return pygame.image.fromstring(img_string, img.size, 'RGB'), img.size
    except Exception:
        return None, (0, 0)

def load_image_to_pygame_manga(image_path, screen_width, screen_height):
    try:
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img_width, img_height = img.size
            width_ratio = screen_width / img_width
            height_ratio = screen_height / img_height
            ratio = min(width_ratio, height_ratio) * 0.9
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            img_string = img.tobytes()
            return pygame.image.fromstring(img_string, img.size, 'RGB'), img.size
    except Exception:
        return None, (0, 0)

def calculate_scroll_speed(zoom, base_speed=100):
    return int(base_speed * (zoom ** 0.8))

class WebtoonRenderer:
    def __init__(self, images, screen_width, screen_height, cache):
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cache = cache
        self.image_positions = []
        self.total_height = 0
        self.zoom = 1.0
        self.gap = 10

    def calculate_layout(self, zoom):
        self.zoom = zoom
        self.image_positions = []
        current_y = 0
        for i, img_path in enumerate(self.images):
            self.image_positions.append(current_y)
            cache_key = f"{img_path}_{zoom:.2f}_webtoon"
            cached = self.cache.get(cache_key)
            if cached:
                _, (width, height) = cached
            else:
                try:
                    with Image.open(img_path) as img:
                        img_width, img_height = img.size
                        target_width = int(self.screen_width * 0.4 * zoom)
                        ratio = target_width / img_width
                        height = int(img_height * ratio)
                except:
                    height = 1000
            current_y += height + self.gap
        self.total_height = current_y

    def get_visible_images(self, scroll_offset):
        visible_images = []
        top = scroll_offset
        bottom = scroll_offset + self.screen_height
        for i, y_pos in enumerate(self.image_positions):
            cache_key = f"{self.images[i]}_{self.zoom:.2f}_webtoon"
            cached = self.cache.get(cache_key)
            if cached:
                _, (width, height) = cached
            else:
                height = 1000
            if y_pos + height >= top and y_pos <= bottom:
                visible_images.append(i)
        return visible_images

    def render(self, screen, scroll_offset):
        # Mettre à jour les dimensions avant le rendu
        self.screen_width, self.screen_height = pygame.display.get_surface().get_size()
        visible_indices = self.get_visible_images(scroll_offset)
        for i in visible_indices:
            cache_key = f"{self.images[i]}_{self.zoom:.2f}_webtoon"
            cached = self.cache.get(cache_key)
            if cached:
                img_surface, (width, height) = cached
                target_width = int(self.screen_width * 0.4 * self.zoom)
                if width != target_width:
                    img_surface, (width, height) = load_image_to_pygame_webtoon(self.images[i], self.screen_width, self.zoom)
                    self.cache.put(cache_key, (img_surface, (width, height)))
                x = (self.screen_width - width) // 2
                print(f"Largeur écran: {self.screen_width}, Largeur image: {width}, Position X: {x}")
                y = self.image_positions[i] - scroll_offset
                if y + height >= 0 and y <= self.screen_height:
                    screen.blit(img_surface, (x, y))
            else:
                y = self.image_positions[i] - scroll_offset
                placeholder_height = 100
                if y + placeholder_height >= 0 and y <= self.screen_height:
                    placeholder_rect = pygame.Rect(50, y, self.screen_width - 100, placeholder_height)
                    pygame.draw.rect(screen, (50, 50, 50), placeholder_rect)
        return visible_indices

class MangaRenderer:
    def __init__(self, images, screen_width, screen_height, cache):
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cache = cache
        self.current_page = 0

    def calculate_layout(self):
        pass

    def next_page(self):
        if self.current_page < len(self.images) - 1:
            self.current_page += 1
            if self.current_page + 1 < len(self.images):
                key = f"{self.images[self.current_page + 1]}_1.0_manga"
                if self.cache.get(key) is None:
                    img_surface, size = load_image_to_pygame_manga(self.images[self.current_page + 1], self.screen_width, self.screen_height)
                    if img_surface:
                        self.cache.put(key, (img_surface, size))

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            if self.current_page - 1 >= 0:
                key = f"{self.images[self.current_page - 1]}_1.0_manga"
                if self.cache.get(key) is None:
                    img_surface, size = load_image_to_pygame_manga(self.images[self.current_page - 1], self.screen_width, self.screen_height)
                    if img_surface:
                        self.cache.put(key, (img_surface, size))

    def go_to_page(self, page):
        self.current_page = max(0, min(page, len(self.images) - 1))
        for i in range(max(0, self.current_page - 1), min(len(self.images), self.current_page + 2)):
            key = f"{self.images[i]}_1.0_manga"
            if self.cache.get(key) is None:
                img_surface, size = load_image_to_pygame_manga(self.images[i], screen_width, screen_height)
                if img_surface:
                    self.cache.put(key, (img_surface, size))

    def get_visible_images(self):
        return [self.current_page]

    def render(self, screen):
        # Mettre à jour les dimensions avant le rendu
        self.screen_width, self.screen_height = pygame.display.get_surface().get_size()
        visible_indices = self.get_visible_images()
        for i in visible_indices:
            cache_key = f"{self.images[i]}_1.0_manga"
            cached = self.cache.get(cache_key)
            if cached:
                img_surface, (width, height) = cached
                x = (self.screen_width - width) // 2
                y = (self.screen_height - height) // 2
                screen.blit(img_surface, (x, y))
            else:
                placeholder_rect = pygame.Rect(50, 50, self.screen_width - 100, self.screen_height - 100)
                pygame.draw.rect(screen, (50, 50, 50), placeholder_rect)
        return visible_indices

try:
    def main(archive_path):
        pygame.init()
        pygame.mixer.quit()
        
        screen_info = pygame.display.Info()
        screen_width, screen_height = screen_info.current_w - 100, screen_info.current_h - 100
        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE | pygame.DOUBLEBUF)
        pygame.display.set_caption(f"Lecteur Webtoon: {Path(archive_path).stem}")

        archive_path = Path(archive_path)
        if not archive_path.exists():
            cleanup()
            return

        cache_dir = Path.home() / ".manga_reader_cache" / get_file_hash(archive_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "image_list.pkl"

        images = []
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    images = pickle.load(f)
            except Exception:
                images = []
        else:
            with tempfile.TemporaryDirectory() as tmpdirname:
                tmp_path = Path(tmpdirname)
                if not extract_archive(archive_path, tmp_path):
                    cleanup()
                    return
                images = get_image_files(tmp_path)
                
                cached_images = []
                for img in images:
                    try:
                        dest = cache_dir / img.name
                        dest.write_bytes(img.read_bytes())
                        cached_images.append(dest)
                    except Exception:
                        continue
                
                if not cached_images:
                    cleanup()
                    return
                
                with open(cache_file, 'wb') as f:
                    pickle.dump(cached_images, f)
                images = cached_images

        images = [img for img in images if img.exists()]
        if not images:
            cleanup()
            return

        image_cache = WebtoonImageCache(max_cache_size=30)
        
        webtoon_renderer = WebtoonRenderer(images, screen_width, screen_height, image_cache)
        manga_renderer = MangaRenderer(images, screen_width, screen_height, image_cache)
        
        mode = 'webtoon'
        zoom = 1.0
        scroll_offset = 0
        webtoon_renderer.calculate_layout(zoom)

        def initial_preload():
            for i in range(min(20, len(images))):
                cache_key_webtoon = f"{images[i]}_{zoom:.2f}_webtoon"
                cache_key_manga = f"{images[i]}_1.0_manga"
                if not image_cache.get(cache_key_webtoon):
                    img_surface, size = load_image_to_pygame_webtoon(images[i], screen_width, zoom)
                    if img_surface:
                        image_cache.put(cache_key_webtoon, (img_surface, size))
                if not image_cache.get(cache_key_manga):
                    img_surface, size = load_image_to_pygame_manga(images[i], screen_width, screen_height)
                    if img_surface:
                        image_cache.put(cache_key_manga, (img_surface, size))
        
        preload_thread = threading.Thread(target=initial_preload, daemon=True)
        preload_thread.start()

        clock = pygame.time.Clock()
        font = pygame.font.SysFont('arial', 18, bold=True)
        mode_button = ModernButton(screen_width - 250, 10, 120, 30, f"{mode.capitalize()}", font)
        # Ajuster la taille et la position de la barre de progression
        progress_bar = ModernProgressBar(screen_width - 200, screen_height - 50, 180, 20)
        running = True
        last_resize_time = 0
        resize_debounce = 0.1  # 100ms de debounce
        last_preload_time = 0

        while running:
            current_time = pygame.time.get_ticks() / 1000.0
            
            # Mettre à jour les dimensions de l'écran à chaque frame
            screen_width, screen_height = pygame.display.get_surface().get_size()
            webtoon_renderer.screen_width = screen_width
            webtoon_renderer.screen_height = screen_height
            manga_renderer.screen_width = screen_width
            manga_renderer.screen_height = screen_height
            mode_button.rect.topleft = (screen_width - 250, 10)
            progress_bar.rect.topright = (screen_width - 20, screen_height - 30)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        running = False
                    elif event.key == pygame.K_w:
                        mode = 'webtoon'
                        mode_button.text = "Webtoon"
                        webtoon_renderer.calculate_layout(zoom)
                    elif event.type == pygame.VIDEORESIZE:
                        last_resize_time = current_time
                        screen_width, screen_height = event.w, event.h
                        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE | pygame.DOUBLEBUF)
                    elif event.key == pygame.K_m:
                        mode = 'manga'
                        mode_button.text = "Manga"
                        manga_renderer.go_to_page(manga_renderer.current_page)
                    elif mode == 'webtoon':
                        if event.key == pygame.K_HOME:
                            scroll_offset = 0
                        elif event.key == pygame.K_END:
                            scroll_offset = max(0, webtoon_renderer.total_height - screen_height)
                        elif event.key == pygame.K_PAGEDOWN:
                            scroll_offset += screen_height
                            scroll_offset = min(scroll_offset, max(0, webtoon_renderer.total_height - screen_height))
                        elif event.key == pygame.K_PAGEUP:
                            scroll_offset -= screen_height
                            scroll_offset = max(0, scroll_offset)
                    elif mode == 'manga':
                        if event.key == pygame.K_HOME:
                            manga_renderer.go_to_page(0)
                        elif event.key == pygame.K_END:
                            manga_renderer.go_to_page(len(images) - 1)
                        elif event.key == pygame.K_PAGEDOWN or event.key == pygame.K_DOWN or event.key == pygame.K_s:
                            manga_renderer.next_page()
                        elif event.key == pygame.K_PAGEUP or event.key == pygame.K_UP or event.key == pygame.K_w:
                            manga_renderer.prev_page()
                if mode_button.handle_event(event):
                    mode = 'manga' if mode == 'webtoon' else 'webtoon'
                    mode_button.text = mode.capitalize()
                    if mode == 'webtoon':
                        webtoon_renderer.calculate_layout(zoom)
                    else:
                        manga_renderer.go_to_page(manga_renderer.current_page)
                elif event.type == pygame.MOUSEWHEEL:
                    if mode == 'webtoon':
                        scroll_speed = calculate_scroll_speed(zoom)
                        scroll_offset -= event.y * scroll_speed * 2.0
                        scroll_offset = max(0, min(scroll_offset, max(0, webtoon_renderer.total_height - screen_height)))
                    elif mode == 'manga':
                        if event.y > 0:
                            manga_renderer.prev_page()
                        elif event.y < 0:
                            manga_renderer.next_page()

            keys = pygame.key.get_pressed()
            if mode == 'webtoon':
                if keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_SPACE]:
                    scroll_offset += calculate_scroll_speed(zoom) // 3
                    scroll_offset = min(scroll_offset, max(0, webtoon_renderer.total_height - screen_height))
                elif keys[pygame.K_UP] or keys[pygame.K_w] or keys[pygame.K_BACKSPACE]:
                    scroll_offset -= calculate_scroll_speed(zoom) // 3
                    scroll_offset = max(0, scroll_offset)
            elif mode == 'manga':
                if keys[pygame.K_DOWN] or keys[pygame.K_s]:
                    manga_renderer.next_page()
                elif keys[pygame.K_UP] or keys[pygame.K_w]:
                    manga_renderer.prev_page()

            # Traitement du redimensionnement après délai de debounce
            if last_resize_time > 0 and (current_time - last_resize_time) > resize_debounce:
                webtoon_renderer.screen_width = screen_width
                webtoon_renderer.screen_height = screen_height
                webtoon_renderer.calculate_layout(zoom)

                manga_renderer.screen_width = screen_width
                manga_renderer.screen_height = screen_height

                mode_button.rect.topleft = (screen_width - 250, 10)
                progress_bar.rect.topright = (screen_width - 20, screen_height - 30)

                image_cache.clear()
                last_resize_time = 0

            if current_time - last_preload_time > 0.1:
                if mode == 'webtoon':
                    visible_indices = webtoon_renderer.get_visible_images(scroll_offset)
                    if visible_indices:
                        start_idx, end_idx = min(visible_indices), max(visible_indices)
                        preload_thread = threading.Thread(
                            target=image_cache.aggressive_preload,
                            args=(images, screen_width, zoom, (start_idx, end_idx), mode),
                            daemon=True
                        )
                        preload_thread.start()
                        preload_thread.join(timeout=0.2)
                else:
                    visible_indices = manga_renderer.get_visible_images()
                    if visible_indices:
                        start_idx, end_idx = min(visible_indices), max(visible_indices)
                        preload_thread = threading.Thread(
                            target=image_cache.aggressive_preload,
                            args=(images, screen_width, 1.0, (start_idx, end_idx), mode),
                            daemon=True
                        )
                        preload_thread.start()
                        preload_thread.join(timeout=0.2)
                last_preload_time = current_time

            screen.fill((20, 20, 20))
            if mode == 'webtoon':
                visible_indices = webtoon_renderer.render(screen, scroll_offset)
                progress = min(1.0, scroll_offset / max(1, webtoon_renderer.total_height - screen_height)) if webtoon_renderer.total_height > screen_height else 1.0
            else:
                visible_indices = manga_renderer.render(screen)
                progress = manga_renderer.current_page / max(1, len(images) - 1) if len(images) > 1 else 1.0

            text = font.render(f"Webtoon: {Path(archive_path).stem}", True, (255, 255, 255))
            screen.blit(text, (10, 10))
            mode_button.draw(screen)
            current_page = min(visible_indices) + 1 if visible_indices else 1
            progress_bar.draw(screen, progress, current_page, len(images))
            pygame.display.flip()
            clock.tick(120)

        cleanup()

    if __name__ == "__main__":
        if len(sys.argv) != 2:
            sys.exit(1)
        main(sys.argv[1])

except Exception as e:
    cleanup()
    raise  # Pour voir l'erreur si elle se produit

finally:
    os.dup2(stdout_orig, 1)
    os.dup2(stderr_orig, 2)
    os.close(stdout_orig)
    os.close(stderr_orig)