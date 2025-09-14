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
from PIL import Image, ImageFilter
import threading
import gc
from pdf2image import convert_from_path
import json
import argparse
import time
import random
import math
import queue
import subprocess
import shutil
import sqlite3

# Configurer le logger
logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] %(message)s')

# Préparer Pygame
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
os.environ['SDL_LOGGING'] = '0'
os.environ['SDL_VIDEODRIVER'] = os.environ.get('XDG_SESSION_TYPE', 'wayland')

def load_wal_colors():
    """Charge les couleurs depuis ~/.cache/wal/wal.json ou retourne les couleurs par défaut."""
    default_colors = {
        "background": (20, 20, 20),
        "foreground": (255, 255, 255),
        "button_bg": (50, 50, 50),
        "button_hover": (80, 80, 80),
        "slider_bg": (50, 50, 50),
        "slider_handle": (80, 80, 80),
        "progress_bar_bg": (245, 247, 255),
        "progress_bar_left": (230, 237, 255),
        "progress_bar_right": (120, 170, 255),
        "progress_bubble": (255, 255, 255),
        "progress_bubble_text": (70, 90, 120),
        "thumbnail_bg": (20, 20, 20, 200),
        "color_12": (255, 253, 0),
        "colors_13": (255, 133, 0),
        "button_active": (255, 200, 0),
        "opacity": 0
    }
    wal_path = Path.home() / ".cache" / "wal" / "wal.json"
    if not wal_path.exists():
        logging.warning("wal.json non trouvé, utilisation des couleurs par défaut")
        return default_colors

    try:
        with open(wal_path, "r", encoding='utf-8') as f:
            wal_data = json.load(f)
        def hex_to_rgb(hex_str):
            hex_str = hex_str.lstrip('#')
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        
        colors = {}
        special = wal_data.get("special", {})
        colors["background"] = hex_to_rgb(special.get("background", "#222224"))
        colors["foreground"] = hex_to_rgb(special.get("foreground", "#E4C1B7"))
        wal_colors = wal_data.get("colors", {})
        colors["button_bg"] = hex_to_rgb(wal_colors.get("color0", "#48484A"))
        colors["button_hover"] = hex_to_rgb(wal_colors.get("color8", "#926F64"))
        colors["button_active"] = hex_to_rgb(wal_colors.get("color4", "#1E90FF"))
        colors["slider_bg"] = hex_to_rgb(wal_colors.get("color3", "#2B1513"))
        colors["slider_handle"] = hex_to_rgb(wal_colors.get("color12", "#D09E8F"))
        colors["progress_bar_bg"] = hex_to_rgb(wal_colors.get("color7", "#D09E8F"))
        colors["progress_bar_left"] = hex_to_rgb(wal_colors.get("color10", "#25262C"))
        colors["progress_bar_right"] = hex_to_rgb(wal_colors.get("color14", "#B34E30"))
        colors["colors_13"] = hex_to_rgb(wal_colors.get("color13", "#B34E30"))
        colors["progress_bubble"] = hex_to_rgb(special.get("foreground", "#E4C1B7"))
        colors["progress_bubble_text"] = hex_to_rgb(wal_colors.get("color5", "#713423"))
        colors["thumbnail_bg"] = (*hex_to_rgb(wal_colors.get("color0", "#48484A")), 200)
        colors["color_12"] = hex_to_rgb(wal_colors.get("color12", "#D09E8F"))
        colors["opacity"] = int(wal_data.get("alpha", "51").strip('%')) if isinstance(wal_data.get("alpha"), str) else 51
        logging.info(f"Couleurs chargées avec succès : {colors}")
        return colors
    except Exception as e:
        logging.error(f"Erreur lors du chargement de wal.json: {e}. Utilisation des couleurs par défaut.")
        return default_colors

def show_file_dialogue(initial_dir=None):
    """Affiche une fenêtre Pygame pour sélectionner un fichier d'archive."""
    pygame.init()
    sw, sh = 720, 480
    colors = load_wal_colors()
    screen = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
    pygame.display.set_caption("Manga Live - Sélectionner un fichier")
    
    current_dir = Path(initial_dir or Path.home()).expanduser().absolute()
    supported_extensions = {".cbz", ".cbr", ".zip", ".rar", ".pdf"}
    font = pygame.font.SysFont("arial", 18, bold=True)
    title_font = pygame.font.SysFont("comicsansms", 36, bold=True)
    
    # Pré-créer le masque pour les coins arrondis
    rounded_mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
    pygame.draw.rect(rounded_mask, (0, 0, 0, 0), (0, 0, sw, sh))
    pygame.draw.rect(rounded_mask, colors["foreground"], (0, 0, sw, sh), border_radius=10)
    
    # Pré-créer les particules
    particles = [
        {
            'x': random.randint(0, sw),
            'y': random.randint(0, sh),
            'size': random.uniform(1, 3),
            'alpha': 0,
            'target_alpha': random.randint(30, 60),
            'speed': random.uniform(0.1, 0.3),
            'phase': random.uniform(0, 2 * math.pi),
            'surface': pygame.Surface((int(random.uniform(1, 3) * 6), int(random.uniform(1, 3) * 6)), pygame.SRCALPHA)
        } for _ in range(10)
    ]
    
    file_entries = []
    buttons = []
    button_indices = []
    scroll_offset = 0
    selected_index = -1
    start_time = time.time()
    logo_alpha = 0
    logo_scale = 0.3
    file_list_alpha = 0
    
    def update_file_list():
        nonlocal file_entries
        file_entries = []
        if current_dir != current_dir.parent:
            file_entries.append(("..", current_dir.parent, True))
        try:
            for item in sorted(current_dir.iterdir()):
                if item.name.startswith('.'):
                    continue
                if item.is_dir():
                    file_entries.append((item.name, item, True))
                elif item.is_file() and item.suffix.lower() in supported_extensions:
                    file_entries.append((item.name, item, False))
        except PermissionError:
            logging.warning(f"Permission refusée pour accéder à {current_dir}")

    def update_buttons():
        nonlocal buttons, button_indices
        buttons = []
        button_indices = []
        for i, (name, path, is_dir) in enumerate(file_entries):
            y = 80 + i * 40 - scroll_offset
            if 80 <= y <= sh - 40:
                buttons.append(ModernButton(20, y, sw - 40, 30, name, font, colors))
                button_indices.append(i)

    update_file_list()
    clock = pygame.time.Clock()
    running = True
    while running:
        elapsed = time.time() - start_time
        
        # Animations
        if elapsed < 0.6:
            anim_progress = elapsed / 0.6
            logo_alpha = int(255 * min(1.0, anim_progress * 1.5))
            logo_scale = 0.3 + 0.7 * easeOutBounce(anim_progress)
        else:
            logo_alpha = 255
            logo_scale = 1.0
        
        if elapsed > 0.4:
            file_list_alpha = int(255 * min(1.0, (elapsed - 0.4) / 0.6))
        
        for particle in particles:
            if elapsed > 0.2:
                particle['alpha'] = min(particle['target_alpha'], particle['alpha'] + 1.5)
                particle['phase'] += particle['speed']
                particle['surface'].fill((0, 0, 0, 0))
                center = particle['size'] * 3
                for r in range(int(particle['size'] * 3), 0, -1):
                    alpha = min(255, particle['alpha'] // (r + 1))
                    pygame.draw.circle(particle['surface'], (*colors["slider_handle"], alpha), (center, center), r)

        update_buttons()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                return None
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN and selected_index >= 0:
                    name, path, is_dir = file_entries[selected_index]
                    if is_dir:
                        current_dir = path
                        scroll_offset = 0
                        selected_index = -1
                        update_file_list()
                    else:
                        pygame.quit()
                        return path
                elif event.key == pygame.K_UP:
                    selected_index = max(-1, selected_index - 1)
                    if selected_index >= 0 and (button_y := 80 + selected_index * 40 - scroll_settings) < 80:
                        scroll_offset = max(0, scroll_offset - 40)
                elif event.key == pygame.K_DOWN:
                    selected_index = min(len(file_entries) - 1, selected_index + 1)
                    if selected_index >= 0 and (button_y := 80 + selected_index * 40 - scroll_offset) > sh - 80:
                        scroll_offset = min((len(file_entries) * 40 - (sh - 120)), scroll_offset + 40)
                elif event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                    scroll_offset = max(0, min(scroll_offset + (sh - 120) * (-1 if event.key == pygame.K_PAGEUP else 1), len(file_entries) * 40 - (sh - 120)))
                elif pygame.K_a <= event.key <= pygame.K_z:
                    char = chr(event.key).lower()
                    for i, (name, _, _) in enumerate(file_entries):
                        if name.lower().startswith(char):
                            selected_index = i
                            scroll_offset = max(0, min(i * 40, len(file_entries) * 40 - (sh - 120)))
                            break
            elif event.type == pygame.MOUSEWHEEL:
                scroll_offset = max(0, min(scroll_offset - event.y * 40, len(file_entries) * 40 - (sh - 120)))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, button in enumerate(buttons):
                    if button.handle_event(event):
                        selected_index = button_indices[i]
                        name, path, is_dir = file_entries[selected_index]
                        if is_dir:
                            current_dir = path
                            scroll_offset = 0
                            selected_index = -1
                            update_file_list()
                        else:
                            pygame.quit()
                            return path

        screen.fill(colors["background"])
        screen.blit(rounded_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        
        for particle in particles:
            if particle['alpha'] > 0:
                x = particle['x'] + math.sin(particle['phase']) * 4
                y = particle['y'] + math.cos(particle['phase'] * 0.8) * 3
                screen.blit(particle['surface'], (x - particle['size'] * 3, y - particle['size'] * 3))
        
        if logo_alpha > 0:
            font_size = max(32, min(39, int(36 * logo_scale)))
            title_text = title_font.render("Sélectionner un fichier", True, colors["slider_handle"])
            title_text.set_alpha(logo_alpha)
            screen.blit(title_text, title_text.get_rect(center=(sw // 2, 30)))
        
        path_text = font.render(str(current_dir), True, colors["button_hover"])
        path_text.set_alpha(file_list_alpha)
        screen.blit(path_text, (20, 60))
        
        for i, button in enumerate(buttons):
            button.is_hovered = (button_indices[i] == selected_index)
            button.draw(screen)
        
        if len(file_entries) * 40 > sh - 120:
            scrollbar_height = int(((sh - 120) / (len(file_entries) * 40)) * (sh - 120))
            scrollbar_pos = int((scroll_offset / (len(file_entries) * 40 - (sh - 120))) * (sh - 120))
            pygame.draw.rect(screen, colors["button_hover"], (sw - 10, 80 + scrollbar_pos, 6, scrollbar_height), border_radius=3)

        pygame.display.flip()
        clock.tick(60)

def cleanup(cache_dir=None):
    """Nettoie les ressources et termine le programme."""
    if cache_dir:
        try:
            shutil.rmtree(cache_dir)
            logging.info(f"Cache supprimé : {cache_dir}")
        except Exception as e:
            logging.warning(f"Impossible de supprimer le cache : {e}")
    pygame.quit()
    gc.collect()
    sys.exit(0)

def show_splash(image_path=None, wait_time=1.0, colors=None):
    """Affiche un écran de démarrage avec animation."""
    pygame.init()
    sw, sh = 640, 400
    colors = colors or load_wal_colors()
    screen = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
    pygame.display.set_caption("Manga Live - Chargement...")
    
    start_time = time.time()
    logo_alpha = 0
    logo_scale = 0.3
    text_alpha = 0
    particles = [
        {
            'x': sw // 2 + ((-1) ** i) * (60 + i * 20),
            'y': sh // 2 + ((-1) ** (i // 2)) * (30 + i * 12),
            'size': 1 + (i % 3),
            'alpha': 0,
            'target_alpha': 40 + (i * 6),
            'speed': 0.2 + (i * 0.08),
            'phase': i * 0.5
        } for i in range(3)
    ]
    
    while time.time() - start_time < wait_time:
        elapsed = time.time() - start_time
        
        if elapsed < 0.6:
            anim_progress = elapsed / 0.6
            logo_alpha = int(255 * min(1.0, anim_progress * 1.5))
            logo_scale = 0.3 + 0.7 * easeOutBounce(anim_progress)
        else:
            logo_alpha = 255
            logo_scale = 1.0
        
        if elapsed > 0.4:
            text_alpha = int(255 * min(1.0, (elapsed - 0.4) / 0.6))
        
        for particle in particles:
            if elapsed > 0.2:
                particle['alpha'] = min(particle['target_alpha'], particle['alpha'] + 1.5)
                particle['phase'] += particle['speed']
        
        screen.fill(colors["background"])
        
        if image_path and Path(image_path).exists():
            try:
                with Image.open(image_path) as im:
                    im = im.convert("RGB").filter(ImageFilter.GaussianBlur(6))
                    im.thumbnail((sw + 20, sh + 20))
                    bg_surf = pygame.transform.scale(pygame.image.fromstring(im.tobytes(), im.size, "RGB"), (sw + 20, sh + 20))
                    offset_x = int(math.sin(elapsed * 0.3) * 3)
                    offset_y = int(math.cos(elapsed * 0.2) * 2)
                    screen.blit(bg_surf, (-10 + offset_x, -10 + offset_y))
                    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, int(120 + 20 * math.sin(elapsed * 0.5))))
                    screen.blit(overlay, (0, 0))
            except Exception:
                pass
        
        for particle in particles:
            if particle['alpha'] > 0:
                x = particle['x'] + math.sin(particle['phase']) * 4
                y = particle['y'] + math.cos(particle['phase'] * 0.8) * 3
                surf = pygame.Surface((particle['size'] * 6, particle['size'] * 6), pygame.SRCALPHA)
                for r in range(particle['size'] * 3, 0, -1):
                    pygame.draw.circle(surf, (*colors["slider_handle"], particle['alpha'] // (r + 1)), (particle['size'] * 3, particle['size'] * 3), r)
                screen.blit(surf, (x - particle['size'] * 3, y - particle['size'] * 3))
        
        if logo_alpha > 0:
            font = pygame.font.SysFont("comicsansms", int(54 * logo_scale), bold=True)
            for layer in range(5, 0, -1):
                glow_alpha = (logo_alpha // 5) // layer
                glow_font = pygame.font.SysFont("comicsansms", int(54 * logo_scale) + layer * 2, bold=True)
                glow_text = glow_font.render("Manga Live", True, colors["slider_handle"])
                glow_text.set_alpha(glow_alpha)
                screen.blit(glow_text, glow_text.get_rect(center=(sw // 2, sh // 2 - 40)))
            
            text = font.render("Manga Live", True, colors["foreground"])
            text.set_alpha(logo_alpha)
            shake_x = int(math.sin(elapsed * 8) * (1 - logo_scale) * 2)
            shake_y = int(math.cos(elapsed * 12) * (1 - logo_scale) * 1)
            screen.blit(text, text.get_rect(center=(sw // 2 + shake_x, sh // 2 - 40 + shake_y)))
        
        if text_alpha > 0:
            font2 = pygame.font.SysFont("arial", int(28 * (0.8 + 0.2 * math.sin(elapsed * 3))))
            t2 = font2.render(f"Chargement du Webtoon{'.' * (int(elapsed * 2) % 4)}", True, colors["button_hover"])
            t2.set_alpha(text_alpha)
            screen.blit(t2, t2.get_rect(center=(sw // 2, sh // 2 + 45)))
        
        pygame.display.flip()
        pygame.time.wait(16)
    
    for alpha in range(255, 0, -15):
        fade_surf = pygame.Surface((sw, sh))
        fade_surf.fill((0, 0, 0))
        fade_surf.set_alpha(255 - alpha)
        screen.blit(fade_surf, (0, 0))
        pygame.display.flip()
        pygame.time.wait(20)
    pygame.quit()

def easeOutBounce(t):
    """Fonction d'easing pour animation bounce."""
    if t < (1 / 2.75): return 7.5625 * t * t
    elif t < (2 / 2.75): return 7.5625 * (t - (1.5 / 2.75)) * (t - (1.5 / 2.75)) + 0.75
    elif t < (2.5 / 2.75): return 7.5625 * (t - (2.25 / 2.75)) * (t - (2.25 / 2.75)) + 0.9375
    return 7.5625 * (t - (2.625 / 2.75)) * (t - (2.625 / 2.75)) + 0.984375

class ProgressManager:
    """Gère la progression de lecture dans une base de données SQLite."""
    def __init__(self):
        self.db_path = Path.home() / ".config" / "manga_reader" / "library.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            return conn
        except sqlite3.Error as e:
            logging.error(f"Erreur de connexion à la base de données : {e}")
            raise

    def save(self, manga_name, chapter_number, current_page, total_pages, force_save=False):
        try:
            chapter_key = f"{float(chapter_number):.1f}"
            is_completed = current_page >= total_pages
            with self._connect_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
                manga_id = cursor.fetchone()
                if not manga_id:
                    logging.error(f"Manga {manga_name} non trouvé.")
                    return
                manga_id = manga_id[0]
                
                cursor.execute("SELECT id FROM chapters WHERE manga_id = ? AND num = ?", (manga_id, float(chapter_number)))
                chapter_id = cursor.fetchone()
                if not chapter_id:
                    logging.error(f"Chapitre {chapter_number} non trouvé pour {manga_name}.")
                    return
                chapter_id = chapter_id[0]
                
                cursor.execute("SELECT last_page_read FROM chapters WHERE id = ?", (chapter_id,))
                existing_page = cursor.fetchone()[0] or 0
                
                if force_save or current_page > existing_page or is_completed:
                    cursor.execute(
                        "UPDATE chapters SET read = ?, last_page_read = ?, full_pages_read = ? WHERE id = ?",
                        (is_completed, current_page, total_pages, chapter_id)
                    )
                    conn.commit()
                    logging.debug(f"Progression sauvegardée : {manga_name}, chapitre {chapter_number}, page {current_page}/{total_pages}")
        except sqlite3.Error as e:
            logging.error(f"Erreur sauvegarde progression : {e}")

    def load(self, manga_name, chapter_number):
        try:
            with self._connect_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
                manga_id = cursor.fetchone()
                if not manga_id:
                    logging.warning(f"Manga {manga_name} non trouvé.")
                    return 1
                manga_id = manga_id[0]
                
                cursor.execute("SELECT last_page_read FROM chapters WHERE manga_id = ? AND num = ?", (manga_id, float(chapter_number)))
                result = cursor.fetchone()
                return max(1, result[0]) if result and result[0] is not None else 1
        except sqlite3.Error as e:
            logging.error(f"Erreur chargement progression : {e}")
            return 1

def migrate_progress_json(db_path, progress_path):
    """Migre les données de progression depuis progress.json vers SQLite."""
    if not progress_path.exists():
        logging.info("Aucun fichier progress.json trouvé.")
        return

    try:
        with open(progress_path, 'r', encoding='utf-8') as f:
            progress_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Erreur lecture progress.json : {e}")
        return

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            for manga_name, chapters in progress_data.items():
                cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
                manga_result = cursor.fetchone()
                if not manga_result:
                    logging.warning(f"Manga '{manga_name}' non trouvé, ignoré.")
                    continue
                manga_id = manga_result[0]
                for chapter_num, data in chapters.items():
                    try:
                        chapter_num_float = float(chapter_num)
                        read = data.get("read", False)
                        last_page_read = data.get("last_page", 0)
                        full_pages_read = data.get("total_pages", 0)
                        cursor.execute("SELECT id FROM chapters WHERE manga_id = ? AND num = ?", (manga_id, chapter_num_float))
                        chapter_result = cursor.fetchone()
                        if not chapter_result:
                            logging.warning(f"Chapitre {chapter_num} pour '{manga_name}' non trouvé, ignoré.")
                            continue
                        chapter_id = chapter_result[0]
                        cursor.execute(
                            "UPDATE chapters SET read = ?, last_page_read = ?, full_pages_read = ? WHERE id = ?",
                            (read, last_page_read, full_pages_read, chapter_id)
                        )
                        logging.debug(f"Progression migrée : {manga_name}, chapitre {chapter_num}")
                    except ValueError:
                        logging.warning(f"Numéro de chapitre invalide '{chapter_num}' pour '{manga_name}'.")
            conn.commit()
            logging.info("Migration terminée.")
    except sqlite3.Error as e:
        logging.error(f"Erreur migration vers SQLite : {e}")
        return

    try:
        if progress_path.exists():
            progress_path.rename(progress_path.with_suffix(".json.bak"))
            logging.info(f"Fichier {progress_path} renommé en {progress_path.with_suffix('.json.bak')}")
    except (PermissionError, OSError) as e:
        logging.error(f"Erreur renommage {progress_path} : {e}")

def parse_manga_and_chapter(archive_path):
    """Extrait le nom du manga et le numéro du chapitre depuis le chemin de l'archive."""
    p = Path(archive_path).expanduser().absolute()
    manga_name = p.parent.name
    chapter_raw = p.stem
    chapter_number = chapter_raw.replace("Chapitre_", "") if "Chapitre_" in chapter_raw else chapter_raw
    return manga_name, chapter_number

def get_file_hash(file_path):
    """Calcule le hachage MD5 d'un fichier."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def extract_archive(archive_path, extract_to):
    archive_path = Path(archive_path).expanduser().absolute()
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
    """Récupère les fichiers d'image triés dans un dossier."""
    supported_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    files = list(Path(directory).iterdir())
    logging.debug(f"Fichiers trouvés dans {directory}: {files}")
    images = sorted(
        [f for f in files if f.is_file() and f.suffix.lower() in supported_extensions],
        key=lambda x: (len(x.stem), x.stem)
    )
    logging.debug(f"Images valides trouvées : {images}")
    return images

def load_image_to_pygame(image_path, screen_width, screen_height, zoom=1.0, mode='webtoon'):
    """Charge une image et la redimensionne pour Pygame."""
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
                ratio = min(screen_width / iw, screen_height / ih) * 0.9 * zoom
                size = (int(iw * ratio), int(ih * ratio))
            img = img.resize(size, Image.Resampling.LANCZOS)
            return pygame.image.fromstring(img.tobytes(), img.size, 'RGB'), img.size
    except Exception as e:
        logging.error(f"Erreur chargement image {image_path}: {e}")
        return None, (0, 0)

class ImageCache:
    """Cache LRU pour les images."""
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
                old = self.order.pop(0)
                self.cache.pop(old, None)
            self.cache[key] = value
            self.order.append(key)

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.order.clear()
            gc.collect()

class ImageLoaderThread:
    """Thread pour charger les images en arrière-plan."""
    def __init__(self, cache, images, screen_width, screen_height, zoom, mode='webtoon'):
        self.cache = cache
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.zoom = zoom
        self.mode = mode
        self.queue = queue.Queue()
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while self.running:
            try:
                idx, key = self.queue.get(timeout=0.1)
                if self.cache.get(key) is None and 0 <= idx < len(self.images):
                    img, size = load_image_to_pygame(self.images[idx], self.screen_width, self.screen_height, self.zoom, self.mode)
                    if img:
                        self.cache.put(key, (img, size))
                self.queue.task_done()
            except queue.Empty:
                continue

    def stop(self):
        self.running = False
        self.thread.join()

    def preload(self, visible_indices):
        if not visible_indices or not self.images:
            return
        start, end = min(visible_indices), max(visible_indices)
        for i in range(max(0, start-3), min(len(self.images), end+3)):
            key = f"{self.images[i]}_{self.zoom:.2f}_{self.mode}"
            if self.cache.get(key) is None:
                self.queue.put((i, key))

def detect_mode(images):
    """Détermine si le contenu est un webtoon ou un manga."""
    webtoon, manga = 0, 0
    for img_path in images[:5]:  # Limiter à 5 images pour optimiser
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

class ModernButton:
    """Bouton stylé avec survol."""
    def __init__(self, x, y, w, h, text, font, colors):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.font = font
        self.bg_color = colors["button_bg"]
        self.hover_color = colors["button_hover"]
        self.text_color = colors["colors_13"]
        self.is_hovered = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            return True
        return False

    def draw(self, surface):
        color = self.hover_color if self.is_hovered else self.bg_color
        pygame.draw.rect(surface, color, self.rect, border_radius=10)
        text_surf = self.font.render(self.text, True, self.text_color)
        surface.blit(text_surf, text_surf.get_rect(center=self.rect.center))

class Slider:
    """Curseur pour ajuster la vitesse de défilement."""
    def __init__(self, x, y, width, height, min_value, max_value, initial_value, colors):
        self.rect = pygame.Rect(x, y, width, height)
        self.min_value = min_value
        self.max_value = max_value
        self.value = initial_value
        self.bg_color = colors["slider_bg"]
        self.handle_color = colors["slider_handle"]
        self.text_color = colors["foreground"]
        self.handle_width = 10
        self.dragging = False
        self.update_handle_position()

    def update_handle_position(self):
        ratio = (self.value - self.min_value) / (self.max_value - self.min_value)
        self.handle_x = self.rect.x + int(ratio * (self.rect.width - self.handle_width))
        self.handle_rect = pygame.Rect(self.handle_x, self.rect.y, self.handle_width, self.rect.height)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.handle_rect.collidepoint(event.pos):
            self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            mouse_x = max(self.rect.x, min(event.pos[0], self.rect.x + self.rect.width - self.handle_width))
            ratio = (mouse_x - self.rect.x) / (self.rect.width - self.handle_width)
            self.value = self.min_value + ratio * (self.max_value - self.min_value)
            self.update_handle_position()

    def draw(self, surface):
        pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=10)
        pygame.draw.rect(surface, self.handle_color, self.handle_rect, border_radius=5)
        font = pygame.font.SysFont('arial', 18, bold=True)
        text = font.render(f"Speed: {int(self.value)}", True, self.text_color)
        surface.blit(text, text.get_rect(center=(self.rect.centerx, self.rect.y + self.rect.height + 15)))

class ThumbnailViewer:
    """Afficheur de vignettes pour naviguer dans les pages."""
    def __init__(self, x, y, width, height, images, cache, screen_width, screen_height, colors, cache_dir):
        self.rect = pygame.Rect(x, y, width, height)
        self.images = images
        self.cache = cache
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.thumbnail_size = (100, 150)
        self.gap = 10
        self.visible = False
        self.scroll_offset = 0
        self.thumbnails = []
        self.bg_color = colors["thumbnail_bg"]
        self.text_color = colors["foreground"]
        self.cache_dir = cache_dir
        self.generate_thumbnails()
        self.calculate_layout()

    def generate_thumbnails(self):
        self.thumbnails = []
        for img_path in self.images:
            img_name = Path(img_path).name
            thumb_key = f"thumb_{img_name}"
            thumb_file = self.cache_dir / f"{thumb_key}.png"
            if thumb_file.exists():
                try:
                    with Image.open(thumb_file) as img:
                        img = img.convert('RGB')
                        thumb_surf = pygame.image.fromstring(img.tobytes(), img.size, 'RGB')
                        self.cache.put(thumb_key, (thumb_surf, img.size))
                    self.thumbnails.append(thumb_key)
                    continue
                except Exception:
                    pass
            try:
                with Image.open(img_path) as img:
                    img = img.convert('RGB')
                    img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                    img.save(thumb_file, 'PNG')
                    thumb_surf = pygame.image.fromstring(img.tobytes(), img.size, 'RGB')
                    self.cache.put(thumb_key, (thumb_surf, img.size))
                self.thumbnails.append(thumb_key)
            except Exception as e:
                logging.error(f"Erreur génération vignette {img_path}: {e}")
                thumb_surf = pygame.Surface(self.thumbnail_size)
                thumb_surf.fill((50, 50, 50))
                self.cache.put(thumb_key, (thumb_surf, self.thumbnail_size))
                self.thumbnails.append(thumb_key)

    def calculate_layout(self):
        self.positions = [i * (self.thumbnail_size[1] + self.gap) for i in range(len(self.thumbnails))]
        self.total_height = self.positions[-1] + self.thumbnail_size[1] if self.positions else 0

    def scroll_to_current_page(self, current_page):
        if current_page <= 0 or not self.positions:
            return
        page_idx = current_page - 1
        self.scroll_offset = max(0, min(self.positions[page_idx] - self.rect.height // 2, self.total_height - self.rect.height))

    def get_visible_indices(self):
        top, bottom = self.scroll_offset, self.scroll_offset + self.rect.height
        return [i for i, y in enumerate(self.positions) if y + self.thumbnail_size[1] >= top and y <= bottom]

    def handle_event(self, event):
        if not self.visible:
            return None
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = max(0, min(self.scroll_offset - event.y * 50, self.total_height - self.rect.height))
            return "consumed"
        elif event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            rel_y = event.pos[1] - self.rect.y + self.scroll_offset
            for i, y in enumerate(self.positions):
                if y <= rel_y < y + self.thumbnail_size[1]:
                    return i + 1
        return None

    def draw(self, surface, current_page):
        if not self.visible:
            return
        pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=10)
        visible_indices = self.get_visible_indices()
        font = pygame.font.SysFont('arial', 18, bold=True)
        for i in visible_indices:
            thumb_key = self.thumbnails[i]
            cached = self.cache.get(thumb_key)
            if not cached:
                thumb_file = self.cache_dir / f"{thumb_key}.png"
                try:
                    with Image.open(self.images[i]) as img:
                        img = img.convert('RGB')
                        img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                        img.save(thumb_file, 'PNG')
                        thumb_surf = pygame.image.fromstring(img.tobytes(), img.size, 'RGB')
                        self.cache.put(thumb_key, (thumb_surf, img.size))
                        cached = (thumb_surf, img.size)
                except Exception as e:
                    logging.error(f"Erreur régénération vignette {self.images[i]}: {e}")
                    thumb_surf = pygame.Surface(self.thumbnail_size)
                    thumb_surf.fill((50, 50, 50))
                    cached = (thumb_surf, self.thumbnail_size)
                    self.cache.put(thumb_key, cached)
            thumb_surf, thumb_size = cached
            y = self.rect.y + self.positions[i] - self.scroll_offset
            surface.blit(thumb_surf, (self.rect.x + (self.rect.width - thumb_size[0]) // 2, y))
            if i + 1 == current_page:
                pygame.draw.rect(surface, self.text_color, (self.rect.x, y, self.rect.width, thumb_size[1]), width=2, border_radius=5)

class ModernProgressBar:
    """Barre de progression stylée."""
    def __init__(self, x, y, width, height, colors):
        self.rect = pygame.Rect(x, y, width, height)
        self.progress = 0.0
        self.colors = colors

    def draw(self, surface, progress, current_page, total_pages):
        self.progress += (progress - self.progress) * 0.2
        percent = int(self.progress * 100)
        
        pygame.draw.rect(surface, self.colors["button_bg"], self.rect, border_radius=10)
        inner_rect = self.rect.inflate(-10, -10)
        fill_width = int(inner_rect.width * self.progress)
        if fill_width > 0:
            fill_rect = pygame.Rect(inner_rect.x, inner_rect.y, fill_width, inner_rect.height)
            for x in range(fill_width):
                t = x / max(fill_width - 1, 1)
                r = int(self.colors["progress_bar_right"][0] + (self.colors["progress_bar_left"][0] - self.colors["progress_bar_right"][0]) * t)
                g = int(self.colors["progress_bar_right"][1] + (self.colors["progress_bar_left"][1] - self.colors["progress_bar_right"][1]) * t)
                b = int(self.colors["progress_bar_right"][2] + (self.colors["progress_bar_left"][2] - self.colors["progress_bar_right"][2]) * t)
                pygame.draw.line(surface, (r, g, b), (inner_rect.x + x, inner_rect.y), (inner_rect.x + x, inner_rect.y + inner_rect.height))
        
        if fill_width > 40:
            cx = inner_rect.x + fill_width
            cy = inner_rect.centery
            bubble_radius = inner_rect.height // 2 + 4
            pygame.draw.circle(surface, self.colors["progress_bar_right"], (cx, cy), bubble_radius)
            font = pygame.font.SysFont('arial', int(bubble_radius * 1.4), bold=True)
            text_surface = font.render(f"{percent}%", True, self.colors["slider_handle"])
            surface.blit(text_surface, text_surface.get_rect(center=(cx, cy)))
        else:
            font = pygame.font.SysFont('arial', int(self.rect.height * 0.7), bold=True)
            text_surface = font.render(f"{percent}%", True, self.colors["progress_bar_bg"])
            surface.blit(text_surface, text_surface.get_rect(center=self.rect.center))

class WebtoonRenderer:
    """Rendu pour le mode Webtoon sans espace entre les pages."""
    def __init__(self, images, screen_width, screen_height, cache, sizes=None):
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cache = cache
        self.zoom = 1.0
        self.image_positions = []
        self.image_sizes = {}
        self.total_height = 0
        self.sizes = sizes or {}
        self.calculate_layout(self.zoom)

    def calculate_layout(self, zoom):
        self.zoom = zoom
        self.image_positions = []
        self.image_sizes = {}
        y = 0
        target_width = int(self.screen_width * 0.4 * zoom)
        for img_path in self.images:
            img_name = str(Path(img_path).name)
            if img_name in self.sizes:
                iw, ih = self.sizes[img_name]["w"], self.sizes[img_name]["h"]
                ratio = target_width / iw if iw != 0 else 1
                w, h = target_width, int(ih * ratio)
            else:
                try:
                    with Image.open(img_path) as img:
                        iw, ih = img.size
                        self.sizes[img_name] = {"w": iw, "h": ih}
                        ratio = target_width / iw if iw != 0 else 1
                        w, h = target_width, int(ih * ratio)
                except Exception:
                    w, h = target_width, 1000
            self.image_sizes[img_path] = (w, h)
            self.image_positions.append(y)
            y += h  # Pas d'espace entre les pages
        self.total_height = y
        self.cache.clear()

    def get_visible_indices(self, scroll_offset):
        indices = []
        for i, y in enumerate(self.image_positions):
            h = self.image_sizes[self.images[i]][1]
            if y + h >= scroll_offset and y <= scroll_offset + self.screen_height:
                indices.append(i)
        return indices

    def render(self, screen, scroll_offset):
        self.screen_width, self.screen_height = screen.get_size()
        indices = self.get_visible_indices(scroll_offset)
        for i in indices:
            img_path = self.images[i]
            key = f"{img_path}_{self.zoom:.2f}_webtoon"
            w, h = self.image_sizes[img_path]
            cached = self.cache.get(key)
            if cached:
                img, _ = cached
            else:
                img, _ = load_image_to_pygame(img_path, self.screen_width, self.screen_height, self.zoom, 'webtoon')
                if img:
                    self.cache.put(key, (img, (w, h)))
            x = (self.screen_width - w) // 2
            y = self.image_positions[i] - scroll_offset
            if y + h >= 0 and y <= self.screen_height:
                screen.blit(img or pygame.Surface((w, h)).fill((50, 50, 50)), (x, y))
        return indices

    def page_from_offset(self, scroll_offset):
        screen_center = scroll_offset + self.screen_height // 2
        page = 1
        for i, pos in enumerate(self.image_positions):
            if pos <= screen_center:
                page = i + 1
            else:
                break
        return min(page, len(self.images))

class MangaRenderer:
    """Rendu pour le mode Manga avec transition de page."""
    def __init__(self, images, screen_width, screen_height, cache):
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cache = cache
        self.current_page = 0
        self.transition_progress = 0.0
        self.transition_direction = 0
        self.zoom = 1.0

    def next_page(self):
        if self.current_page < len(self.images) - 1 and self.transition_progress == 0:
            self.transition_direction = 1
            self.transition_progress = 0.01

    def prev_page(self):
        if self.current_page > 0 and self.transition_progress == 0:
            self.transition_direction = -1
            self.transition_progress = 0.01

    def go_to_page(self, page):
        if self.transition_progress == 0:
            self.current_page = max(0, min(page, len(self.images)-1))
            self.transition_progress = 0
            self.transition_direction = 0

    def update_transition(self):
        if self.transition_progress > 0:
            self.transition_progress += 0.05
            if self.transition_progress >= 1.0:
                self.transition_progress = 0
                self.current_page += self.transition_direction
                self.transition_direction = 0

    def render(self, screen):
        self.screen_width, self.screen_height = screen.get_size()
        i = self.current_page
        key = f"{self.images[i]}_{self.zoom:.2f}_manga"
        cached = self.cache.get(key)
        if cached:
            img, (w, h) = cached
        else:
            img, (w, h) = load_image_to_pygame(self.images[i], self.screen_width, self.screen_height, self.zoom, 'manga')
            if img:
                self.cache.put(key, (img, (w, h)))
        
        x_current = (self.screen_width - w) // 2
        y = (self.screen_height - h) // 2
        
        if self.transition_progress > 0:
            offset = int(self.screen_width * self.transition_progress * self.transition_direction)
            x_current -= offset
            next_page = self.current_page + self.transition_direction
            if 0 <= next_page < len(self.images):
                key_next = f"{self.images[next_page]}_{self.zoom:.2f}_manga"
                cached_next = self.cache.get(key_next)
                if cached_next:
                    img_next, (w_next, h_next) = cached_next
                else:
                    img_next, (w_next, h_next) = load_image_to_pygame(self.images[next_page], self.screen_width, self.screen_height, self.zoom, 'manga')
                    if img_next:
                        self.cache.put(key_next, (img_next, (w_next, h_next)))
                screen.blit(img_next, (x_current + (self.screen_width * self.transition_direction), (self.screen_height - h_next) // 2))
        
        screen.blit(img or pygame.Surface((self.screen_width-100, self.screen_height-100)).fill((50, 50, 50)), (x_current, y))
        return [i]

def run_reader(archive_path=None, start_page=1, cache_dir=None):
    """Exécute le lecteur de manga/webtoon."""
    pygame.init()
    colors = load_wal_colors()
    screen_info = pygame.display.Info()
    screen_width, screen_height = screen_info.current_w - 200, screen_info.current_h - 200
    screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE | pygame.DOUBLEBUF)
    pygame.display.set_caption("Lecteur Webtoon")
    
    if not archive_path:
        archive_path = show_file_dialogue()
        if not archive_path:
            cleanup(cache_dir)
    
    archive_path = Path(archive_path).expanduser().absolute()
    logging.info(f"Traitement de l'archive : {archive_path}")
    if not archive_path.exists():
        logging.error(f"Le fichier {archive_path} n'existe pas.")
        cleanup(cache_dir)
    
    cache_dir = cache_dir or (Path.home() / ".config" / "manga_reader" / "manga_reader_cache" / get_file_hash(archive_path))
    logging.info(f"Dossier de cache : {cache_dir}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "image_list.pkl"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                images = pickle.load(f)
            logging.info(f"Cache chargé : {len(images)} fichiers trouvés dans {cache_file}")
            for img in images:
                logging.debug(f"Fichier dans le cache : {img}")
        except Exception as e:
            images = []
            logging.error(f"Erreur chargement cache : {e}")
    else:
        cached_images = get_image_files(cache_dir)
        logging.info(f"Vérification des images en cache : {len(cached_images)} fichiers trouvés")
        if cached_images:
            images = cached_images
            with open(cache_file, 'wb') as f:
                pickle.dump(cached_images, f)
            logging.info(f"Cache créé avec {len(images)} fichiers")
        else:
            logging.info(f"Extraction de l'archive vers un dossier temporaire")
            with tempfile.TemporaryDirectory() as tmpdirname:
                tmp_path = Path(tmpdirname)
                if not extract_archive(archive_path, tmp_path):
                    logging.error(f"Échec extraction {archive_path}")
                    cleanup(cache_dir)
                images = get_image_files(tmp_path)
                logging.info(f"Images extraites : {len(images)} fichiers trouvés dans {tmp_path}: {images}")
                for img in images:
                    dest = cache_dir / img.name
                    try:
                        dest.write_bytes(img.read_bytes())
                        logging.debug(f"Copié {img} vers {dest}")
                    except Exception as e:
                        logging.error(f"Erreur copie {img} vers {dest}: {e}")
                with open(cache_file, 'wb') as f:
                    pickle.dump(images, f)
                logging.info(f"Cache créé : {cache_file}")
    
    images = [img for img in images if img.exists()]
    logging.info(f"Images valides après filtrage : {len(images)} fichiers")
    if not images:
        logging.error("Aucune image valide trouvée.")
        cleanup(cache_dir)
    
    show_splash(images[0], colors=colors)
    pygame.display.quit()
    pygame.display.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF)
    screen_width, screen_height = screen.get_size()
    pygame.display.set_caption(f"Lecteur Webtoon: {Path(archive_path).stem}")
    
    sizes_file = cache_dir / "sizes.json"
    sizes = {}
    if sizes_file.exists():
        with open(sizes_file, "r", encoding="utf-8") as f:
            sizes = json.load(f)
    else:
        for img in images:
            try:
                with Image.open(img) as im:
                    sizes[str(img.name)] = {"w": im.width, "h": im.height}
            except Exception:
                sizes[str(img.name)] = {"w": 1000, "h": 1500}
        with open(sizes_file, "w", encoding="utf-8") as f:
            json.dump(sizes, f)
    
    mode = detect_mode(images)
    image_cache = ImageCache(max_size=50)
    loader = ImageLoaderThread(image_cache, images, screen_width, screen_height, 1.0, mode)
    webtoon_renderer = WebtoonRenderer(images, screen_width, screen_height, image_cache, sizes)
    manga_renderer = MangaRenderer(images, screen_width, screen_height, image_cache)
    
    manga_name, chapter_number = parse_manga_and_chapter(archive_path)
    progress_mgr = ProgressManager()
    start_page = max(start_page, progress_mgr.load(manga_name, chapter_number))
    
    if mode == 'manga':
        manga_renderer.go_to_page(start_page - 1)
        current_page = start_page
    else:
        webtoon_renderer.calculate_layout(1.0)
        scroll_offset = webtoon_renderer.image_positions[start_page-1] if start_page - 1 < len(webtoon_renderer.image_positions) else 0
        current_page = start_page
    
    font = pygame.font.SysFont('arial', 18, bold=True)
    mode_button = ModernButton(screen_width - 250, 10, 120, 30, mode.capitalize(), font, colors)
    play_button = ModernButton(screen_width - 120, 10, 100, 30, "Play", font, colors)
    speed_slider = Slider(screen_width - 140, 50, 100, 10, 150, 1200, 300, colors)
    progress_bar = ModernProgressBar(screen_width - 220, screen_height - 50, 200, 25, colors)
    thumbnail_viewer = ThumbnailViewer(10, 10, 120, screen_height - 20, images, image_cache, screen_width, screen_height, colors, cache_dir)
    
    running = True
    is_scrolling = False
    clock = pygame.time.Clock()
    last_scroll_time = time.time()
    
    def update_layout():
        nonlocal screen_width, screen_height
        screen_width, screen_height = screen.get_size()
        mode_button.rect.topleft = (screen_width - 250, 10)
        play_button.rect.topleft = (screen_width - 120, 10)
        speed_slider.rect.topleft = (screen_width - 140, 50)
        progress_bar.rect.topright = (screen_width - 20, screen_height - 50)
        thumbnail_viewer.rect = pygame.Rect(10, 10, 120, screen_height - 20)
        thumbnail_viewer.calculate_layout()
        webtoon_renderer.calculate_layout(webtoon_renderer.zoom)
        manga_renderer.screen_width = screen_width
        manga_renderer.screen_height = screen_height
        image_cache.clear()

    while running:
        delta_time = time.time() - last_scroll_time
        last_scroll_time = time.time()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_q):
                running = False
            elif event.type == pygame.VIDEORESIZE:
                update_layout()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_TAB:
                    thumbnail_viewer.visible = not thumbnail_viewer.visible
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
                    if event.key in [pygame.K_PAGEDOWN, pygame.K_DOWN]: manga_renderer.next_page()
                    elif event.key in [pygame.K_PAGEUP, pygame.K_UP]: manga_renderer.prev_page()
                    elif event.key == pygame.K_HOME: manga_renderer.go_to_page(0)
                    elif event.key == pygame.K_END: manga_renderer.go_to_page(len(images)-1)
            elif event.type == pygame.MOUSEWHEEL:
                if mode == 'webtoon':
                    scroll_offset = max(0, min(scroll_offset - event.y * 100, webtoon_renderer.total_height - screen_height))
                elif mode == 'manga':
                    if event.y > 0: manga_renderer.prev_page()
                    elif event.y < 0: manga_renderer.next_page()
                thumbnail_result = thumbnail_viewer.handle_event(event)
                if thumbnail_result == "consumed":
                    continue
                elif thumbnail_result:
                    if mode == 'webtoon':
                        scroll_offset = webtoon_renderer.image_positions[thumbnail_result - 1]
                        current_page = thumbnail_result
                    else:
                        manga_renderer.go_to_page(thumbnail_result - 1)
                        current_page = thumbnail_result
            if mode_button.handle_event(event):
                mode = 'manga' if mode == 'webtoon' else 'webtoon'
                mode_button.text = mode.capitalize()
                update_layout()
            elif play_button.handle_event(event) and mode == 'webtoon':
                is_scrolling = not is_scrolling
                play_button.text = "Stop" if is_scrolling else "Play"
            speed_slider.handle_event(event)
        
        keys = pygame.key.get_pressed()
        if mode == 'manga':
            manga_renderer.update_transition()
        elif mode == 'webtoon' and not thumbnail_viewer.visible:
            scroll_speed = int(100 * (webtoon_renderer.zoom ** 0.8))
            if keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_SPACE]:
                scroll_offset = min(scroll_offset + scroll_speed, max(0, webtoon_renderer.total_height - screen_height))
            elif keys[pygame.K_UP] or keys[pygame.K_w]:
                scroll_offset = max(0, scroll_offset - scroll_speed)
            if is_scrolling:
                scroll_offset = min(scroll_offset + speed_slider.value * delta_time, max(0, webtoon_renderer.total_height - screen_height))
        
        screen.fill(colors["background"])
        if mode == 'webtoon':
            vis = webtoon_renderer.render(screen, scroll_offset)
            loader.preload(vis)
            current_page = webtoon_renderer.page_from_offset(scroll_offset)
            total_pages = len(images)
            progress = min(1.0, scroll_offset / max(1, webtoon_renderer.total_height - screen_height)) if webtoon_renderer.total_height > screen_height else 1.0
        else:
            vis = manga_renderer.render(screen)
            current_page = manga_renderer.current_page + 1
            total_pages = len(images)
            progress = manga_renderer.current_page / max(1, len(images)-1) if len(images) > 1 else 1.0
        
        if thumbnail_viewer.visible:
            thumbnail_viewer.scroll_to_current_page(current_page)
        progress_mgr.save(manga_name, chapter_number, current_page, total_pages)
        
        screen.blit(font.render(f"{Path(archive_path).stem}", True, colors["foreground"]), (10, 10))
        mode_button.draw(screen)
        if mode == 'webtoon':
            play_button.draw(screen)
            speed_slider.draw(screen)
        progress_bar.draw(screen, progress, current_page, total_pages)
        thumbnail_viewer.draw(screen, current_page)
        
        pygame.display.flip()
        clock.tick(60)
    
    progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
    loader.stop()
    cleanup(cache_dir)

def main(archive_path=None, start_page=1):
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(description="Manga/Webtoon Reader")
    parser.add_argument("archive_path", nargs='?', default=None, help="Path to the manga archive file")
    parser.add_argument("--page", type=int, default=0, help="Starting page number")
    args = parser.parse_args()
    db_path = Path.home() / ".config" / "manga_reader" / "library.db"
    progress_path = Path.home() / ".config" / "manga_reader" / "progress.json"
    migrate_progress_json(db_path, progress_path)
    run_reader(args.archive_path, args.page)

if __name__ == "__main__":
    main()