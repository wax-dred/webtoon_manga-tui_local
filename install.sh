#!/usr/bin/env bash

# Script d'installation pour manga-reader et webtoon-dl

set -e

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Début de l'installation ===${NC}"

# Vérifier et installer Rust/Cargo
echo -e "${YELLOW}Vérification de Rust et Cargo...${NC}"
if ! command -v cargo &> /dev/null; then
    echo -e "${GREEN}Installation de Rust et Cargo...${NC}"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
else
    echo -e "${GREEN}Cargo est déjà installé. $(cargo --version)${NC}"
fi

# Détecter la distribution
DISTRO=""
if [ -f /etc/arch-release ]; then
    DISTRO="arch"
elif [ -f /etc/debian_version ]; then
    DISTRO="debian"
elif [ -f /etc/fedora-release ]; then
    DISTRO="fedora"
elif [ -f /etc/centos-release ] || [ -f /etc/redhat-release ]; then
    DISTRO="rhel"
elif [ -f /etc/os-release ] && grep -q "ID=opensuse" /etc/os-release; then
    DISTRO="opensuse"
elif [ -f /etc/alpine-release ]; then
    DISTRO="alpine"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    DISTRO="macos"
else
    DISTRO="unknown"
fi
echo -e "${YELLOW}Distribution détectée : $DISTRO${NC}"

# Vérifier et installer Python 3
echo -e "${YELLOW}Vérification de Python 3...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${GREEN}Installation de Python 3...${NC}"
    case $DISTRO in
        arch)
            sudo pacman -S --noconfirm python
            ;;
        debian)
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip
            ;;
        fedora)
            sudo dnf install -y python3 python3-pip
            ;;
        rhel)
            sudo dnf install -y python3 python3-pip
            ;;
        opensuse)
            sudo zypper install -y python3 python3-pip
            ;;
        alpine)
            sudo apk add python3 py3-pip
            ;;
        macos)
            if ! command -v brew &> /dev/null; then
                echo -e "${RED}Homebrew requis sur macOS. Installez-le avec :${NC}"
                echo -e "${YELLOW}/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${NC}"
                exit 1
            fi
            brew install python3
            ;;
        *)
            echo -e "${RED}Distribution non supportée pour l'installation automatique de Python.${NC}"
            echo -e "${YELLOW}Veuillez installer Python 3 manuellement, puis relancez le script.${NC}"
            exit 1
            ;;
    esac
else
    echo -e "${GREEN}Python 3 est déjà installé. $(python3 --version)${NC}"
fi

# Installer les dépendances système pour manga-reader
echo -e "${YELLOW}Installation des dépendances système...${NC}"
case $DISTRO in
    arch)
        sudo pacman -S --noconfirm libx11
        ;;
    debian)
        sudo apt-get install -y libx11-dev
        ;;
    fedora)
        sudo dnf install -y libX11-devel
        ;;
    rhel)
        sudo dnf install -y libX11-devel
        ;;
    opensuse)
        sudo zypper install -y libX11-devel
        ;;
    alpine)
        sudo apk add libx11-dev
        ;;
    macos)
        # XQuartz pour X11 sur macOS (optionnel, peut être requis pour ratatui-image)
        if ! command -v brew &> /dev/null; then
            echo -e "${YELLOW}Homebrew requis pour installer XQuartz. Installez-le d'abord.${NC}"
        else
            brew install --cask xquartz
        fi
        ;;
    *)
        echo -e "${YELLOW}Dépendances système non installées automatiquement. Assurez-vous que libX11 est installé si nécessaire.${NC}"
        ;;
esac

# Fonction pour installer les dépendances Python
install_python_deps() {
    if [ "$DISTRO" = "arch" ]; then
        echo -e "${YELLOW}Détection d'Arch Linux, vérification de paru...${NC}"
        if ! command -v paru &> /dev/null; then
            echo -e "${GREEN}Installation de paru...${NC}"
            sudo pacman -S --noconfirm base-devel git
            git clone https://aur.archlinux.org/paru.git /tmp/paru
            cd /tmp/paru
            makepkg -si --noconfirm
            cd -
        else
            echo -e "${GREEN}paru est déjà installé.${NC}"
        fi

        echo -e "${YELLOW}Installation des dépendances Python avec paru...${NC}"
        paru -S --noconfirm python-rich python-requests python-beautifulsoup4 python-cloudscraper python-pillow python-pygame python-pdf2image python-rarfile
    else
        echo -e "${YELLOW}Installation des dépendances Python avec pip...${NC}"
        # Essayer pipx comme fallback si pip échoue
        if ! pip3 install rich requests beautifulsoup4 cloudscraper pillow pygame pdf2image rarfile --user; then
            echo -e "${YELLOW}Échec de pip, tentative avec pipx...${NC}"
            if ! command -v pipx &> /dev/null; then
                echo -e "${YELLOW}Installation de pipx...${NC}"
                case $DISTRO in
                    arch)
                        sudo pacman -S --noconfirm python-pipx
                        ;;
                    debian)
                        sudo apt-get install -y pipx
                        ;;
                    fedora)
                        sudo dnf install -y pipx
                        ;;
                    rhel)
                        sudo dnf install -y pipx
                        ;;
                    opensuse)
                        sudo zypper install -y python3-pipx
                        ;;
                    alpine)
                        sudo apk add py3-pipx
                        ;;
                    macos)
                        brew install pipx
                        ;;
                    *)
                        echo -e "${RED}pipx non supporté. Installez les dépendances manuellement.${NC}"
                        exit 1
                        ;;
                esac
            fi
            pipx install rich
            pipx install requests
            pipx install beautifulsoup4
            pipx install cloudscraper
            pipx install pillow
            pipx install pygame
            pipx install pdf2image
            pipx install rarfile
        fi
    fi
}

# Installer les dépendances Python
install_python_deps

# Configurer webtoon-dl comme une commande exécutable
echo -e "${YELLOW}Configuration de webtoon-dl...${NC}"
if [ -f "webtoon-dl.py" ]; then
    chmod +x webtoon-dl.py
    cp -r webtoon-dl.py webtoon-dl
    # Déplacer vers un dossier dans $PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo -e "${YELLOW}Ajout de ~/.local/bin au PATH...${NC}"
        # Supporter zsh et bash
        if [ -n "$ZSH_VERSION" ]; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
        else
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
        fi
        export PATH="$HOME/.local/bin:$PATH"
    fi
    mkdir -p ~/.local/bin
    mv webtoon-dl ~/.local/bin/
    echo -e "${GREEN}webtoon-dl installé comme commande exécutable.${NC}"
else
    echo -e "${RED}Erreur : webtoon-dl.py non trouvé.${NC}"
    exit 1
fi

# Configurer manga-live comme une commande exécutable
echo -e "${YELLOW}Configuration de manga-live...${NC}"
if [ -f "manga-live.py" ]; then
    chmod +x manga-live.py
    cp -r manga-live.py manga-live
    # Déplacer vers un dossier dans $PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo -e "${YELLOW}Ajout de ~/.local/bin au PATH...${NC}"
        # Supporter zsh et bash
        if [ -n "$ZSH_VERSION" ]; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
        else
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
        fi
        export PATH="$HOME/.local/bin:$PATH"
    fi
    mkdir -p ~/.local/bin
    mv manga-live ~/.local/bin/
    echo -e "${GREEN}manga-live installé comme commande exécutable.${NC}"
else
    echo -e "${RED}Erreur : manga-live.py non trouvé.${NC}"
    exit 1
fi

# Compiler le programme Rust
echo -e "${YELLOW}Compilation du programme Rust...${NC}"
cargo build
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Compilation réussie ! L'exécutable est dans target/release/manga-reader${NC}"
else
    echo -e "${RED}Erreur lors de la compilation.${NC}"
    exit 1
fi

# Copier l'exécutable manga-reader vers ~/.local/bin/
echo -e "${YELLOW}Installation de manga-reader comme commande globale...${NC}"
if [ -f "target/debug/manga-reader" ]; then
    cp target/debug/manga-reader ~/.local/bin/
    chmod +x ~/.local/bin/manga-reader
    echo -e "${GREEN}manga-reader installé comme commande globale dans ~/.local/bin/${NC}"
else
    echo -e "${RED}Erreur : l'exécutable manga-reader n'a pas été trouvé dans target/debug/${NC}"
    exit 1
fi

echo -e "${YELLOW}=== Installation terminée ===${NC}"
echo -e "${GREEN}Vous pouvez maintenant exécuter 'webtoon-dl' et 'manga-reader' depuis n'importe quel terminal${NC}"