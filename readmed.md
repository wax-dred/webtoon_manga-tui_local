Manga Reader

Manga Reader est une application en Rust et Python conçue pour organiser, parcourir et lire vos mangas et webtoons en local. Avec une interface utilisateur intuitive basée sur Ratatui (TUI) et un visualiseur de chapitres utilisant Pygame, ce projet offre une expérience fluide pour les amateurs de mangas. Il inclut également un outil de téléchargement pour récupérer des chapitres depuis des sites comme mangas-origines.fr et anime-sama.fr, avec une gestion efficace du cache et une prise en charge des formats CBR, CBZ et PDF.

Capture d'écran de l'interface principale
Ajoutez ici une capture d'écran de l'interface TUI montrant la liste des mangas et chapitres.
Fonctionnalités

    Interface TUI (Terminal User Interface) :
        Parcourez vos mangas dans une liste claire avec filtres.
        Visualisez les chapitres d'un manga sélectionné avec des détails (numéro, titre, date, taille, état de lecture).
        Affichez une couverture et un synopsis pour chaque manga.
        Navigation fluide avec raccourcis clavier (j/k pour naviguer, Tab pour changer de focus, etc.).
    Lecteur de chapitres :
        Visualisez les chapitres en mode Webtoon (défilement vertical) ou Manga (pagination) via Pygame.
        Support des formats CBR, CBZ et PDF.
        Zoom et défilement personnalisables pour une lecture confortable.
        Cache optimisé pour un chargement rapide des images.
    Téléchargement de chapitres :
        Téléchargez des chapitres depuis mangas-origines.fr et anime-sama.fr en spécifiant une URL et une liste de chapitres.
        Crée automatiquement des fichiers CBR avec les images téléchargées.
        Récupère la couverture et le synopsis du manga pour enrichir votre bibliothèque.
    Gestion locale :
        Organisez vos mangas dans un répertoire local.
        Suivez les chapitres lus et non lus via un fichier de configuration (~/.config/manga_reader/config.json).
        Prise en charge des archives compressées (CBR/CBZ) et des PDF.

Prérequis

Pour utiliser Manga Reader, vous devez installer les dépendances suivantes :

    Système : Linux (testé sur Ubuntu/Debian) ou macOS. Windows n'est pas encore officiellement supporté.
    Rust : Version 1.65 ou supérieure (pour compiler app.rs).
    Python : Version 3.8 ou supérieure (pour manga-live.py et webtoon-dl.py).
    Dépendances système :
        libx11-dev, libxcb1-dev, libxkbcommon-dev (pour Rust/TUI).
        python3-pip, python3-dev, libjpeg-dev, zlib1g-dev (pour Python/PIL).
        unrar (pour extraire les fichiers CBR).
        poppler-utils (pour convertir les PDF en images).
    Dépendances Python (listées dans requirements.txt, installées via install.sh).

Installation

Suivez ces étapes pour installer Manga Reader sur votre système :

    Cloner le dépôt :
    bash

git clone https://github.com/wax-dred/webtoon_manga-tui_local.git
cd manga-reader

Rendre le script d'installation exécutable :
bash
chmod +x install.sh

Exécuter le script d'installation :
bash

    ./install.sh

    Le script install.sh :
        Installe les dépendances système (Rust, Python, unrar, poppler-utils).
        Compile l'application Rust (cargo build --release).
        Installe les dépendances Python via pip (requirements.txt).

    Capture d'écran du processus d'installation
    Ajoutez ici une capture d'écran de la sortie du script d'installation.

    Vérifier l'installation :
        Assurez-vous que l'exécutable Rust est généré dans target/release/manga-reader.
        Vérifiez que les scripts Python (manga-live.py, webtoon-dl.py) sont exécutables.

Utilisation
1. Lancer l'application

Pour démarrer l'interface TUI, exécutez :
bash
./target/release/manga-reader /chemin/vers/votre/repertoire/mangas

    Remplacez /chemin/vers/votre/repertoire/mangas par le chemin de votre répertoire contenant les mangas (fichiers CBR, CBZ, PDF ou dossiers).
    L'application charge automatiquement les mangas et chapitres depuis ce répertoire.

Raccourcis clavier dans l'interface TUI :

    j/k : Naviguer dans la liste des mangas ou chapitres.
    Tab : Basculer entre la liste des mangas et des chapitres.
    Enter : Ouvrir un chapitre (via manga-live.py).
    d : Passer en mode téléchargement pour saisir une URL et des chapitres.
    q : Quitter l'application.

Capture d'écran de la navigation TUI
Ajoutez ici une capture d'écran montrant la navigation dans l'interface TUI.
2. Lire un chapitre

Lorsque vous sélectionnez un chapitre avec Enter, l'application lance manga-live.py pour afficher le chapitre dans une fenêtre Pygame.

Modes de lecture :

    Webtoon : Défilement vertical, idéal pour les webtoons (touche w).
    Manga : Pagination, parfait pour les mangas traditionnels (touche m).

Raccourcis clavier dans le lecteur :

    w : Passer en mode Webtoon.
    m : Passer en mode Manga.
    +/- : Zoomer/dézoomer (en mode Webtoon).
    PageUp/PageDown : Naviguer dans les pages (Webtoon/Manga).
    Home/End : Aller au début/fin du chapitre.
    q : Quitter le lecteur.

Capture d'écran du lecteur Webtoon
Ajoutez ici une capture d'écran du mode Webtoon.

Capture d'écran du lecteur Manga
Ajoutez ici une capture d'écran du mode Manga.
3. Télécharger des chapitres

L'application permet de télécharger des chapitres depuis mangas-origines.fr et anime-sama.fr pour une lecture locale. Les chapitres sont enregistrés sous forme de fichiers CBR dans votre répertoire de mangas.

Pour télécharger :

    Dans l'interface TUI, appuyez sur d pour entrer en mode téléchargement.
    Saisissez l'URL du manga (ex. https://mangas-origines.fr/oeuvre/nom-du-manga/chapitre-1 ou https://anime-sama.fr/catalogue/nom-du-manga/scan/vf/).
    Appuyez sur Tab pour passer au champ des chapitres.
    Entrez les numéros de chapitres (ex. 1-3,5 pour les chapitres 1, 2, 3 et 5).
    Appuyez sur Enter pour lancer le téléchargement via webtoon-dl.py.

Exemple de commande manuelle (alternative) :
bash
python3 webtoon-dl.py "https://mangas-origines.fr/oeuvre/nom-du-manga/chapitre-1" "1-3,5" -o ~/Documents/Scan

    Les chapitres sont sauvegardés dans ~/Documents/Scan/nom_du_manga/Chaptitre_XXX.cbr.
    La couverture (cover.jpg) et le synopsis (synopsis.txt) sont également téléchargés dans le dossier du manga.

Note : Les téléchargements sont destinés à un usage personnel et à la lecture locale. Respectez les droits d'auteur et les conditions d'utilisation des sites.

Capture d'écran du mode téléchargement
Ajoutez ici une capture d'écran du mode téléchargement dans la TUI.
Structure du projet

    app.rs : Interface principale en Rust (TUI) pour parcourir les mangas, gérer les chapitres et lancer les téléchargements.
    manga-live.py : Visualiseur de chapitres basé sur Pygame, avec support des modes Webtoon et Manga.
    webtoon-dl.py : Script de téléchargement pour récupérer les chapitres, couvertures et synopsis depuis mangas-origines.fr et anime-sama.fr.
    install.sh : Script d'installation pour configurer les dépendances et compiler l'application.
    ~/.config/manga_reader/config.json : Fichier de configuration pour stocker le dernier répertoire, les chapitres lus et les paramètres.

Configuration
Fichier de configuration

L'application crée automatiquement un fichier de configuration à ~/.config/manga_reader/config.json. Exemple de contenu :
json
{
  "last_manga_dir": "/home/user/Mangas",
  "read_chapters": [],
  "open_command": null,
  "settings": {
    "prefer_external": false,
    "auto_mark_read": true,
    "default_provider": "manual",
    "enable_image_rendering": true
  },
  "last_download_url": null,
  "last_downloaded_chapters": []
}

    last_manga_dir : Chemin par défaut pour charger vos mangas.
    read_chapters : Liste des chapitres marqués comme lus.
    last_download_url : Dernière URL utilisée pour le téléchargement.

Pour modifier le répertoire par défaut, éditez last_manga_dir ou passez un nouveau chemin lors du lancement de l'application.
Répertoire des mangas

Organisez vos mangas dans un répertoire comme suit :
text
/home/user/Mangas/
├── Nom_du_Manga_1/
│   ├── cover.jpg
│   ├── synopsis.txt
│   ├── Chapitre_001.cbr
│   ├── Chapitre_002.cbr
├── Nom_du_Manga_2/
│   ├── cover.jpg
│   ├── synopsis.txt
│   ├── Chapitre_001.pdf

    Les dossiers doivent contenir des fichiers CBR, CBZ ou PDF.
    Les fichiers cover.jpg et synopsis.txt sont automatiquement ajoutés lors du téléchargement.

Dépannage

    L'interface TUI ne charge pas les mangas :
        Vérifiez que last_manga_dir dans config.json pointe vers un répertoire valide.
        Assurez-vous que le répertoire contient des fichiers CBR/CBZ/PDF.
        Exécutez avec RUST_LOG=debug ./target/release/manga-reader /chemin/vers/mangas pour voir les logs.
    La liste des chapitres est vide :
        Vérifiez que selected_manga est défini (logs dans refresh_manga_list).
        Assurez-vous que cached_chapter_items est mis à jour dans ui.rs (voir logs dans draw_browse).
    Erreur lors du téléchargement :
        Vérifiez que l'URL est correcte et que le site est accessible.
        Assurez-vous que cloudscraper et ses dépendances sont installées (pip install -r requirements.txt).
        Consultez les logs dans la TUI ou en exécutant python3 webtoon-dl.py manuellement.
    Le lecteur Pygame ne s'ouvre pas :
        Vérifiez que unrar et poppler-utils sont installés (sudo apt install unrar poppler-utils).
        Assurez-vous que le fichier CBR/CBZ/PDF est valide.

Contribution

Les contributions sont les bienvenues ! Pour contribuer :

    Forkez le dépôt.
    Créez une branche pour vos modifications (git checkout -b feature/nouvelle-fonction).
    Committez vos changements (git commit -m "Ajout de la fonctionnalité X").
    Poussez vers votre fork (git push origin feature/nouvelle-fonction).
    Ouvrez une Pull Request.

Licence

Ce projet est distribué sous la licence MIT. Voir le fichier LICENSE pour plus de détails.
Crédits

Développé par Wax-dred. Inspiré par la passion pour les mangas et les webtoons !