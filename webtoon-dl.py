#!/usr/bin/env python3
import os
import json
import re
import time
import shutil
import urllib.parse
from zipfile import ZipFile
from typing import List, Tuple, Set
from PIL import Image
import io
import argparse
import requests
import cloudscraper
from bs4 import BeautifulSoup
import sys

# Configuration initiale
default_output_dir = os.path.expanduser("~/Documents/Scan")
config_path = os.path.expanduser("~/.config/manga_reader/config.json")
try:
    with open(config_path, "r") as f:
        config = json.load(f)
        if config.get("last_manga_dir"):
            default_output_dir = config["last_manga_dir"]
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    print("⚠️ Could not read manga_reader config, using default output directory")

# Arguments de la ligne de commande
parser = argparse.ArgumentParser(description="Webtoon Downloader for mangas-origines.fr and anime-sama.fr")
parser.add_argument(
    "url",
    type=str,
    help="URL of the scan page (e.g., https://mangas-origines.fr/oeuvre/.../chapitre-1 or https://anime-sama.fr/catalogue/.../scan/vf/)"
)
parser.add_argument(
    "chapters",
    type=str,
    nargs="?",
    default="1",
    help="Chapters to download (e.g., 1-3,5)"
)
parser.add_argument(
    "-o",
    "--output-dir",
    type=str,
    default=default_output_dir,
    help=f"Directory where manga folders and cache will be created (default: {default_output_dir})"
)
args = parser.parse_args()

# Création des répertoires
output_dir = os.path.expanduser(args.output_dir)
os.makedirs(output_dir, exist_ok=True)

# Validation de l'URL et détection du site
start_url = args.url.strip()
site = None
base_url = None
oeuvre_url = None

# Détection pour mangas-origines.fr
if "mangas-origines.fr" in start_url:
    site = "mangas-origines"
    base_match = re.search(r'(.*?/chapitre-)(\d+)', start_url)
    if not base_match:
        print("❌ Invalid URL provided for mangas-origines.fr.")
        exit(1)
    base_url = base_match.group(1)
    oeuvre_url_match = re.search(r'(.*?/oeuvre/[^/]+)', start_url)
    if not oeuvre_url_match:
        print("❌ Could not determine the manga page URL for mangas-origines.fr")
        exit(1)
    oeuvre_url = oeuvre_url_match.group(1)

# Détection pour anime-sama.fr
elif "anime-sama.fr" in start_url:
    site = "anime-sama"
    base_match = re.search(r'(.*?/scan/vf/?)', start_url)
    if not base_match:
        print("❌ Invalid URL provided for anime-sama.fr. Expected format: /scan/vf/")
        exit(1)
    base_url = base_match.group(1)  # Base URL pour construire les URLs des chapitres
    oeuvre_url_match = re.search(r'(.*?/catalogue/[^/]+)', start_url)
    if not oeuvre_url_match:
        print("❌ Could not determine the manga page URL for anime-sama.fr")
        exit(1)
    oeuvre_url = oeuvre_url_match.group(1)
else:
    print("❌ Unsupported site. Supported sites: mangas-origines.fr, anime-sama.fr")
    exit(1)

# Analyse des chapitres demandés
chap_input = args.chapters.strip()
try:
    chapters: Set[int] = set()
    for part in chap_input.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            chapters.update(range(start, end + 1))
        else:
            chapters.add(int(part))
    chapters = sorted(chapters)
except ValueError:
    print("❌ Invalid chapter format. Use numbers, commas, or ranges (e.g., 1-3,5)")
    exit(1)

# Afficher le résumé initial
print(f"Downloading {len(chapters)} chapters to {max(chapters)}")

# Initialisation du scraper
scraper = cloudscraper.create_scraper()

# Extraire le nom du manga
try:
    soup_preview = BeautifulSoup(scraper.get(oeuvre_url).text, 'html.parser')
    if site == "mangas-origines":
        breadcrumb = soup_preview.select_one('.breadcrumb a[href*="/oeuvre/"]')
        manga_name = breadcrumb.text.strip().replace(" ", "_") if breadcrumb else "Manga"
    else:  # anime-sama.fr
        # Plusieurs sélecteurs possibles pour le titre
        title_selectors = [
            'h1.text-2xl',
            'h1',
            '.text-2xl',
            'title'
        ]
        manga_name = None
        for selector in title_selectors:
            title_elem = soup_preview.select_one(selector)
            if title_elem:
                manga_name = title_elem.get_text().strip()
                # Nettoyer le titre (enlever les suffixes comme "- Anime-Sama")
                manga_name = re.sub(r'\s*-\s*Anime[- ]Sama.*$', '', manga_name, flags=re.IGNORECASE)
                break
        
        if not manga_name:
            # Fallback: extraire depuis l'URL
            url_match = re.search(r'/catalogue/([^/]+)', start_url)
            if url_match:
                manga_name = url_match.group(1).replace('-', ' ')
        
        manga_name = manga_name.replace(" ", "_") if manga_name else "Manga"
        
    print(f"📖 Manga détecté: {manga_name.replace('_', ' ')}")
    sys.stdout.write(f"📖 Manga en cours de téléchargement: {manga_name.replace('_', ' ')}\n")
    sys.stdout.flush()
except Exception as e:
    print(f"⚠️ Error fetching manga name: {e}")
    manga_name = "Manga"

# Création des dossiers
manga_dir = os.path.join(output_dir, manga_name)
cache_dir = os.path.join(output_dir, "cache")
print(f"📁 Manga Folder: {manga_dir}")
os.makedirs(manga_dir, exist_ok=True)
os.makedirs(cache_dir, exist_ok=True)

# Téléchargement de la couverture et du synopsis
cover_path = os.path.join(manga_dir, "cover.jpg")
synopsis_path = os.path.join(manga_dir, "synopsis.txt")

if not os.path.exists(cover_path) or not os.path.exists(synopsis_path):
    print(f"📘 Fetching manga info: {oeuvre_url}")
    try:
        r_oeuvre = scraper.get(oeuvre_url)
        if r_oeuvre.status_code != 200:
            print(f"❌ Manga page not found: {oeuvre_url}")
        else:
            soup_oeuvre = BeautifulSoup(r_oeuvre.text, 'html.parser')

            # Télécharger la couverture
            cover_url = None
            if site == "mangas-origines":
                og_image = soup_oeuvre.select_one('meta[property="og:image"]')
                if og_image and og_image.get('content'):
                    cover_url = og_image['content']
                    print(f"ℹ️ Found og:image: {cover_url}")

                if not cover_url:
                    cover_img = (
                        soup_oeuvre.select_one('div.summary_image img[srcset]') or
                        soup_oeuvre.select_one('picture.img-responsive img[srcset]') or
                        soup_oeuvre.select_one('img[alt*="Cover"][data-fullsrc]') or
                        soup_oeuvre.select_one('img[alt*="thumbnail"][data-fullsrc]') or
                        soup_oeuvre.select_one('div.summary_image img') or
                        soup_oeuvre.select_one('picture.img-responsive img') or
                        soup_oeuvre.select_one('img[alt*="Cover"], img[alt*="thumbnail"]') or
                        soup_oeuvre.select_one('.thumbnail img')
                    )
                    if cover_img:
                        if cover_img.get('srcset'):
                            srcset = cover_img['srcset'].split(',')
                            cover_url = max(srcset, key=lambda x: int(x.split()[-2]) if x.split()[-2].isdigit() else 0).split()[0]
                        elif cover_img.get('data-fullsrc'):
                            cover_url = cover_img['data-fullsrc']
                        elif cover_img.get('data-src'):
                            cover_url = cover_img['data-src']
                        else:
                            cover_url = cover_img.get('src')

                        if cover_url and not cover_url.startswith("http"):
                            cover_url = urllib.parse.urljoin(oeuvre_url, cover_url)

                        if "/thumbnail/" in cover_url.lower():
                            cover_url = cover_url.replace("/thumbnail/", "/full/")
                        elif "?size=" in cover_url.lower():
                            cover_url = re.sub(r"size=\w+", "size=large", cover_url)
                        elif "/small/" in cover_url.lower():
                            cover_url = cover_url.replace("/small/", "/large/")
            else:  # anime-sama.fr
                cover_img = soup_oeuvre.select_one('#coverOeuvre')
                if cover_img and cover_img.get('src'):
                    cover_url = cover_img['src']
                    print(f"ℹ️ Found cover: {cover_url}")

            if cover_url:
                try:
                    print(f"ℹ️ Attempting to download cover from: {cover_url}")
                    cover_data = scraper.get(cover_url).content
                    original_image = Image.open(io.BytesIO(cover_data))
                    original_width, original_height = original_image.size

                    # Redimensionner à une largeur fixe de 900px
                    target_width = 900
                    aspect_ratio = original_height / original_width
                    new_width = target_width
                    new_height = int(new_width * aspect_ratio)
                    print(f"ℹ️ Resizing cover from {original_width}x{original_height} to {new_width}x{new_height}")
                    resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    resized_image = resized_image.convert('RGB')
                    resized_image.save(cover_path, quality=95)

                    print(f"✅ Cover downloaded and resized: {cover_path}")

                    file_size = os.path.getsize(cover_path) / 1024  # Taille en KB
                    if file_size < 50:
                        print(f"⚠️ Cover file size is small ({file_size:.1f} KB), consider checking the source.")
                except Exception as e:
                    print(f"❌ Error downloading or resizing cover: {e}")
                    try:
                        with open(cover_path, 'wb') as f:
                            f.write(cover_data)
                        print(f"⚠️ Saved original cover without resizing: {cover_path}")
                    except Exception as e2:
                        print(f"❌ Failed to save original cover: {e2}")
            else:
                print("⚠️ Cover URL not found")

            # Télécharger le synopsis
            synopsis_text = None
            if site == "mangas-origines":
                synopsis_div = soup_oeuvre.select_one('.summary__content') or soup_oeuvre.select_one('.summary images')
                if synopsis_div:
                    synopsis_text = synopsis_div.get_text(separator=' ', strip=True)
            else:  # anime-sama.fr
                synopsis_div = soup_oeuvre.select_one('p.text-sm.text-gray-400.mt-2')
                if synopsis_div:
                    synopsis_text = synopsis_div.get_text(separator=' ', strip=True)

            if synopsis_text:
                sentences = [s.strip() for s in synopsis_text.split('.')]
                sentences = [s + '.' for s in sentences if s]
                if sentences and not sentences[-1].endswith('.'):
                    sentences[-1] = sentences[-1] + '.'
                formatted_synopsis = '\n\n'.join(sentences)

                title = f"{manga_name.replace('_', ' ')}"
                title_underline = '━' * len(title)

                with open(synopsis_path, 'w', encoding='utf-8') as f:
                    f.write(f"{title}\n{title_underline}\n\n{formatted_synopsis}\n\nSource: {oeuvre_url}")
                print(f"✅ Synopsis saved: {synopsis_path}")
            else:
                print("⚠️ Synopsis not found")

    except Exception as e:
        print(f"❌ Error fetching manga info: {e}")
else:
    print("ℹ️ Cover and synopsis already exist, skipping.")

# Téléchargement des chapitres
downloaded_chapters: List[Tuple[int, str, str]] = []

for idx, current_chapter in enumerate(chapters, 1):
    print(f"Downloading Chapter {current_chapter} ({idx}/{len(chapters)})")
    sys.stdout.write(f"Downloading Chapter {current_chapter}\n")
    sys.stdout.flush()
    time.sleep(0.1)  # Délai pour permettre à Rust de capturer les logs

    # Réinitialiser le cache
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)

    try:
        img_urls = []
        
        if site == "mangas-origines":
            url = base_url + str(current_chapter)
            r = scraper.get(url)
            if r.status_code != 200:
                print(f"❌ Chapter page not accessible: {url}")
                sys.stdout.write(f"Chapter {current_chapter} failed: Page not accessible\n")
                sys.stdout.flush()
                downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", "Failed: Page not accessible"))
                continue

            soup = BeautifulSoup(r.text, 'html.parser')
            img_tags = [img for img in soup.find_all('img') if "/uploads/" in (img.get('src') or '')]
            if len(img_tags) <= 1:
                print(f"⚠️ No valid images for Chapter {current_chapter}")
                sys.stdout.write(f"No valid images for Chapter {current_chapter}\n")
                sys.stdout.flush()
                downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", "Failed: No images"))
                continue
            img_tags = img_tags[1:]  # Ignorer la première image

            for img in img_tags:
                img_url = (
                    img.get('data-src') or
                    img.get('src') or
                    img.get('data-lazy-src') or
                    img.get('data-cfsrc')
                )
                if img_url:
                    if not img_url.startswith("http"):
                        img_url = urllib.parse.urljoin(url, img_url)
                    img_urls.append(img_url)
                    
        else:  # anime-sama.fr
            # Pour anime-sama.fr, construire directement les URLs des images
            # Basé sur le pattern: https://anime-sama.fr/s2/scans/Hunter x Hunter/1/1.jpg
            manga_name_for_url = manga_name.replace('_', ' ')
            base_img_url = f"https://anime-sama.fr/s2/scans/{manga_name_for_url}/{current_chapter}/"
            
            print(f"🔍 Building image URLs for chapter {current_chapter}: {base_img_url}")
            
            # Essayer de détecter le nombre de pages en testant les URLs
            max_pages = 100  # Limite raisonnable
            for page in range(1, max_pages + 1):
                img_url = f"{base_img_url}{page}.jpg"
                try:
                    # Faire un HEAD request pour vérifier si l'image existe
                    response = scraper.head(img_url, timeout=10)
                    if response.status_code == 200:
                        img_urls.append(img_url)
                        if page == 1:
                            print(f"✅ First image found: {img_url}")
                    else:
                        # Si on trouve une 404, on arrête (fin du chapitre)
                        if page == 1:
                            print(f"❌ First image not found: {img_url}")
                        break
                except requests.RequestException as e:
                    if page == 1:
                        print(f"❌ Error checking first image: {e}")
                    break
                    
                # Petite pause pour ne pas surcharger le serveur
                time.sleep(0.1)

        if not img_urls:
            print(f"⚠️ No valid images for Chapter {current_chapter}")
            sys.stdout.write(f"No valid images for Chapter {current_chapter}\n")
            sys.stdout.flush()
            downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", "Failed: No images"))
            continue

        print(f"Found {len(img_urls)} images for Chapter {current_chapter}")
        sys.stdout.write(f"Found {len(img_urls)} images for Chapter {current_chapter}\n")
        sys.stdout.flush()
        time.sleep(0.1)

        # Télécharger les images
        final_images = []
        for i, img_url in enumerate(img_urls, 1):
            ext = os.path.splitext(img_url)[-1].split('?')[0]
            if ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
                ext = '.jpg'
            filename = os.path.join(cache_dir, f"{i:03d}{ext}")

            max_retries = 3
            success = False
            for attempt in range(max_retries):
                try:
                    img_data = scraper.get(img_url).content
                    with open(filename, 'wb') as f:
                        f.write(img_data)
                    final_images.append(filename)
                    print(f"Downloaded image {i}/{len(img_urls)} for Chapter {current_chapter}")
                    sys.stdout.write(f"Downloaded image {i}/{len(img_urls)} for Chapter {current_chapter}\n")
                    sys.stdout.flush()
                    success = True
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"⚠️ Page {i} error (attempt {attempt + 1}/{max_retries}): {e}. Retrying...")
                        sys.stdout.write(f"Page {i} error (attempt {attempt + 1}/{max_retries}): {e}. Retrying...\n")
                        sys.stdout.flush()
                        time.sleep(1)
                    else:
                        print(f"❌ Page {i} failed after {max_retries} attempts: {e}")
                        sys.stdout.write(f"Page {i} failed after {max_retries} attempts: {e}\n")
                        sys.stdout.flush()
                        break
            time.sleep(0.2)

        if not final_images:
            print(f"⚠️ No images downloaded for Chapter {current_chapter}")
            sys.stdout.write(f"No images downloaded for Chapter {current_chapter}\n")
            sys.stdout.flush()
            downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", "Failed: No images downloaded"))
            continue

        # Créer le fichier CBR
        zip_path = os.path.join(manga_dir, f"Chapitre_{current_chapter:03d}.cbr")
        with ZipFile(zip_path, 'w') as myzip:
            for img in final_images:
                myzip.write(img, os.path.basename(img))

        print(f"✅ Chapitre_{current_chapter:03d}.cbr created with {len(final_images)} image(s).")
        sys.stdout.write(f"Chapitre_{current_chapter:03d}.cbr created with {len(final_images)} image(s).\n")
        sys.stdout.flush()
        downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", "Success"))

        # Nettoyage
        for file in os.listdir(cache_dir):
            os.remove(os.path.join(cache_dir, file))
        time.sleep(1)

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.stdout.write(f"Unexpected error: {e}\n")
        sys.stdout.flush()
        downloaded_chapters.append((current_chapter, f"Chapitre_{current_chapter:03d}", f"Failed: {e}"))

# Résumé final
print("\n🎉 Download Complete!")
sys.stdout.write("Download Complete!\n")
sys.stdout.flush()
if downloaded_chapters:
    print("Download Summary:")
    for chap, title, status in downloaded_chapters:
        print(f"Chapter {chap} - {title}: {status}")
else:
    print("⚠️ No chapters were downloaded.")