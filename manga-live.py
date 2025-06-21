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
import random
import math
import queue
import io
import subprocess
import shutil
import sqlite3
from pathlib import Path
import logging
import tkinter as tk
from tkinter import filedialog

# Config logger
logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] %(message)s')

# Préparer Pygame avant import
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
        "thumbnail_bg": (20, 20, 20, 200)
    }
    wal_path = Path.home() / ".cache" / "wal" / "wal.json"
    if not wal_path.exists():
        logging.warning("wal.json non trouvé, utilisation des couleurs par défaut")
        return default_colors

    try:
        with open(wal_path, "r", encoding='utf-8') as f:
            wal_data = json.load(f)
        # Conversion des couleurs hex en tuples RGB
        def hex_to_rgb(hex_str):
            hex_str = hex_str.lstrip('#')
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

        # Vérifier et extraire les couleurs, utiliser des valeurs par défaut si absentes
        colors = {}
        special = wal_data.get("special", {})
        colors["background"] = hex_to_rgb(special.get("background", "#222224"))
        colors["foreground"] = hex_to_rgb(special.get("foreground", "#E4C1B7"))
        
        wal_colors = wal_data.get("colors", {})
        colors["button_bg"] = hex_to_rgb(wal_colors.get("color0", "#48484A"))
        colors["button_hover"] = hex_to_rgb(wal_colors.get("color8", "#926F64"))
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

        logging.info(f"Couleurs chargées avec succès : {colors}")
        return colors
    except Exception as e:
        logging.error(f"Erreur lors du chargement de wal.json: {e}. Utilisation des couleurs par défaut.")
        return default_colors
        
def show_file_dialogue(initial_dir=None):
    """Affiche une fenêtre Pygame personnalisée pour sélectionner un fichier d'archive."""
    pygame.init()
    sw, sh = 720, 480
    colors = load_wal_colors()
    bg_color = colors["background"]
    fg_color = colors["foreground"]
    manga_color = colors["slider_handle"]
    chalk_color = colors["highlight_color"] if "highlight_color" in colors else colors["button_hover"]
    
    dialog_surface = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
    pygame.display.set_caption("Manga Live - Sélectionner un fichier")
    
    # Répertoire courant
    if initial_dir is None:
        initial_dir = Path.home()
    else:
        initial_dir = Path(initial_dir).expanduser().absolute()
    current_dir = initial_dir
    
    # Extensions supportées
    supported_extensions = {".cbz", ".cbr", ".zip", ".rar", ".pdf"}
    
    # Variables d'animation
    start_time = time.time()
    logo_alpha = 0
    logo_scale = 0.3
    particles = []
    file_list_alpha = 0
    
    # OPTIMISATION: Pré-créer le masque pour les coins arrondis
    radius = 10
    rounded_mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
    pygame.draw.rect(rounded_mask, (0, 0, 0, 0), (0, 0, sw, sh))
    pygame.draw.rect(rounded_mask, fg_color, (0, 0, sw, sh), border_radius=radius)
    
    # OPTIMISATION: Initialiser les particules avec surfaces pré-créées
    for i in range(10):
        particle = {
            'x': random.randint(0, sw),
            'y': random.randint(0, sh),
            'size': random.uniform(1, 3),
            'alpha': 0,
            'target_alpha': random.randint(30, 60),
            'speed': random.uniform(0.1, 0.3),
            'phase': random.uniform(0, 2 * math.pi),
            'surface': None  # Sera créée une seule fois
        }
        # Pré-créer la surface de la particule
        particle_size = int(particle['size'] * 6)
        particle['surface'] = pygame.Surface((particle_size, particle_size), pygame.SRCALPHA)
        particles.append(particle)
    
    # Widgets UI
    font = pygame.font.SysFont("arial", 18, bold=True)
    title_font = pygame.font.SysFont("comicsansms", 36, bold=True)
    buttons = []
    button_indices = []
    scroll_offset = 0
    selected_index = -1
    file_entries = []
    
    # OPTIMISATION: Variables de cache pour éviter les recalculs
    buttons_cache_valid = False
    last_scroll_offset = -1
    last_selected_index = -1
    particles_need_update = True
    
    # OPTIMISATION: Pré-calculer les textes du titre avec différentes tailles
    title_surfaces = {}
    for size in range(32, 40):  # Gamme de tailles possibles
        scaled_font = pygame.font.SysFont("comicsansms", size, bold=True)
        title_surfaces[size] = scaled_font.render("Sélectionner un fichier", True, manga_color)
    
    def update_file_list():
        nonlocal file_entries, buttons_cache_valid
        file_entries = []
        # Ajouter le dossier parent
        if current_dir != current_dir.parent:
            file_entries.append(("..", current_dir.parent, True))
        # Lister les dossiers et fichiers
        try:
            for item in sorted(current_dir.iterdir()):
                if item.name.startswith('.'):
                    continue  # Ignore les fichiers/dossiers cachés
                if item.is_dir():
                    file_entries.append((item.name, item, True))
                elif item.is_file() and item.suffix.lower() in supported_extensions:
                    file_entries.append((item.name, item, False))
        except PermissionError:
            logging.warning(f"Permission refusée pour accéder à {current_dir}")
        # Invalider le cache des boutons
        buttons_cache_valid = False
    
    def update_buttons_if_needed():
        nonlocal buttons, button_indices, buttons_cache_valid, last_scroll_offset
        # OPTIMISATION: Ne recréer les boutons que si nécessaire
        if not buttons_cache_valid or scroll_offset != last_scroll_offset:
            buttons = []
            button_indices = []
            for i, (name, path, is_dir) in enumerate(file_entries):
                y = 80 + i * 40 - scroll_offset
                if 80 <= y <= sh - 40:
                    buttons.append(ModernButton(20, y, sw - 40, 30, name, font, colors))
                    button_indices.append(i)
            buttons_cache_valid = True
            last_scroll_offset = scroll_offset
    
    def update_particles():
        nonlocal particles_need_update
        # OPTIMISATION: Ne recalculer les particules que si nécessaire
        if particles_need_update:
            for particle in particles:
                if particle['alpha'] > 0:
                    # Vider et redessiner la surface de la particule
                    particle['surface'].fill((0, 0, 0, 0))
                    center = particle['size'] * 3
                    for r in range(int(particle['size'] * 3), 0, -1):
                        alpha = min(255, particle['alpha'] // (r + 1))
                        color = (*manga_color, alpha)
                        pygame.draw.circle(particle['surface'], color, (center, center), r)
            particles_need_update = False

    update_file_list()
    
    # OPTIMISATION: Pré-calculer le texte du chemin pour éviter les recalculs
    current_path_text = None
    last_current_dir = None
    
    # Boucle principale
    running = True
    clock = pygame.time.Clock()
    while running:
        elapsed = time.time() - start_time
        
        # Animation du logo
        if elapsed < 0.6:
            anim_progress = elapsed / 0.6
            logo_alpha = int(255 * min(1.0, anim_progress * 1.5))
            logo_scale = 0.3 + 0.7 * easeOutBounce(anim_progress)
        else:
            logo_alpha = 255
            logo_scale = 1.0
        
        # Animation de la liste
        if elapsed > 0.4:
            file_list_alpha = int(255 * min(1.0, (elapsed - 0.4) / 0.6))
        
        # Animation des particules
        particles_changed = False
        for particle in particles:
            if elapsed > 0.2:
                old_alpha = particle['alpha']
                particle['alpha'] = min(particle['target_alpha'], particle['alpha'] + 1.5)
                particle['phase'] += particle['speed']
                if old_alpha != particle['alpha']:
                    particles_changed = True
        
        if particles_changed:
            particles_need_update = True
        
        # OPTIMISATION: Mettre à jour les boutons seulement si nécessaire
        update_buttons_if_needed()

        # Gestion des événements
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                return None
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    return None
                elif event.key == pygame.K_RETURN and selected_index >= 0:
                    name, path, is_dir = file_entries[selected_index]
                    if is_dir:
                        current_dir = path
                        scroll_offset = 0
                        selected_index = -1
                        update_file_list()
                    else:
                        return path
                elif event.key == pygame.K_UP:
                    selected_index = max(-1, selected_index - 1)
                    if selected_index >= 0:
                        button_y = 80 + selected_index * 40 - scroll_offset
                        if button_y < 80:
                            scroll_offset = max(0, scroll_offset - 40)
                            buttons_cache_valid = False
                elif event.key == pygame.K_DOWN:
                    selected_index = min(len(file_entries) - 1, selected_index + 1)
                    if selected_index >= 0:
                        button_y = 80 + selected_index * 40 - scroll_offset
                        if button_y > sh - 80:
                            scroll_offset = min((len(file_entries) * 40 - (sh - 120)), scroll_offset + 40)
                            buttons_cache_valid = False
                elif event.key == pygame.K_PAGEUP:
                    old_scroll = scroll_offset
                    scroll_offset = max(0, scroll_offset - (sh - 120))  # Scroll d'une page vers le haut
                    if old_scroll != scroll_offset:
                        buttons_cache_valid = False
                elif event.key == pygame.K_PAGEDOWN:
                    old_scroll = scroll_offset
                    scroll_offset = min(max(0, len(file_entries) * 40 - (sh - 120)), scroll_offset + (sh - 120))  # Scroll d'une page vers le bas
                    if old_scroll != scroll_offset:
                        buttons_cache_valid = False
                elif pygame.K_a <= event.key <= pygame.K_z:
                    char = chr(event.key).lower()
                    for i, (name, _, _) in enumerate(file_entries):
                        if name.lower().startswith(char):
                            selected_index = i
                            # Scroll vers l'entrée trouvée
                            if i * 40 < scroll_offset:
                                scroll_offset = max(0, i * 40)
                                buttons_cache_valid = False
                            elif i * 40 > scroll_offset + (sh - 120 - 40):
                                scroll_offset = min((len(file_entries) * 40 - (sh - 120)), i * 40)
                                buttons_cache_valid = False
                            break
            elif event.type == pygame.MOUSEWHEEL:
                old_scroll = scroll_offset
                # Calculer le scroll maximum
                max_scroll = max(0, len(file_entries) * 40 - (sh - 120))
                # Appliquer le scroll avec event.y (positif = scroll up, négatif = scroll down)
                scroll_offset = max(0, min(scroll_offset - event.y * 40, max_scroll))
                if old_scroll != scroll_offset:
                    buttons_cache_valid = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Clic gauche seulement
                    for i, button in enumerate(buttons):
                        if button.handle_event(event):
                            real_index = button_indices[i]
                            selected_index = real_index
                            name, path, is_dir = file_entries[real_index]
                            if is_dir:
                                current_dir = path
                                scroll_offset = 0
                                selected_index = -1
                                update_file_list()
                            else:
                                return path
        
        # Rendu
        dialog_surface.fill(bg_color)
        
        # OPTIMISATION: Utiliser le masque pré-créé
        dialog_surface.blit(rounded_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        
        # OPTIMISATION: Mettre à jour et dessiner les particules
        update_particles()
        for particle in particles:
            if particle['alpha'] > 0:
                x = particle['x'] + math.sin(particle['phase']) * 4
                y = particle['y'] + math.cos(particle['phase'] * 0.8) * 3
                dialog_surface.blit(particle['surface'], (x - particle['size'] * 3, y - particle['size'] * 3))
        
        # OPTIMISATION: Titre avec surface pré-calculée
        if logo_alpha > 0:
            font_size = max(32, min(39, int(36 * logo_scale)))
            if font_size in title_surfaces:
                title_text = title_surfaces[font_size].copy()
                title_text.set_alpha(logo_alpha)
                title_rect = title_text.get_rect(center=(sw // 2, 30))
                dialog_surface.blit(title_text, title_rect)
        
        # OPTIMISATION: Afficher le chemin courant (mise en cache)
        if current_dir != last_current_dir:
            current_path_text = font.render(str(current_dir), True, chalk_color)
            last_current_dir = current_dir
        
        if current_path_text:
            path_text_copy = current_path_text.copy()
            path_text_copy.set_alpha(file_list_alpha)
            path_rect = path_text_copy.get_rect(topleft=(20, 60))
            dialog_surface.blit(path_text_copy, path_rect)
        
        # OPTIMISATION: Afficher les boutons (mise à jour seulement si sélection change)
        if selected_index != last_selected_index:
            for i, button in enumerate(buttons):
                button.is_hovered = (button_indices[i] == selected_index)
            last_selected_index = selected_index
        
        for button in buttons:
            button.draw(dialog_surface)
        
        # Dessiner une barre de défilement si nécessaire
        visible_count = (sh - 120) // 40  # nombre d'éléments visibles
        total_count = len(file_entries)
        if total_count > visible_count:
            scrollbar_height = int((visible_count / total_count) * (sh - 120))
            scrollbar_pos = int((scroll_offset / (total_count * 40 - (sh - 120))) * (sh - 120))
            scrollbar_rect = pygame.Rect(sw - 10, 80 + scrollbar_pos, 6, scrollbar_height)
            pygame.draw.rect(dialog_surface, chalk_color, scrollbar_rect, border_radius=3)

        pygame.display.flip()
        clock.tick(60)
    
    return None

def cleanup(cache_dir=None):
    if cache_dir is not None:
        try:
            shutil.rmtree(cache_dir)
            print(f"[INFO] Cache supprimé : {cache_dir}")
        except Exception as e:
            print(f"[WARNING] Impossible de supprimer le cache : {e}")
    pygame.display.quit()
    pygame.quit()
    gc.collect()
    sys.exit(0)

def show_splash(image_path=None, wait_time=1.2, bg_color=("button_bg"), logo_txt="Manga Live", do_radius=True, preload_func=None):
    pygame.init()
    sw, sh = 640, 400
    colors = load_wal_colors()
    bg_color = colors["background"]
    fg_color = colors["foreground"]
    manga_color = colors["slider_handle"]
    chalk_color = colors["button_hover"]
    
    splash = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
    pygame.display.set_caption("Manga Live - Chargement...")
    
    # Variables d'animation
    splash_start = time.time()
    logo_alpha = 0
    logo_scale = 0.3
    text_alpha = 0
    progress = 0.0
    particles = []
    
    # Initialiser les particules
    for i in range(3):
        particles.append({
            'x': sw // 2 + ((-1) ** i) * (60 + i * 20),
            'y': sh // 2 + ((-1) ** (i // 2)) * (30 + i * 12),
            'size': 1 + (i % 3),
            'alpha': 0,
            'target_alpha': 40 + (i * 6),
            'speed': 0.2 + (i * 0.08),
            'phase': i * 0.5
        })
    
    # Preload asynchrone avec progression
    preload_done = threading.Event()
    preload_progress = {'value': 0.0}
    
    def preload_wrapper():
        if preload_func:
            # Simuler progression pendant le preload
            steps = 15
            for step in range(steps):
                preload_progress['value'] = step / steps
                time.sleep(0.05)
            preload_func()
        preload_progress['value'] = 1.0
        preload_done.set()
    
    if preload_func:
        th = threading.Thread(target=preload_wrapper)
        th.daemon = True
        th.start()
    else:
        preload_done.set()
        preload_progress['value'] = 1.0
    
    # Boucle d'animation principale
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
        
        now = time.time()
        elapsed = now - splash_start
        
        # === CALCUL DES ANIMATIONS ===
        # Logo apparition (0-0.6s)
        if elapsed < 0.6:
            anim_progress = elapsed / 0.6
            logo_alpha = int(255 * min(1.0, anim_progress * 1.5))
            logo_scale = 0.3 + 0.7 * easeOutBounce(anim_progress)
        else:
            logo_alpha = 255
            logo_scale = 1.0
        
        # Texte de chargement apparition (0.4-1.0s)
        if elapsed > 0.4:
            text_progress = min(1.0, (elapsed - 0.4) / 0.6)
            text_alpha = int(255 * text_progress)
        
        # Progression globale
        progress = min(1.0, preload_progress['value'])
        
        # Particules animation
        for particle in particles:
            if elapsed > 0.2:
                particle['alpha'] = min(particle['target_alpha'], particle['alpha'] + 1.5)
                particle['phase'] += particle['speed']
        
        # === RENDU ===
        splash.fill(bg_color)
        
        # Coins arrondis
        if do_radius:
            radius = 5
            mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
            pygame.draw.rect(mask, (0,0,0,0), (0,0,sw,sh))
            pygame.draw.rect(mask, fg_color, (0,0,sw,sh), border_radius=radius)
            splash.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MIN)
        
        # Image de fond avec parallax subtil
        bg_surf = None
        if image_path and Path(image_path).exists():
            try:
                with Image.open(image_path) as im:
                    im = im.convert("RGB")
                    im = im.filter(ImageFilter.GaussianBlur(6))
                    im.thumbnail((sw + 20, sh + 20))
                    arr = pygame.image.fromstring(im.tobytes(), im.size, "RGB")
                    bg_surf = pygame.transform.scale(arr, (sw + 20, sh + 20))
            except Exception:
                pass
        
        if bg_surf:
            # Effet parallax léger
            offset_x = int(math.sin(elapsed * 0.3) * 3)
            offset_y = int(math.cos(elapsed * 0.2) * 2)
            splash.blit(bg_surf, (-10 + offset_x, -10 + offset_y))
            
            # Overlay sombre animé
            overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
            overlay_alpha = int(120 + 20 * math.sin(elapsed * 0.5))
            overlay.fill((0, 0, 0, overlay_alpha))
            splash.blit(overlay, (0, 0))
        
        # Particules flottantes
        for particle in particles:
            if particle['alpha'] > 0:
                x = particle['x'] + math.sin(particle['phase']) * 4
                y = particle['y'] + math.cos(particle['phase'] * 0.8) * 3
                
                # Créer une surface pour la particule avec glow
                particle_surf = pygame.Surface((particle['size'] * 6, particle['size'] * 6), pygame.SRCALPHA)
                
                # Effet glow
                for r in range(particle['size'] * 3, 0, -1):
                    alpha = particle['alpha'] // (r + 1)
                    color = (*manga_color, alpha)
                    pygame.draw.circle(particle_surf, color, 
                                     (particle['size'] * 3, particle['size'] * 3), r)
                
                splash.blit(particle_surf, (x - particle['size'] * 3, y - particle['size'] * 3))
        
        # Logo avec effet de bounce et glow
        if logo_alpha > 0:
            font_size = int(54 * logo_scale)
            font = pygame.font.SysFont("comicsansms", font_size, bold=True)
            
            # Effet glow sur le logo
            glow_layers = 5
            for layer in range(glow_layers, 0, -1):
                glow_alpha = (logo_alpha // glow_layers) // layer
                glow_size = font_size + layer * 2
                glow_font = pygame.font.SysFont("comicsansms", glow_size, bold=True)
                glow_text = glow_font.render(logo_txt, True, manga_color)
                glow_text.set_alpha(glow_alpha)
                glow_rect = glow_text.get_rect(center=(sw // 2, sh // 2 - 40))
                splash.blit(glow_text, glow_rect)
            
            # Texte principal du logo
            main_text = font.render(logo_txt, True, fg_color)
            main_text.set_alpha(logo_alpha)
            
            # Petit effet de tremblement sur le logo
            shake_x = int(math.sin(elapsed * 8) * (1 - logo_scale) * 2)
            shake_y = int(math.cos(elapsed * 12) * (1 - logo_scale) * 1)
            
            main_rect = main_text.get_rect(center=(sw // 2 + shake_x, sh // 2 - 40 + shake_y))
            splash.blit(main_text, main_rect)
        
        # Ligne décorative animée
        if logo_alpha > 100:
            line_width = int(120 * (logo_alpha / 255))
            line_y = sh // 2 - 5
            
            # Ligne avec gradient
            for i in range(line_width):
                ratio = abs(i - line_width // 2) / (line_width // 2)
                alpha = int(255 * (1 - ratio) * (logo_alpha / 255))
                color = (*manga_color, alpha)
                
                line_surf = pygame.Surface((2, 3), pygame.SRCALPHA)
                line_surf.fill(color)
                splash.blit(line_surf, (sw // 2 - line_width // 2 + i, line_y))
        
        # Texte de chargement avec pulsation
        if text_alpha > 0:
            pulse = 0.8 + 0.2 * math.sin(elapsed * 3)
            font2_size = int(28 * pulse)
            font2 = pygame.font.SysFont("arial", font2_size, bold=False)
            
            loading_text = "Chargement du Webtoon"
            # Animation des points
            dots = "." * (int(elapsed * 2) % 4)
            full_text = loading_text + dots
            
            t2 = font2.render(full_text, True, chalk_color)
            t2.set_alpha(text_alpha)
            r2 = t2.get_rect(center=(sw // 2, sh // 2 + 45))
            splash.blit(t2, r2)
        
        # Barre de progression stylée
        if text_alpha > 50 and progress > 0:
            progress_width = 200
            progress_height = 6
            progress_x = sw // 2 - progress_width // 2
            progress_y = sh // 2 + 85
            
            # Fond de la barre avec glow
            bg_glow = pygame.Surface((progress_width + 10, progress_height + 6), pygame.SRCALPHA)
            pygame.draw.rect(bg_glow, (*chalk_color, 30), (0, 0, progress_width + 10, progress_height + 6), border_radius=4)
            splash.blit(bg_glow, (progress_x - 5, progress_y - 3))
            
            # Fond de la barre
            pygame.draw.rect(splash, (40, 40, 50), (progress_x, progress_y, progress_width, progress_height), border_radius=3)
            
            # Barre de progression avec animation fluide
            current_width = int(progress_width * progress)
            if current_width > 0:
                # Gradient sur la barre
                for i in range(current_width):
                    ratio = i / progress_width
                    r = int(manga_color[0] * (1 + ratio * 0.3))
                    g = int(manga_color[1] * (1 + ratio * 0.2))
                    b = int(manga_color[2] * (1 + ratio * 0.4))
                    color = (min(255, r), min(255, g), min(255, b))
                    
                    pygame.draw.line(splash, color, 
                                   (progress_x + i, progress_y + 1), 
                                   (progress_x + i, progress_y + progress_height - 1))
                
                # Effet de lueur qui se déplace
                glow_pos = current_width - 15
                if glow_pos > 0:
                    glow_surf = pygame.Surface((30, progress_height + 4), pygame.SRCALPHA)
                    for x in range(30):
                        alpha = int(100 * math.exp(-(x - 15) ** 2 / 50))
                        glow_color = (*manga_color, alpha)
                        pygame.draw.line(glow_surf, glow_color, (x, 0), (x, progress_height + 4))
                    
                    splash.blit(glow_surf, (progress_x + glow_pos - 15, progress_y - 2))
            
            # Pourcentage avec effet typewriter
            percent = int(progress * 100)
            percent_text = f"{percent}%"
            percent_font = pygame.font.SysFont("arial", 16, bold=True)
            percent_surf = percent_font.render(percent_text, True, chalk_color)
            percent_surf.set_alpha(text_alpha)
            percent_rect = percent_surf.get_rect(center=(sw // 2, progress_y + 20))
            splash.blit(percent_surf, percent_rect)
        
        pygame.display.flip()
        pygame.time.wait(30)

        if now - splash_start > wait_time and preload_done.is_set():
            break
        
        # Condition de sortie
        if elapsed > wait_time and preload_done.is_set():
            break
            
        pygame.time.wait(16)  # 60 FPS
    
    # Effet de fade out
    for alpha in range(255, 0, -15):
        fade_surf = pygame.Surface((sw, sh))
        fade_surf.fill((0, 0, 0))
        fade_surf.set_alpha(255 - alpha)
        splash.blit(fade_surf, (0, 0))
        pygame.display.flip()
        pygame.time.wait(20)

# Fonction d'easing pour animation bounce
def easeOutBounce(t):
    if t < (1 / 2.75):
        return 7.5625 * t * t
    elif t < (2 / 2.75):
        t -= (1.5 / 2.75)
        return 7.5625 * t * t + 0.75
    elif t < (2.5 / 2.75):
        t -= (2.25 / 2.75)
        return 7.5625 * t * t + 0.9375
    else:
        t -= (2.625 / 2.75)
        return 7.5625 * t * t + 0.984375


### Progression & Sauvegarde ###
class ProgressManager:
    def __init__(self):
        self.db_path = Path.home() / ".config" / "manga_reader" / "library.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_chapter_key(self, chapter_number):
        try:
            return f"{float(chapter_number):.1f}"
        except Exception:
            return str(chapter_number)

    def _connect_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            return conn
        except sqlite3.Error as e:
            logging.error(f"Erreur de connexion à la base de données : {e}")
            raise

    def save(self, manga_name, chapter_number, current_page, total_pages, force_save=False):
        chapter_key = self._get_chapter_key(chapter_number)
        is_completed = current_page >= total_pages
        try:
            with self._connect_db() as conn:
                cursor = conn.cursor()
                # Rechercher le manga_id
                cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
                manga_id = cursor.fetchone()
                if not manga_id:
                    logging.error(f"Manga {manga_name} non trouvé dans la base de données.")
                    return
                manga_id = manga_id[0]
                
                # Rechercher le chapitre
                cursor.execute(
                    "SELECT id FROM chapters WHERE manga_id = ? AND num = ?",
                    (manga_id, float(chapter_number))
                )
                chapter_id = cursor.fetchone()
                if not chapter_id:
                    logging.error(f"Chapitre {chapter_number} non trouvé pour le manga {manga_name}.")
                    return
                chapter_id = chapter_id[0]
                
                # Mettre à jour la progression
                cursor.execute(
                    "SELECT last_page_read FROM chapters WHERE id = ?",
                    (chapter_id,)
                )
                existing_page = cursor.fetchone()
                existing_page = existing_page[0] if existing_page and existing_page[0] is not None else 0
                
                if force_save or current_page > existing_page or is_completed:
                    cursor.execute(
                        "UPDATE chapters SET read = ?, last_page_read = ?, full_pages_read = ? WHERE id = ?",
                        (is_completed, current_page, total_pages, chapter_id)
                    )
                    conn.commit()
                    logging.debug(
                        f"Progression sauvegardée pour {manga_name} chapitre {chapter_number}: "
                        f"page={current_page}, total={total_pages}, read={is_completed}"
                    )
        except sqlite3.Error as e:
            logging.error(f"Impossible de sauvegarder la progression : {e}")

    def load(self, manga_name, chapter_number):
        chapter_key = self._get_chapter_key(chapter_number)
        try:
            with self._connect_db() as conn:
                cursor = conn.cursor()
                # Rechercher le manga_id
                cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
                manga_id = cursor.fetchone()
                if not manga_id:
                    logging.warning(f"Manga {manga_name} non trouvé dans la base de données.")
                    return 1
                manga_id = manga_id[0]
                
                # Rechercher la progression du chapitre
                cursor.execute(
                    "SELECT last_page_read FROM chapters WHERE manga_id = ? AND num = ?",
                    (manga_id, float(chapter_number))
                )
                result = cursor.fetchone()
                if result and result[0] is not None:
                    return max(1, result[0])
                return 1
        except sqlite3.Error as e:
            logging.error(f"Impossible de charger la progression : {e}")
            return 1

def migrate_progress_json(db_path, progress_path):
    if not progress_path.exists():
        print("Aucun fichier progress.json trouvé, migration ignorée.")
        return

    # Lire progress.json
    try:
        with open(progress_path, 'r', encoding='utf-8') as f:
            progress_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Erreur lors de la lecture de progress.json : {e}")
        return
    except IOError as e:
        print(f"Erreur d'accès au fichier progress.json : {e}")
        return

    # Connexion à la base de données
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        # Parcourir les données de progress.json
        for manga_name, chapters in progress_data.items():
            # Rechercher l'ID du manga
            cursor.execute("SELECT id FROM mangas WHERE name = ?", (manga_name,))
            manga_result = cursor.fetchone()
            if not manga_result:
                print(f"Manga '{manga_name}' non trouvé dans la base de données, ignoré.")
                continue
            manga_id = manga_result[0]

            # Parcourir les chapitres
            for chapter_num, data in chapters.items():
                try:
                    chapter_num_float = float(chapter_num)
                except ValueError:
                    print(f"Numéro de chapitre invalide '{chapter_num}' pour '{manga_name}', ignoré.")
                    continue

                read = data.get("read", False)
                last_page_read = data.get("last_page", 0)
                full_pages_read = data.get("total_pages", 0)

                # Rechercher le chapitre dans la base de données
                cursor.execute(
                    "SELECT id FROM chapters WHERE manga_id = ? AND num = ?",
                    (manga_id, chapter_num_float)
                )
                chapter_result = cursor.fetchone()
                if not chapter_result:
                    print(f"Chapitre {chapter_num} pour '{manga_name}' non trouvé dans la base de données, ignoré.")
                    continue
                chapter_id = chapter_result[0]

                # Mettre à jour la progression
                cursor.execute(
                    "UPDATE chapters SET read = ?, last_page_read = ?, full_pages_read = ? WHERE id = ?",
                    (read, last_page_read, full_pages_read, chapter_id)
                )
                print(f"Progression mise à jour pour '{manga_name}' chapitre {chapter_num}: "
                      f"read={read}, last_page_read={last_page_read}, full_pages_read={full_pages_read}")

        conn.commit()
        print("Migration des données de progression terminée.")
    except sqlite3.Error as e:
        print(f"Erreur lors de la migration vers la base de données : {e}")
        return
    finally:
        conn.close()

    # Renommer progress.json en progress.json.bak
    backup_path = progress_path.with_suffix(".json.bak")
    try:
        if progress_path.exists():
            progress_path.rename(backup_path)
            print(f"Fichier {progress_path} renommé en {backup_path}")
        else:
            print(f"Fichier {progress_path} n'existe plus, renommage ignoré.")
    except PermissionError as e:
        print(f"Erreur de permissions lors du renommage de {progress_path} : {e}")
        print("Vérifiez les droits d'accès au répertoire ~/.config/manga_reader/")
    except OSError as e:
        print(f"Erreur lors du renommage de {progress_path} en {backup_path} : {e}")
        print("Vérifiez si le fichier est utilisé par un autre processus ou si le disque est plein.")

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
    
    def clear_except_zoom(self, zoom, mode='webtoon', zoom_tolerance=0.2):
        with self.lock:
            new_cache = {}
            new_order = []
            for key in self.cache:
                parts = key.split('_')
                if len(parts) >= 3:
                    try:
                        cached_zoom = float(parts[-2])
                        cached_mode = parts[-1]
                        if cached_mode == mode and abs(cached_zoom - zoom) <= zoom_tolerance:
                            new_cache[key] = self.cache[key]
                            new_order.append(key)
                    except ValueError:
                        continue
            self.cache = new_cache
            self.order = new_order
            gc.collect()

class ImageLoaderThread:
    def __init__(self, cache, images, screen_width, screen_height, zoom):
        self.queue = queue.Queue()
        self.cache = cache
        self.images = images
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.zoom = zoom
        self.running = True
        self.mode = 'webtoon'
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while self.running:
            try:
                idx, key = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.cache.get(key) is None and 0 <= idx < len(self.images):
                img, size = load_image_to_pygame(self.images[idx], self.screen_width, self.screen_height, self.zoom, self.mode)
                if img:
                    self.cache.put(key, (img, size))
            time.sleep(0.005)

    def stop(self):
        self.running = False

    def preload(self, visible_indices):
        if not visible_indices or not self.images:
            return
        start, end = min(visible_indices), max(visible_indices)
        for i in range(max(0, start-5), min(len(self.images), end+5)):
            key = f"{self.images[i]}_{self.zoom:.2f}_webtoon"
            if self.cache.get(key) is None:
                self.queue.put((i, key))

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

    mask = pygame.Surface((fill_width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255,255,255,255), (0,0,fill_width,rect.height), border_radius=radius)
    bloc_surf.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MULT)

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

def safe_color(color):
    """Retourne un tuple RGB pour pygame.draw.*"""
    if isinstance(color, tuple):
        if len(color) == 4:
            return color[:3]
        return color
    return (0, 0, 0)

### UI widgets ###
class ModernButton:
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
        draw_rounded_rect(surface, self.bg_color, self.rect, radius=10)
        draw_rounded_rect(surface, self.handle_color, self.handle_rect, radius=5)
        font = pygame.font.SysFont('bold', 18, bold=True)
        text = font.render(f"Speed: {int(self.value)}", True, self.text_color)
        text_rect = text.get_rect(center=(self.rect.centerx, self.rect.y + self.rect.height + 15))
        surface.blit(text, text_rect)

class ThumbnailViewer:
    def __init__(self, x, y, width, height, images, cache, screen_width, screen_height, colors, cache_dir):
        self.rect = pygame.Rect(x, y + 35, width, height - 30)
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
        self.generate_thumbnails(lazy=True)
        self.calculate_layout()
        self.colors = colors if colors is not None else {}


    def generate_thumbnails(self, lazy=False):
        self.thumbnails = []
        for img_path in self.images:
            # Utiliser le nom du fichier au lieu du chemin complet
            img_name = Path(img_path).name
            thumb_key = f"thumb_{img_name}"  # Exemple : thumb_001.jpg
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
            if not lazy:
                try:
                    with Image.open(img_path) as img:
                        img = img.convert('RGB')
                        img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                        img.save(thumb_file, 'PNG')
                        thumb_surf = pygame.image.fromstring(img.tobytes(), img.size, 'RGB')
                        self.cache.put(thumb_key, (thumb_surf, img.size))
                    logging.info(f"Vignette générée pour {img_path}")
                except Exception as e:
                    logging.error(f"Erreur génération vignette {img_path}: {e}")
                    thumb_surf = pygame.Surface(self.thumbnail_size)
                    thumb_surf.fill((50, 50, 50))
                    self.cache.put(thumb_key, (thumb_surf, self.thumbnail_size))
                self.thumbnails.append(thumb_key)
            else:
                self.thumbnails.append(thumb_key)

    def calculate_layout(self):
        self.positions = []
        y = self.gap
        for _ in self.thumbnails:
            self.positions.append(y)
            y += self.thumbnail_size[1] + self.gap
        self.total_height = y

    def get_visible_indices(self):
        top = self.scroll_offset
        bottom = self.scroll_offset + self.rect.height
        visible = []
        for i, y in enumerate(self.positions):
            if y + self.thumbnail_size[1] >= top and y <= bottom:
                visible.append(i)
        return visible

    def handle_event(self, event):
        if not self.visible:
            return None
        mouse_pos = pygame.mouse.get_pos()
        if not self.rect.collidepoint(mouse_pos):
            return None
        if event.type == pygame.MOUSEWHEEL:
            scroll_speed = 50
            self.scroll_offset = max(0, min(self.scroll_offset - event.y * scroll_speed, max(0, self.total_height - self.rect.height)))
            return "consumed"
        elif event.type == pygame.MOUSEBUTTONDOWN:
            rel_y = event.pos[1] - self.rect.y + self.scroll_offset
            for i, y in enumerate(self.positions):
                if y <= rel_y < y + self.thumbnail_size[1]:
                    return i + 1
        return None

    def draw(self, surface, current_page):
        if not self.visible:
            return
        draw_rounded_rect(surface, self.bg_color, self.rect, radius=10, shadow=True)
        visible_indices = self.get_visible_indices()
        font = pygame.font.SysFont('bold', 18, bold=True)
        for i in visible_indices:
            thumb_key = self.thumbnails[i]
            cached = self.cache.get(thumb_key)
            if cached is None:
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
                if cached is None:
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
            thumb_surf, thumb_size = cached
            x = self.rect.x + (self.rect.width - thumb_size[0]) // 2
            y = self.rect.y + self.positions[i] - self.scroll_offset
            if y + thumb_size[1] >= self.rect.y and y <= self.rect.y + self.rect.height:
                surface.blit(thumb_surf, (x, y))
                if i + 1 == current_page:
                    pygame.draw.rect(surface, (255, 255, 0), (x, y, thumb_size[0], thumb_size[1]), 2)
                page_number = str(i + 1)
                text_surf = font.render(page_number, True, self.text_color)
                text_rect = text_surf.get_rect(centery=y + thumb_size[1] // 2, right=x - 5)
                surface.blit(text_surf, text_rect)
    
    def draw(self, surface, current_page):
        if not self.visible:
            return

        border_color = self.colors.get("colors_13", (179, 78, 48))
        draw_rounded_rect(surface, self.bg_color, self.rect, radius=16, width=0, shadow=True)
        pygame.draw.rect(surface, border_color, self.rect, width=3, border_radius=16)  # Bordure fine

        # Clipping pour masquer les miniatures qui dépassent
        old_clip = surface.get_clip()
        surface.set_clip(self.rect)
        
        visible_indices = self.get_visible_indices()
        font = pygame.font.SysFont('bold', 18, bold=True)
        for i in visible_indices:
            thumb_key = self.thumbnails[i]
            cached = self.cache.get(thumb_key)
            if cached is None:
                # --- GENERATION DYNAMIQUE ---
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
                # (fin fix)
            if cached is None:
                continue

            thumb_surf, thumb_size = cached
            x = self.rect.x + (self.rect.width - thumb_size[0]) // 2
            y = self.rect.y + self.positions[i] - self.scroll_offset
            if y + thumb_size[1] >= self.rect.y and y <= self.rect.y + self.rect.height:
                surface.blit(thumb_surf, (x, y))
                if i + 1 == current_page:
                    pygame.draw.rect(surface, (255, 255, 0), (x, y, thumb_size[0], thumb_size[1]), 2)
                page_number = str(i + 1)
                text_surf = font.render(page_number, True, self.text_color)
                text_rect = text_surf.get_rect(centery=y + thumb_size[1] // 2, right=x - 5)
                surface.blit(text_surf, text_rect)
        surface.set_clip(old_clip)  # Restaure le clipping !

    def scroll_to_current_page(self, current_page):
        if not self.thumbnails:
            return
        idx = current_page - 1
        if idx < 0 or idx >= len(self.positions):
            return
        thumb_y = self.positions[idx]
        thumb_center = thumb_y + self.thumbnail_size[1] // 2
        ideal_scroll = thumb_center - self.rect.height // 2

        # Limite pour ne pas dépasser les bornes du scroll
        ideal_scroll = max(0, min(ideal_scroll, max(0, self.total_height - self.rect.height)))
        self.scroll_offset = ideal_scroll

class FileSelector:
    def __init__(self, screen_width, screen_height, colors, initial_dir=None):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.colors = colors
        self.initial_dir = Path.home() if initial_dir is None else Path(initial_dir).expanduser().absolute()
        self.current_dir = self.initial_dir
        self.supported_extensions = {".cbz", ".cbr", ".zip", ".rar", ".pdf"}
        self.file_entries = []
        self.scroll_offset = 0
        self.selected_index = 0
        self.visible = False
        self.font = pygame.font.SysFont("arial", 18, bold=True)
        self.title_font = pygame.font.SysFont("comicsansms", 24, bold=True)
        self.item_height = 40
        
        # Dimensions de la fenêtre centrée
        self.width = min(screen_width - 200, 600)
        self.height = min(screen_height - 200, 400)
        self.rect = pygame.Rect(
            (screen_width - self.width) // 2,
            (screen_height - self.height) // 2,
            self.width,
            self.height
        )
        
        # Hauteur de l'en-tête (titre + chemin + marge)
        self.header_height = 30
        
        self.update_file_list()

    def update_file_list(self):
        """Met à jour la liste des fichiers et dossiers."""
        self.file_entries = []
        if self.current_dir != self.current_dir.parent:
            self.file_entries.append(("..", self.current_dir.parent, True))
        try:
            for item in sorted(self.current_dir.iterdir()):
                if item.name.startswith('.'):
                    continue
                if item.is_dir():
                    self.file_entries.append((item.name, item, True))
                elif item.is_file() and item.suffix.lower() in self.supported_extensions:
                    self.file_entries.append((item.name, item, False))
        except PermissionError:
            logging.warning(f"Permission refusée pour accéder à {self.current_dir}")
        self.calculate_layout()
        self.selected_index = 0
        self.scroll_offset = 0  # Réinitialiser le scroll

    def calculate_layout(self):
        """Calcule les positions des éléments pour le défilement."""
        
        # Recalculer dynamiquement la hauteur de l'en-tête (titre + chemin + marge)
        title_height = self.title_font.get_height()
        path_height = self.font.get_height()
        self.margin = 30
        self.header_height = title_height + path_height + self.margin

        self.positions = []
        y = self.header_height
        for _ in self.file_entries:
            self.positions.append(y)
            y += self.item_height

        self.total_height = len(self.file_entries) * self.item_height
        self.max_scroll = max(0, self.total_height - (self.rect.height - self.header_height))

    def get_visible_indices(self):
        """Retourne les indices des éléments visibles."""
        if not self.file_entries:
            return []
        
        visible_area_height = self.rect.height - self.header_height
        visible_indices = []
        
        for i in range(len(self.file_entries)):
            item_bottom = (i + 1) * self.item_height
            # L'élément est visible s'il intersecte avec la zone visible
            if (i * self.item_height < self.scroll_offset + visible_area_height and 
                item_bottom > self.scroll_offset):
                visible_indices.append(i)
        
        return visible_indices

    def handle_event(self, event):
        """Gère les événements (souris, clavier, défilement)."""
        if not self.visible:
            return None

        if event.type == pygame.MOUSEWHEEL:
            scroll_speed = 40
            old_scroll = self.scroll_offset
            self.scroll_offset = max(0, min(self.scroll_offset - event.y * scroll_speed, self.max_scroll))
            return "consumed"
            
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.rect.collidepoint(event.pos):  # Clic gauche
                # Vérifier si le clic est dans la zone de contenu
                content_rect = pygame.Rect(self.rect.x, self.rect.y + self.header_height, 
                                         self.rect.width, self.rect.height - self.header_height)
                if content_rect.collidepoint(event.pos):
                    rel_y = event.pos[1] - (self.rect.y + self.header_height) + self.scroll_offset
                    clicked_index = -1
                    
                    # Trouver l'élément cliqué en utilisant les positions
                    for i in range(len(self.file_entries)):
                        if i * self.item_height <= rel_y < (i + 1) * self.item_height:
                            clicked_index = i
                            break
                    
                    if 0 <= clicked_index < len(self.file_entries):
                        self.selected_index = clicked_index
                        name, path, is_dir = self.file_entries[clicked_index]
                        if is_dir:
                            self.current_dir = path
                            self.update_file_list()
                        else:
                            return path
                return "consumed"
            elif not self.rect.collidepoint(event.pos):  # Clic en dehors
                self.visible = False
                return "consumed"
                
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.visible = False
                return "consumed"
                
            elif event.key == pygame.K_RETURN:
                if 0 <= self.selected_index < len(self.file_entries):
                    name, path, is_dir = self.file_entries[self.selected_index]
                    if is_dir:
                        self.current_dir = path
                        self.update_file_list()
                    else:
                        return path
                return "consumed"
                
            elif event.key == pygame.K_UP:
                if self.file_entries:
                    self.selected_index = max(0, self.selected_index - 1)
                    self.ensure_visible()
                return "consumed"
                
            elif event.key == pygame.K_DOWN:
                if self.file_entries:
                    self.selected_index = min(len(self.file_entries) - 1, self.selected_index + 1)
                    self.ensure_visible()
                return "consumed"
                
            elif event.key == pygame.K_PAGEUP:
                visible_count = (self.rect.height - self.header_height) // self.item_height
                self.scroll_offset = max(0, self.scroll_offset - visible_count * self.item_height)
                return "consumed"
                
            elif event.key == pygame.K_PAGEDOWN:
                visible_count = (self.rect.height - self.header_height) // self.item_height
                self.scroll_offset = min(self.max_scroll, self.scroll_offset + visible_count * self.item_height)
                return "consumed"
                
            elif pygame.K_a <= event.key <= pygame.K_z:
                char = chr(event.key).lower()
                # Chercher le fichier/dossier commençant par cette lettre
                found = False
                for i, (name, _, _) in enumerate(self.file_entries):
                    if name.lower().startswith(char):
                        self.selected_index = i
                        self.ensure_visible()
                        found = True
                        break
                
                return "consumed"  # Toujours consommer les touches de lettres
            
            # Bloquer toutes les autres touches pour éviter les reloads
            return "consumed"
                
        return None

    def ensure_visible(self):
        """S'assure que l'élément sélectionné est visible dans la zone scrollable."""
        if not self.file_entries:
            return

        item_top = self.item_height * self.selected_index
        item_bottom = item_top + self.item_height
        visible_top = self.scroll_offset
        visible_bottom = self.scroll_offset + (self.rect.height - self.header_height)

        if item_top < visible_top:
            self.scroll_offset = item_top
        elif item_bottom > visible_bottom:
            self.scroll_offset = item_bottom - (self.rect.height - self.header_height)

        self.scroll_offset = max(0, min(self.scroll_offset, self.max_scroll))

    def draw(self, surface):
        """Dessine la fenêtre de sélection de fichiers."""
        if not self.visible:
            return

        # Fond avec ombre
        draw_rounded_rect(surface, self.colors["thumbnail_bg"], self.rect, radius=16, shadow=True)
        pygame.draw.rect(surface, self.colors["colors_13"], self.rect, width=3, border_radius=16)

        # Titre
        title_text = self.title_font.render("Sélectionner un fichier", True, self.colors["foreground"])
        title_rect = title_text.get_rect(center=(self.rect.centerx, self.rect.y + 25))
        surface.blit(title_text, title_rect)

        # Chemin courant (tronqué si trop long)
        path_str = str(self.current_dir)
        if len(path_str) > 50:  # Limiter la longueur affichée
            path_str = "..." + path_str[-47:]
        path_text = self.font.render(path_str, True, self.colors["button_hover"])
        path_rect = path_text.get_rect(topleft=(self.rect.x + 10, self.rect.y + 60))
        surface.blit(path_text, path_rect)

        # Zone de contenu avec clipping
        content_rect = pygame.Rect(self.rect.x, self.rect.y + self.header_height, 
                                 self.rect.width, self.rect.height - self.header_height)
        old_clip = surface.get_clip()
        surface.set_clip(content_rect)

        # Dessiner les éléments visibles
        visible_indices = self.get_visible_indices()
        for i in visible_indices:
            if i >= len(self.file_entries):
                continue
                
            name, _, is_dir = self.file_entries[i]
            
            # Position de l'élément
            item_y = self.rect.y + self.header_height + (i * self.item_height) - self.scroll_offset
            button_rect = pygame.Rect(self.rect.x + 10, item_y, self.rect.width - 20, self.item_height - 5)
            
            # Couleur selon l'état
            is_selected = (i == self.selected_index)
            color = self.colors["button_hover"] if is_selected else self.colors["button_bg"]
            
            # Dessiner le bouton
            pygame.draw.rect(surface, color, button_rect, border_radius=10)
            
            # Texte avec icône pour les dossiers
            display_name = f"📁 {name}" if is_dir else name
            text_surf = self.font.render(display_name, True, self.colors["colors_13"])
            text_rect = text_surf.get_rect(center=button_rect.center)
            surface.blit(text_surf, text_rect)

        # Barre de défilement
        if self.total_height > (self.rect.height - self.header_height):
            # Calcul de la barre de défilement
            scrollbar_track_height = self.rect.height - self.header_height
            scrollbar_height = max(20, int((scrollbar_track_height / self.total_height) * scrollbar_track_height))
            
            if self.max_scroll > 0:
                scrollbar_pos = int((self.scroll_offset / self.max_scroll) * (scrollbar_track_height - scrollbar_height))
            else:
                scrollbar_pos = 0
                
            scrollbar_rect = pygame.Rect(
                self.rect.x + self.rect.width - 15, 
                self.rect.y + self.header_height + scrollbar_pos, 
                8, 
                scrollbar_height
            )
            pygame.draw.rect(surface, self.colors["button_hover"], scrollbar_rect, border_radius=4)

        surface.set_clip(old_clip)

    def draw(self, surface):
        """Dessine la fenêtre de sélection de fichiers."""
        if not self.visible:
            return

        # Fond avec ombre
        draw_rounded_rect(surface, self.colors["thumbnail_bg"], self.rect, radius=16, shadow=True)
        pygame.draw.rect(surface, self.colors["colors_13"], self.rect, width=3, border_radius=16)

        # Titre
        title_text = self.title_font.render("Sélectionner un fichier", True, self.colors["foreground"])
        title_rect = title_text.get_rect(center=(self.rect.centerx, self.rect.y + 30))
        surface.blit(title_text, title_rect)

        # Chemin courant
        path_text = self.font.render(str(self.current_dir), True, self.colors["button_hover"])
        path_rect = path_text.get_rect(topleft=(self.rect.x + 10, self.rect.y + 50))
        surface.blit(path_text, path_rect)

        # Clipping pour les éléments
        old_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(self.rect.x, self.rect.y + 70, self.rect.width, self.rect.height - 70))

        # Boutons pour les fichiers/dossiers visibles
        visible_indices = self.get_visible_indices()
        for i in visible_indices:
            name, _, is_dir = self.file_entries[i]
            y = self.rect.y + self.item_height * i - self.scroll_offset
            button_rect = pygame.Rect(self.rect.x + 10, y, self.rect.width - 20, self.item_height - 5)
            is_hovered = (i == self.selected_index)
            color = self.colors["button_hover"] if is_hovered else self.colors["button_bg"]
            pygame.draw.rect(surface, color, button_rect, border_radius=10)
            text_surf = self.font.render(name, True, self.colors["colors_13"])
            text_rect = text_surf.get_rect(center=button_rect.center)
            surface.blit(text_surf, text_rect)

        # Barre de défilement
        visible_count = (self.rect.height - 70) // self.item_height
        total_count = len(self.file_entries)
        if total_count > visible_count:
            scrollbar_height = int((visible_count / total_count) * (self.rect.height - 70))
            scrollbar_pos = int((self.scroll_offset / (total_count * self.item_height - (self.rect.height - 70))) * (self.rect.height - 70))
            scrollbar_rect = pygame.Rect(self.rect.x + self.rect.width - 10, self.rect.y + 70 + scrollbar_pos, 6, scrollbar_height)
            pygame.draw.rect(surface, self.colors["button_hover"], scrollbar_rect, border_radius=3)

        surface.set_clip(old_clip)

    def draw(self, surface):
        """Dessine la fenêtre de sélection de fichiers."""
        if not self.visible:
            return

        # Fond avec ombre
        draw_rounded_rect(surface, self.colors["thumbnail_bg"], self.rect, radius=16, shadow=True)
        pygame.draw.rect(surface, self.colors["colors_13"], self.rect, width=3, border_radius=16)

        # Titre
        title_text = self.title_font.render("Sélectionner un fichier", True, self.colors["foreground"])
        title_rect = title_text.get_rect(center=(self.rect.centerx, self.rect.y + 30))
        surface.blit(title_text, title_rect)

        # Chemin courant
        path_text = self.font.render(str(self.current_dir), True, self.colors["button_hover"])
        path_rect = path_text.get_rect(topleft=(self.rect.x + 10, self.rect.y + 50))
        surface.blit(path_text, path_rect)

        # Clipping pour les éléments
        old_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(self.rect.x, self.rect.y + 70, self.rect.width, self.rect.height - 70))

        # Boutons pour les fichiers/dossiers visibles
        visible_indices = self.get_visible_indices()
        for i in visible_indices:
            name, _, is_dir = self.file_entries[i]
            y = self.rect.y + self.positions[i] - self.scroll_offset
            button_rect = pygame.Rect(self.rect.x + 10, y, self.rect.width - 20, self.item_height - 5)
            is_hovered = (i == self.selected_index)
            color = self.colors["button_hover"] if is_hovered else self.colors["button_bg"]
            pygame.draw.rect(surface, color, button_rect, border_radius=10)
            text_surf = self.font.render(name, True, self.colors["colors_13"])
            text_rect = text_surf.get_rect(center=button_rect.center)
            surface.blit(text_surf, text_rect)

        # Barre de défilement
        visible_count = (self.rect.height - 70) // self.item_height
        total_count = len(self.file_entries)
        if total_count > visible_count:
            scrollbar_height = int((visible_count / total_count) * (self.rect.height - 70))
            scrollbar_pos = int((self.scroll_offset / (total_count * self.item_height - (self.rect.height - 70))) * (self.rect.height - 70))
            scrollbar_rect = pygame.Rect(self.rect.x + self.rect.width - 10, self.rect.y + 70 + scrollbar_pos, 6, scrollbar_height)
            pygame.draw.rect(surface, self.colors["button_hover"], scrollbar_rect, border_radius=3)

        surface.set_clip(old_clip)
        
class ModernProgressBar:
    def __init__(self, x, y, width, height, radius=20, colors=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.radius = radius
        self.progress = 0.0
        self.animation_offset = 0.0
        self.colors = colors if colors else load_wal_colors()  # Charger les couleurs par défaut si none

    def draw(self, surface, progress, current_page, total_pages, show_text=True):
        self.progress += (progress - self.progress) * 0.2
        percent = int(self.progress * 100)

        self._draw_soft_background(surface, self.rect, self.radius)
        shadow_rect = self.rect.copy()
        shadow_rect.y += 6
        self._draw_glow(surface, shadow_rect, (*self.colors["background"], 40), blur_size=10)
        inner_rect = self.rect.inflate(-10, -10)
        fill_width = int(inner_rect.width * self.progress)
        if fill_width > 0:
            fill_rect = pygame.Rect(inner_rect.x, inner_rect.y, fill_width, inner_rect.height)
            self._draw_gradient_fill(surface, fill_rect, self.radius - 8)
        if fill_width > 40:  # Ajuster le seuil pour le bubble
            self._draw_progress_bubble(surface, inner_rect, fill_width, percent)
        if show_text and fill_width <= 40:
            self._draw_center_text(surface, rect, percent)

    def _draw_soft_background(self, surface, rect, radius):
        bg_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(bg_surf, self.colors["button_bg"], (0, 0, rect.width, rect.height), border_radius=radius)
        pygame.draw.rect(bg_surf, (*self.colors["button_bg"], 200), (0, 0, rect.width, rect.height), width=2, border_radius=radius)
        surface.blit(bg_surf, (rect.x, rect.y))

    def _draw_glow(self, surface, rect, color, blur_size=10):
        for i in range(blur_size, 0, -1):
            alpha = color[3] // (i + 1)
            glow_rect = rect.inflate(i * 4, i * 2)
            glow_surf = pygame.Surface((glow_rect.width, glow_rect.height), pygame.SRCALPHA)
            pygame.draw.ellipse(glow_surf, (*color[:3], alpha), (0, 0, glow_rect.width, rect.height))
            surface.blit(glow_surf, (glow_rect.x, rect.y))  # Ajuster pour alignement

    def _draw_gradient_fill(self, surface, rect, radius):
        grad_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        for x in range(rect.width):
            t = x / max(rect.width - 1, 1)
            r = int(self.colors["progress_bar_right"][0] + (self.colors["progress_bar_left"][0] - self.colors["progress_bar_right"][0]) * t)
            g = int(self.colors["progress_bar_right"][1] + (self.colors["progress_bar_left"][1] - self.colors["progress_bar_right"][1]) * t)
            b = int(self.colors["progress_bar_right"][2] + (self.colors["progress_bar_left"][2] - self.colors["progress_bar_right"][2]) * t)
            pygame.draw.line(grad_surf, (r, g, b), (x, 0), (x, rect.height))
        mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, rect.width, rect.height), border_radius=radius)
        grad_surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(grad_surf, (rect.x, rect.y))

    def _draw_progress_bubble(self, surface, inner_rect, fill_width, percent):
        bubble_radius = inner_rect.height // 2 + 4  # Taille ajustée
        cx = inner_rect.x + fill_width
        cy = inner_rect.centery
        shadow_surf = pygame.Surface((bubble_radius * 2 + 6, bubble_radius * 2 + 6), pygame.SRCALPHA)
        pygame.draw.circle(shadow_surf, (*self.colors["background"], 80), (bubble_radius + 3, bubble_radius + 5), bubble_radius)
        surface.blit(shadow_surf, (cx - bubble_radius - 3, cy - bubble_radius - 3))
        bubble_bg = pygame.Surface((bubble_radius * 2 + 6, bubble_radius * 2 + 6), pygame.SRCALPHA)
        pygame.draw.circle(bubble_bg, (*self.colors["button_bg"], 200), (bubble_radius + 3, bubble_radius + 3), bubble_radius + 3)
        surface.blit(bubble_bg, (cx - bubble_radius - 3, cy - bubble_radius - 3))
        pygame.draw.circle(surface, self.colors["progress_bar_right"], (cx, cy), bubble_radius)
        pygame.draw.circle(surface, (*self.colors["progress_bar_right"], 220), (cx, cy), bubble_radius, width=2)
        font = pygame.font.SysFont('arial', int(bubble_radius * 1.4), bold=True)  # Légèrement réduit pour éviter le débordement
        percent_text = f"{percent}%"
        text_surface = font.render(percent_text, True, self.colors["slider_handle"])
        text_rect = text_surface.get_rect(center=(cx, cy))
        surface.blit(text_surface, text_rect)

    def _draw_center_text(self, surface, rect, percent):
        if not rect:  # Vérification pour éviter les erreurs si rect est None ou invalide
            logging.error("Rect non défini dans _draw_center_text")
            return
        font = pygame.font.SysFont('arial', int(rect.height * 0.7), bold=True)
        percent_text = f"{percent}%"
        text_surface = font.render(percent_text, True, self.colors.get("progress_bar_bg", (255, 255, 255)))
        text_rect = text_surface.get_rect(center=rect.center)
        surface.blit(text_surface, text_rect)

    def draw(self, surface, progress, current_page, total_pages, show_text=True):
        self.progress += (progress - self.progress) * 0.2
        percent = int(self.progress * 100)

        self._draw_soft_background(surface, self.rect, self.radius)
        shadow_rect = self.rect.copy()
        shadow_rect.y += 6
        self._draw_glow(surface, shadow_rect, (*self.colors["background"], 40), blur_size=10)
        inner_rect = self.rect.inflate(-10, -10)
        fill_width = int(inner_rect.width * self.progress)
        if fill_width > 0:
            fill_rect = pygame.Rect(inner_rect.x, inner_rect.y, fill_width, inner_rect.height)
            self._draw_gradient_fill(surface, fill_rect, self.radius - 8)
        if fill_width > 40:
            self._draw_progress_bubble(surface, inner_rect, fill_width, percent)
        if show_text and fill_width <= 40:
            self._draw_center_text(surface, self.rect, percent)

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
    def __init__(self, images, screen_width, screen_height, cache, sizes=None):
        super().__init__(images, screen_width, screen_height, cache)
        self.zoom = 1.0
        self.gap = 10
        self.image_positions = []
        self.image_sizes = {}
        self.total_height = 0
        self.sizes = sizes if sizes is not None else {}
        self.lazy_sizes_cache = {}
        self.calculate_layout(self.zoom)

    def calculate_layout(self, zoom, preload_count=3):
        self.zoom = zoom
        self.image_positions = []
        self.image_sizes = {}
        y = 0
        target_width = int(self.screen_width * 0.4 * zoom)
        count = 0
        for img_path in self.images:
            k = (str(img_path), zoom)
            img_name = str(Path(img_path).name)
            if k in self.lazy_sizes_cache:
                w, h = self.lazy_sizes_cache[k]
            elif img_name in self.sizes:
                iw, ih = self.sizes[img_name]["w"], self.sizes[img_name]["h"]
                ratio = target_width / iw if iw != 0 else 1
                w, h = target_width, int(ih * ratio)
                self.lazy_sizes_cache[k] = (w, h)
            elif count < preload_count:
                try:
                    with Image.open(img_path) as img:
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        iw, ih = img.size
                        ratio = target_width / iw if iw != 0 else 1
                        size = (target_width, int(ih * ratio))
                        img = img.resize(size, Image.Resampling.LANCZOS)
                        w, h = img.size
                except Exception:
                    w, h = target_width, 1000
                self.lazy_sizes_cache[k] = (w, h)
                count += 1
            else:
                w, h = target_width, 250
            self.image_sizes[img_path] = (w, h)
            self.image_positions.append(y)
            y += h + self.gap
        self.total_height = y
        self.cache.clear_except_zoom(zoom, 'webtoon')

    def get_visible_indices(self, scroll_offset):
        """Retourne la liste des indices d’images qui sont visibles à l’écran (pour optimiser le rendu)."""
        indices = []
        screen_height = self.screen_height
        for i, y in enumerate(self.image_positions):
            h = self.image_sizes.get(self.images[i], (0, 0))[1]
            # Si l'image est visible (en tout ou partie) dans la fenêtre
            if y + h >= scroll_offset and y <= scroll_offset + screen_height:
                indices.append(i)
        return indices

    def render(self, screen, scroll_offset):
        self.update_screen(*pygame.display.get_surface().get_size())
        indices = self.get_visible_indices(scroll_offset)
        relayout_needed = False
        for i in indices:
            img_path = self.images[i]
            key = f"{img_path}_{self.zoom:.2f}_webtoon"
            k = (str(img_path), self.zoom)
            w, h = self.image_sizes.get(img_path, (1000, 1000))
            cached = self.cache.get(key)
            # Lazy: si on rencontre une image à "estimation", on charge la vraie taille !
            if (w, h) == (int(self.screen_width * 0.4 * self.zoom), 250):
                try:
                    with Image.open(img_path) as img:
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        iw, ih = img.size
                        target_width = int(self.screen_width * 0.4 * self.zoom)
                        ratio = target_width / iw if iw != 0 else 1
                        size = (target_width, int(ih * ratio))
                        img = img.resize(size, Image.Resampling.LANCZOS)
                        w, h = img.size
                except Exception:
                    w, h = target_width, 1000
                self.lazy_sizes_cache[k] = (w, h)
                relayout_needed = True
                break   # On fait UN layout par frame, pas plus
            # Affichage classique
            if cached:
                img, _ = cached
                img_w = img.get_width()
            else:
                img, _ = load_image_to_pygame(img_path, self.screen_width, self.screen_height, self.zoom, 'webtoon')
                if img:
                    self.cache.put(key, (img, (w, h)))
                img_w = w
            x = (self.screen_width - img_w) // 2
            y = self.image_positions[i] - scroll_offset
            if y + h >= 0 and y <= self.screen_height:
                if img:
                    screen.blit(img, (x, y))
                else:
                    pygame.draw.rect(screen, (50, 50, 50), (x, y, w, h))
        # Si on a trouvé une vraie taille, on relayout et on redemande le render
        if relayout_needed:
            self.calculate_layout(self.zoom)
            # On force le redraw au prochain frame (là c’est instant, mais tu peux demander un repaint Pygame si besoin)
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
        self.transition_progress = 0.0  # Progression de l'animation (0.0 à 1.0)
        self.transition_direction = 0    # 0: pas de transition, 1: suivante, -1: précédente
        self.transition_speed = 0.05     # Vitesse de l'animation (ajustable)

    def next_page(self):
        if self.current_page < len(self.images) - 1 and self.transition_progress == 0:
            self.transition_direction = 1
            self.transition_progress = 0.01  # Début de l'animation

    def prev_page(self):
        if self.current_page > 0 and self.transition_progress == 0:
            self.transition_direction = -1
            self.transition_progress = 0.01

    def go_to_page(self, page):
        if self.transition_progress == 0:  # Pas de saut de page pendant une transition
            self.current_page = max(0, min(page, len(self.images)-1))
            self.transition_progress = 0
            self.transition_direction = 0

    def update_transition(self):
        if self.transition_progress > 0:
            self.transition_progress += self.transition_speed
            if self.transition_progress >= 1.0:
                self.transition_progress = 0
                if self.transition_direction == 1:
                    self.current_page += 1
                elif self.transition_direction == -1:
                    self.current_page -= 1
                self.transition_direction = 0

    def render(self, screen):
        self.update_screen(*pygame.display.get_surface().get_size())
        
        # Page actuelle
        i = self.current_page
        key = f"{self.images[i]}_{getattr(self, 'zoom', 1.0):.2f}_manga"
        cached = self.cache.get(key)
        if cached:
            img, (w, h) = cached
        else:
            img, (w, h) = load_image_to_pygame(self.images[i], self.screen_width, self.screen_height, getattr(self, 'zoom', 1.0), 'manga')
            if img: self.cache.put(key, (img, (w, h)))
        
        # Calcul de la position de la page actuelle
        x_current = (self.screen_width - w) // 2
        y = (self.screen_height - h) // 2
        
        if self.transition_progress > 0:
            # Décalage pour l'animation
            offset = int(self.screen_width * self.transition_progress * self.transition_direction)
            x_current -= offset
            
            # Page suivante ou précédente
            next_page = self.current_page + self.transition_direction
            if 0 <= next_page < len(self.images):
                key_next = f"{self.images[next_page]}_1.0_manga"
                cached_next = self.cache.get(key_next)
                if cached_next:
                    img_next, (w_next, h_next) = cached_next
                else:
                    img_next, (w_next, h_next) = load_image_to_pygame(self.images[next_page], self.screen_width, self.screen_height, 1.0, 'manga')
                    if img_next: self.cache.put(key_next, (img_next, (w_next, h_next)))
                
                x_next = x_current + (self.screen_width * self.transition_direction)
                y_next = (self.screen_height - h_next) // 2
                
                # Afficher les deux pages
                if img_next:
                    screen.blit(img_next, (x_next, y_next))
        
        # Afficher la page actuelle
        if img:
            screen.blit(img, (x_current, y))
        else:
            pygame.draw.rect(screen, (50,50,50), (50,50,self.screen_width-100, self.screen_height-100))
        
        return [i]

def print_timing(label, t0):
    t = time.perf_counter()
    print(f"{label:40s}: {t-t0:8.3f}s")
    return t

### Main app loop ###
def run_reader(archive_path, start_page=1, cache_dir=None):
    """Exécute le lecteur avec un fichier d'archive donné."""
    t0 = time.perf_counter()
    try:
        pygame.init()
        pygame.mixer.quit()
        t0 = print_timing("Initialisation Pygame", t0)

        # Charger les couleurs
        colors = load_wal_colors()
        t0 = print_timing("Chargement des couleurs", t0)

        screen_info = pygame.display.Info()
        screen_width, screen_height = screen_info.current_w - 100, screen_info.current_h - 100
        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE | pygame.DOUBLEBUF | pygame.HWSURFACE)
        pygame.display.set_caption("Lecteur Webtoon")
        t0 = print_timing("Configuration de l'écran", t0)

        # Si aucun chemin n'est fourni, ouvrir la boîte de dialogue
        if archive_path is None:
            archive_path = show_file_dialogue()
            if archive_path is None:
                logging.error("Aucun fichier sélectionné, arrêt du programme.")
                cleanup(cache_dir)
        
        archive_path = Path(archive_path).expanduser().absolute()
        if not archive_path.exists():
            logging.error(f"Le fichier {archive_path} n'existe pas.")
            cleanup(cache_dir)

        # Le reste de la logique d'extraction et de cache reste inchangé
        cache_dir = Path.home() / ".config/manga_reader/manga_reader_cache" / get_file_hash(archive_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "image_list.pkl"

        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    images = pickle.load(f)
                t0 = print_timing("Chargement du cache d'images", t0)
            except Exception as e:
                images = []
                logging.error(f"Erreur lors du chargement du cache: {e}")
        else:
            cached_images = []
            for img_name in sorted([f.name for f in cache_dir.iterdir() if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']]):
                cached_images.append(cache_dir / img_name)
            if cached_images:
                images = cached_images
                with open(cache_file, 'wb') as f:
                    pickle.dump(cached_images, f)
                t0 = print_timing("Utilisation des images déjà extraites", t0)
            else:
                with tempfile.TemporaryDirectory() as tmpdirname:
                    tmp_path = Path(tmpdirname)
                    if not extract_archive(archive_path, tmp_path):
                        logging.error(f"Échec de l'extraction de {archive_path}")
                        cleanup(cache_dir)
                    t0 = print_timing("Extraction de l'archive", t0)
                    images = get_image_files(tmp_path)
                    t0 = print_timing("Récupération des fichiers d'image", t0)
                    for img in images:
                        dest = cache_dir / img.name
                        dest.write_bytes(img.read_bytes())
                        cached_images.append(dest)
                    t0 = print_timing("Copie des images dans le cache", t0)
                    with open(cache_file, 'wb') as f:
                        pickle.dump(cached_images, f)
                    t0 = print_timing("Sauvegarde du cache", t0)
                    images = cached_images

        images = [img for img in images if img.exists()]
        if not images:
            logging.error("Aucune image valide trouvée dans l'archive ou le cache.")
            cleanup(cache_dir)
        t0 = print_timing("Vérification des images", t0)

        def preload_first_image():
            try:
                with Image.open(images[0]) as im:
                    im = im.convert("RGB")
                    im = im.resize((200, 200))
            except Exception as e:
                print(f"[SPLASH] Erreur préchargement image : {e}")

        show_splash(
            image_path=str(images[0]),
            wait_time=1.0,
            do_radius=True,
            preload_func=preload_first_image
        )
        t0 = print_timing("Affichage de l'écran de démarrage", t0)

        pygame.display.quit()
        pygame.display.init()
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.HWSURFACE)
        screen_width, screen_height = screen.get_size()
        pygame.display.set_caption(f"Lecteur Webtoon: {Path(archive_path).stem}")
        subprocess.Popen(["hyprctl", "dispatch", "fullscreen", "focuswindow", "Lecteur Webtoon"])
        pygame.mixer.quit()
        t0 = print_timing("Passage en mode plein écran", t0)

        sizes_file = cache_dir / "sizes.json"
        if sizes_file.exists():
            with open(sizes_file, "r", encoding="utf-8") as f:
                sizes = json.load(f)
            t0 = print_timing("Chargement des tailles depuis sizes.json", t0)
        else:
            sizes = {}
            for img in images:
                try:
                    with Image.open(img) as im:
                        sizes[str(img.name)] = {"w": im.width, "h": im.height}
                except Exception:
                    sizes[str(img.name)] = {"w": 1000, "h": 1500}
            t0 = print_timing("Calcul des tailles des images", t0)
            with open(sizes_file, "w", encoding="utf-8") as f:
                json.dump(sizes, f)
            t0 = print_timing("Sauvegarde des tailles dans sizes.json", t0)

        mode = detect_mode(images)
        t0 = print_timing("Détection du mode (webtoon/manga)", t0)

        image_cache = ImageCache(max_size=150)
        zoom = 1.0
        scroll_offset = 0
        loader = ImageLoaderThread(image_cache, images, screen_width, screen_height, zoom)
        webtoon_renderer = WebtoonRenderer(images, screen_width, screen_height, image_cache, sizes=sizes)
        manga_renderer = MangaRenderer(images, screen_width, screen_height, image_cache)
        t0 = print_timing("Initialisation du cache et des renderers", t0)

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
        t0 = print_timing("Initialisation de la progression et du mode", t0)

        font = pygame.font.SysFont('arial', 18, bold=True)
        mode_button = ModernButton(screen_width - 250, 10, 120, 30, f"{mode.capitalize()}", font, colors)
        play_button = ModernButton(screen_width - 120, 10, 100, 30, "Play", font, colors)
        speed_slider = Slider(screen_width - 140, 50, 100, 10, 150, 1200, 200, colors)
        progress_bar = ModernProgressBar(screen_width - 220, screen_height - 50, 200, 25, colors=colors)
        thumbnail_viewer = ThumbnailViewer(10, 10, 120, screen_height - 20, images, image_cache, screen_width, screen_height, colors, cache_dir)
        file_selector = FileSelector(screen_width, screen_height, colors, initial_dir=archive_path.parent if archive_path else None)
        running = True
        is_scrolling = False
        last_scroll_time = pygame.time.get_ticks() / 1000.0
        thumbnail_viewer.scroll_to_current_page(current_page)
        t0 = print_timing("Initialisation des widgets UI", t0)

        def update_layout():
            nonlocal screen_width, screen_height
            screen_width, screen_height = pygame.display.get_surface().get_size()
            mode_button.rect.topleft = (screen_width - 250, 10)
            play_button.rect.topleft = (screen_width - 120, 10)
            speed_slider.rect.topleft = (screen_width - 240, 50)
            if mode == 'webtoon':
                progress_bar.rect.topright = (screen_width - 220, screen_height - 50)
            else:  # mode 'manga'
                progress_bar.rect.topright = (screen_width - 220, screen_height - 50)
            thumbnail_viewer.rect = pygame.Rect(10, 10, 120, screen_height - 20)
            thumbnail_viewer.calculate_layout()
            file_selector.rect = pygame.Rect(
                (screen_width - file_selector.width) // 2,
                (screen_height - file_selector.height) // 2,
                file_selector.width,
                file_selector.height
            )
            file_selector.calculate_layout()
            webtoon_renderer.update_screen(screen_width, screen_height)
            manga_renderer.update_screen(screen_width, screen_height)
            webtoon_renderer.calculate_layout(zoom)
            image_cache.clear_except_zoom(zoom, 'webtoon')

        clock = pygame.time.Clock()
        while running:
            current_time = pygame.time.get_ticks() / 1000.0
            delta_time = current_time - last_scroll_time
            last_scroll_time = current_time

            t_loop_start = time.perf_counter()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    update_layout()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_o:
                        file_selector.visible = not file_selector.visible
                    elif file_selector.visible:
                        result = file_selector.handle_event(event)
                        if result == "consumed":
                            continue
                        elif result is not None:
                            progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
                            loader.stop()
                            image_cache.clear()
                            pygame.display.quit()
                            pygame.display.init()
                            return run_reader(result, start_page=1, cache_dir=cache_dir)
                        # Restaurer l'affichage si aucun fichier n'est sélectionné
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.HWSURFACE)
                        screen_width, screen_height = screen.get_size()
                        pygame.display.set_caption(f"Lecteur Webtoon: {Path(archive_path).stem}")
                        loader = ImageLoaderThread(image_cache, images, screen_width, screen_height, zoom)
                        update_layout()
                    elif event.type == pygame.MOUSEWHEEL or event.type == pygame.MOUSEBUTTONDOWN:
                        if file_selector.visible:
                            result = file_selector.handle_event(event)
                            if result == "consumed":
                                continue
                            elif result is not None:
                                progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
                                loader.stop()
                                image_cache.clear()
                                pygame.display.quit()
                                pygame.display.init()
                                return run_reader(result, start_page=1, cache_dir=cache_dir)
                    elif mode == 'webtoon' and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        if event.key == pygame.K_UP:
                            old_zoom = zoom
                            zoom = min(zoom + 0.2, 1.5)
                            if zoom != old_zoom:
                                current_page_index = 0
                                offset_in_image = 0
                                for i, pos in enumerate(webtoon_renderer.image_positions):
                                    if pos <= scroll_offset:
                                        current_page_index = i
                                        offset_in_image = scroll_offset - pos
                                    else:
                                        break

                                if offset_in_image < 0:
                                    current_page_index = max(0, current_page_index - 1)
                                    offset_in_image = 0

                                old_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                                image_scroll_ratio = offset_in_image / max(1, old_image_height)

                                webtoon_renderer.calculate_layout(zoom)
                                image_cache.clear()

                                if current_page_index == 0:
                                    scroll_offset = 0
                                else:
                                    new_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                                    scroll_offset = webtoon_renderer.image_positions[current_page_index] + int(image_scroll_ratio * new_image_height)

                        elif event.key == pygame.K_DOWN:
                            old_zoom = zoom
                            zoom = max(zoom - 0.2, 0.6)
                            if zoom != old_zoom:
                                current_page_index = 0
                                offset_in_image = 0
                                for i, pos in enumerate(webtoon_renderer.image_positions):
                                    if pos <= scroll_offset:
                                        current_page_index = i
                                        offset_in_image = scroll_offset - pos
                                    else:
                                        break

                                if offset_in_image < 0:
                                    current_page_index = max(0, current_page_index - 1)
                                    offset_in_image = 0

                                old_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                                image_scroll_ratio = offset_in_image / max(1, old_image_height)

                                webtoon_renderer.calculate_layout(zoom)
                                image_cache.clear()

                                if current_page_index == 0:
                                    scroll_offset = 0
                                else:
                                    new_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                                    scroll_offset = webtoon_renderer.image_positions[current_page_index] + int(image_scroll_ratio * new_image_height)

                    elif mode == 'manga' and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        if event.key == pygame.K_UP:
                            old_zoom = manga_renderer.zoom if hasattr(manga_renderer, 'zoom') else 1.0
                            new_zoom = min(old_zoom + 0.2, 1.5)
                            if not hasattr(manga_renderer, 'zoom') or new_zoom != old_zoom:
                                manga_renderer.zoom = new_zoom
                                image_cache.clear()
                        elif event.key == pygame.K_DOWN:
                            old_zoom = manga_renderer.zoom if hasattr(manga_renderer, 'zoom') else 1.0
                            new_zoom = max(old_zoom - 0.2, 0.6)
                            if not hasattr(manga_renderer, 'zoom') or new_zoom != old_zoom:
                                manga_renderer.zoom = new_zoom
                                image_cache.clear()
                    if event.key == pygame.K_TAB:
                        thumbnail_viewer.visible = not thumbnail_viewer.visible
                    elif event.key == pygame.K_q:
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
                    elif not thumbnail_viewer.visible and not file_selector.visible:
                        if mode == 'webtoon':
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
                    if file_selector.visible:
                        result = file_selector.handle_event(event)
                        if result == "consumed":
                            continue
                        elif result is not None:
                            progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
                            loader.stop()
                            image_cache.clear()
                            pygame.display.quit()
                            pygame.display.init()
                            return run_reader(result, start_page=1, cache_dir=cache_dir)
                    if mode == 'webtoon' and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        old_zoom = zoom
                        if event.y > 0:
                            zoom = min(zoom + 0.2, 1.5)
                        elif event.y < 0:
                            zoom = max(zoom - 0.2, 0.6)
                        if zoom != old_zoom:
                            current_page_index = 0
                            offset_in_image = 0
                            for i, pos in enumerate(webtoon_renderer.image_positions):
                                if pos <= scroll_offset:
                                    current_page_index = i
                                    offset_in_image = scroll_offset - pos
                                else:
                                    break

                            if offset_in_image < 0:
                                current_page_index = max(0, current_page_index - 1)
                                offset_in_image = 0

                            old_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                            image_scroll_ratio = offset_in_image / max(1, old_image_height)

                            webtoon_renderer.calculate_layout(zoom)
                            image_cache.clear()

                            if current_page_index == 0:
                                scroll_offset = 0
                            else:
                                new_image_height = webtoon_renderer.image_sizes.get(webtoon_renderer.images[current_page_index], (0,1))[1]
                                scroll_offset = webtoon_renderer.image_positions[current_page_index] + int(image_scroll_ratio * new_image_height)
                        continue
                    if mode == 'manga' and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                        old_zoom = manga_renderer.zoom if hasattr(manga_renderer, 'zoom') else 1.0
                        if event.y > 0:
                            new_zoom = min(old_zoom + 0.2, 1.5)
                        elif event.y < 0:
                            new_zoom = max(old_zoom - 0.2, 0.6)
                        else:
                            new_zoom = old_zoom
                        if not hasattr(manga_renderer, 'zoom') or new_zoom != old_zoom:
                            manga_renderer.zoom = new_zoom
                            image_cache.clear()
                        continue
                    thumbnail_result = thumbnail_viewer.handle_event(event)
                    if thumbnail_result == "consumed":
                        continue
                    elif thumbnail_result is not None and isinstance(thumbnail_result, int):
                        if mode == 'webtoon':
                            if thumbnail_result - 1 < len(webtoon_renderer.image_positions):
                                scroll_offset = webtoon_renderer.image_positions[thumbnail_result - 1]
                                current_page = thumbnail_result
                        else:
                            manga_renderer.go_to_page(thumbnail_result - 1)
                            current_page = thumbnail_result
                    else:
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
                page_selected = thumbnail_viewer.handle_event(event)
                if page_selected is not None:
                    if mode == 'webtoon':
                        if page_selected - 1 < len(webtoon_renderer.image_positions):
                            scroll_offset = webtoon_renderer.image_positions[page_selected - 1]
                            current_page = page_selected
                    else:
                        manga_renderer.go_to_page(page_selected - 1)
                        current_page = page_selected
            t0 = print_timing("Gestion des événements", t_loop_start)

            keys = pygame.key.get_pressed()
            if mode == 'manga':
                manga_renderer.update_transition()
            if not thumbnail_viewer.visible and not file_selector.visible:
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
            t0 = print_timing("Mise à jour du défilement", t0)

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
            t0 = print_timing("Rendu des images", t0)

            if thumbnail_viewer.visible:
                thumbnail_viewer.scroll_to_current_page(current_page)
                thumbnail_viewer.draw(screen, current_page)
            progress_mgr.save(manga_name, chapter_number, current_page, total_pages)
            t0 = print_timing("Sauvegarde de la progression", t0)

            text = font.render(f"{Path(archive_path).stem}", True, colors["foreground"])
            screen.blit(text, (10, 10))
            mode_button.draw(screen)
            if mode == 'webtoon':
                play_button.draw(screen)
                speed_slider.draw(screen)
            progress_bar.draw(screen, progress, current_page, total_pages)
            thumbnail_viewer.draw(screen, current_page)
            file_selector.draw(screen)  # Ajouter le rendu de FileSelector
            t0 = print_timing("Rendu des éléments UI", t0)

            pygame.display.flip()
            t0 = print_timing("Mise à jour de l'affichage", t0)
            clock.tick(60)

        progress_mgr.save(manga_name, chapter_number, current_page, total_pages, force_save=True)
        loader.stop()
        cleanup(cache_dir)
        t0 = print_timing("Nettoyage final", t0)
    except Exception as e:
        logging.error(f"Exception non gérée : {e}")
        cleanup(cache_dir)

def main(archive_path=None, start_page=1):
    print("[DEBUG] ARGV:", sys.argv)
    print("[DEBUG] CWD:", os.getcwd())
    print("[DEBUG] archive_path:", archive_path)
    run_reader(archive_path, start_page)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manga/Webtoon Reader")
    parser.add_argument("archive_path", nargs='?', default=None, help="Path to the manga archive file")
    parser.add_argument("--page", type=int, default=0, help="Starting page number")
    args = parser.parse_args()
    db_path = Path.home() / ".config" / "manga_reader" / "library.db"
    progress_path = Path.home() / ".config" / "manga_reader" / "progress.json"
    migrate_progress_json(db_path, progress_path)
    main(args.archive_path, args.page)