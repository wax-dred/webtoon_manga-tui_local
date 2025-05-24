use std::path::PathBuf;
use crossbeam_channel::{bounded, Receiver};
use std::thread;
use std::process::{Command, Stdio};
use std::io::{BufRead, BufReader};

use anyhow::{Result};
use crossterm::event::{KeyCode, KeyEvent, Event, MouseEventKind};
use log::{debug, error};

use crate::config::Config;
use crate::image::ImageManager;
use crate::manga::Manga;
use crate::theme::Theme;
use ratatui_image::picker::Picker;
use ratatui_image::protocol::StatefulProtocol;

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum InputField {
    Url,
    Chapters,
    MangaDir,
    None,
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum AppState {
    BrowseManga,
    ViewMangaDetails,
    Settings,
    DownloadInput,
    Downloading,
}

pub struct App {
    pub state: AppState,
    pub manga_dir: PathBuf,
    pub theme: Theme,
    pub config: Config,
    pub mangas: Vec<Manga>,
    pub selected_manga: Option<usize>,
    pub selected_chapter: Option<usize>,
    pub current_page: usize,
    pub status: String,
    pub term_width: u16,
    pub term_height: u16,
    pub show_help: bool,
    pub filter: String,
    pub input_mode: bool,
    pub image_manager: ImageManager,
    pub is_manga_list_focused: bool,
    pub image_picker: Picker,
    pub image_state: Option<Box<dyn StatefulProtocol>>,
    pub download_url: String,
    pub selected_chapters_input: String,
    pub input_field: InputField,
    pub download_logs: Vec<String>,
    pub is_downloading: bool,
    pub download_log_receiver: Option<Receiver<String>>,
    pub scroll_offset: u16,
    pub download_finished: bool, // Nouveau champ
    pub has_user_scrolled: bool,
}

impl App {
    pub fn new(manga_dir: PathBuf, theme: Theme) -> Result<Self> {
        debug!("Creating new app with manga_dir: {:?}", manga_dir);
        
        let mut config = Config::load()?;
        config.settings.enable_image_rendering = true;

        let mut image_picker = Picker::from_termios()
            .map_err(|e| anyhow::anyhow!("Failed to initialize Picker: {}", e))?;
        image_picker.guess_protocol();

        let download_url = config.last_download_url.clone().unwrap_or_default();
        let selected_chapters_input = config
            .last_downloaded_chapters
            .iter()
            .map(|c| c.to_string())
            .collect::<Vec<String>>()
            .join(",");

        let mut app = Self {
            state: AppState::BrowseManga,
            manga_dir,
            theme,
            config,
            mangas: Vec::new(),
            selected_manga: None,
            selected_chapter: None,
            current_page: 0,
            status: String::new(),
            term_width: 120,
            term_height: 30,
            show_help: false,
            filter: String::new(),
            input_mode: false,
            image_manager: ImageManager::new(),
            is_manga_list_focused: true,
            image_picker,
            image_state: None,
            download_url,
            selected_chapters_input,
            input_field: InputField::None,
            download_logs: Vec::new(),
            is_downloading: false,
            download_log_receiver: None,
            scroll_offset: 0,
            download_finished: false,
            has_user_scrolled: false,
        };
        
        app.refresh_manga_list()?;
        
        Ok(app)
    }

    pub fn refresh_manga_list(&mut self) -> Result<()> {
        debug!("Refreshing manga list from {:?}", self.manga_dir);
        self.mangas = Manga::scan_directory(&self.manga_dir, &self.config)?;
        self.selected_manga = if self.mangas.is_empty() { None } else { Some(0) };
        self.selected_chapter = None;
        self.load_cover_image()?;
        Ok(())
    }

    pub fn current_manga(&self) -> Option<&Manga> {
        self.selected_manga
            .and_then(|idx| self.mangas.get(idx))
    }

    pub fn current_chapter(&self) -> Option<&crate::manga::Chapter> {
        if let Some(manga) = self.current_manga() {
            self.selected_chapter
                .and_then(|idx| manga.chapters.get(idx))
        } else {
            None
        }
    }

    pub fn mark_current_chapter_as_read(&mut self) -> Result<()> {
        let chapter_path = self.current_chapter().map(|chapter| chapter.path.clone());
        if let Some(path) = chapter_path {
            debug!("Marking chapter as read: {:?}", path);
            self.config.mark_chapter_as_read(&path)?;
            if let (Some(manga_idx), Some(chapter_idx)) = (self.selected_manga, self.selected_chapter) {
                if let Some(manga) = self.mangas.get_mut(manga_idx) {
                    if let Some(chapter) = manga.chapters.get_mut(chapter_idx) {
                        chapter.read = true;
                    }
                }
            }
        }
        Ok(())
    }

    pub fn filtered_mangas(&self) -> Vec<&Manga> {
        if self.filter.is_empty() {
            self.mangas.iter().collect()
        } else {
            self.mangas
                .iter()
                .filter(|manga| {
                    manga.name.to_lowercase().contains(&self.filter.to_lowercase())
                })
                .collect()
        }
    }

    pub fn load_cover_image(&mut self) -> Result<()> {
        let thumbnail_path = self
            .selected_manga
            .and_then(|idx| self.mangas.get(idx))
            .and_then(|manga| manga.thumbnail.as_ref());
        
        self.image_manager.load_cover_image(thumbnail_path)?;
        
        if let Some(dyn_img) = &self.image_manager.image {
            self.image_state = Some(self.image_picker.new_resize_protocol(dyn_img.clone()));
        } else {
            self.image_state = None;
        }
        
        Ok(())
    }

    pub fn manga_progress(&self, manga: &Manga) -> (usize, usize, f32) {
        let total = manga.chapters.len();
        let read = manga.chapters.iter().filter(|ch| ch.read).count();
        let progress = if total > 0 {
            read as f32 / total as f32
        } else {
            0.0
        };
        (read, total, progress)
    }

    pub fn open_external(&mut self) -> Result<()> {
        let (chapter_path, chapter_title) = match self.current_chapter() {
            Some(chapter) => (chapter.path.clone(), chapter.title.clone()),
            None => return Err(anyhow::anyhow!("No chapter selected")),
        };
        
        debug!("Opening chapter with external reader: {:?}", chapter_path);
        
        let command = self
            .config
            .open_command
            .clone()
            .unwrap_or_else(|| {
                if cfg!(target_os = "windows") {
                    "start".to_string()
                } else if cfg!(target_os = "macos") {
                    "open".to_string()
                } else {
                    "xdg-open".to_string()
                }
            });
        
        let home_dir = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        let hypr_script_path = format!("{}/.config/hypr/scripts/mupdf-launcher.sh", home_dir);
        
        let command_result = if cfg!(target_os = "linux") {
            if std::path::Path::new(&hypr_script_path).exists() {
                debug!("Using user's hypr script: {}", hypr_script_path);
                Command::new("manga-live")
                    .arg(&chapter_path)
                    .stdout(Stdio::null()) // Rediriger stdout vers /dev/null
                    .stderr(Stdio::null()) // Rediriger stderr vers /dev/null
                    .spawn() // Lancer sans attendre
            } else if std::path::Path::new("mupdf-launcher.sh").exists() {
                debug!("Using local mupdf-launcher.sh script");
                Command::new("sh")
                    .arg("mupdf-launcher.sh")
                    .arg(&chapter_path)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
            } else {
                debug!("Using standard command");
                Command::new(command)
                    .arg(&chapter_path)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
            }
        } else {
            debug!("Using standard command");
            Command::new(command)
                .arg(&chapter_path)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
        };
        
        match command_result {
            Ok(_) => {
                debug!("Command launched successfully");
                // Marquer le chapitre comme lu si auto_mark_read est activé
                if self.config.settings.auto_mark_read {
                    self.mark_current_chapter_as_read()?;
                }
                self.status = format!("Opened {} with external reader", chapter_title);
                Ok(())
            }
            Err(e) => {
                error!("Failed to execute command: {}", e);
                self.status = format!("Failed to open {}: {}", chapter_title, e);
                Err(anyhow::anyhow!("Failed to execute external reader: {}", e))
            }
        }
    }

    pub fn launch_webtoon_downloader(&mut self) -> Result<()> {
        debug!("Attempting to launch webtoon-dl with URL: {}", self.download_url);
        let output_dir = self.manga_dir.to_string_lossy().to_string();
        
        if self.download_url.is_empty() {
            self.status = "Error: URL is required".to_string();
            return Err(anyhow::anyhow!("URL is required"));
        }
    
        let chapters_arg = if self.selected_chapters_input.is_empty() {
            "1".to_string()
        } else {
            self.selected_chapters_input.clone()
        };
    
        self.config.last_download_url = Some(self.download_url.clone());
        self.config.last_downloaded_chapters = self
            .selected_chapters_input
            .split(',')
            .filter_map(|s| s.trim().parse::<u32>().ok())
            .collect();
        self.config.save()?;
    
        let (tx, rx) = bounded(100);
        self.download_log_receiver = Some(rx);
        self.download_logs.clear();
        self.is_downloading = true;
        self.download_finished = false;
        self.has_user_scrolled = false;
        self.state = AppState::Downloading;
    
        let url = self.download_url.clone();
        let chapters = chapters_arg.clone();
        let output_dir_clone = output_dir.clone();
    
        thread::spawn(move || {
            let result = Command::new("webtoon-dl")
                .arg(&url)
                .arg(&chapters)
                .arg("--output-dir")
                .arg(&output_dir_clone)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn();
    
            match result {
                Ok(mut child) => {
                    if let Some(stdout) = child.stdout.take() {
                        let reader = BufReader::new(stdout);
                        for line in reader.lines() {
                            if let Ok(line) = line {
                                let _ = tx.send(line);
                            }
                        }
                    }
                    if let Some(stderr) = child.stderr.take() {
                        let reader = BufReader::new(stderr);
                        for line in reader.lines() {
                            if let Ok(line) = line {
                                let _ = tx.send(line);
                            }
                        }
                    }
                    match child.wait() {
                        Ok(status) => {
                            let _ = tx.send(format!("Process finished with status: {}", status));
                        }
                        Err(e) => {
                            let _ = tx.send(format!("Error waiting for process: {}", e));
                        }
                    }
                }
                Err(e) => {
                    let _ = tx.send(format!("Failed to launch webtoon-dl: {}", e));
                }
            }
        });
    
        self.status = "Download started. Showing logs below...".to_string();
        Ok(())
    }

    pub fn on_resize(&mut self, width: u16, height: u16) {
        self.term_width = width;
        self.term_height = height;
        debug!("Terminal resized to width={}, height={}", width, height);
        if let Err(e) = self.load_cover_image() {
            debug!("Failed to reload cover image on resize: {}", e);
            self.status = format!("Error reloading image: {}", e);
        }
    }

    pub fn tick(&mut self) {
    if self.is_downloading {
        // Collect all available logs first
        let mut new_logs = Vec::new();
        if let Some(receiver) = &self.download_log_receiver {
            while let Ok(log) = receiver.try_recv() {
                let clean_log = strip_ansi_escapes(&log);
                new_logs.push(clean_log.clone());
                debug!("Received log: {}", clean_log); // Vérifie que les logs sont reçus
            }
        }

        // Ajouter les nouveaux logs immédiatement
        if !new_logs.is_empty() {
            self.download_logs.extend(new_logs.iter().cloned());
            debug!("Added {} new logs to download_logs. Total: {}", new_logs.len(), self.download_logs.len()); // Débogage
        }

        // Vérifier la fin du téléchargement
        if new_logs.iter().any(|log| log.contains("Download Complete!")) {
            self.is_downloading = false;
            self.download_finished = true;
            self.download_log_receiver = None;
            self.status = format!(
                "Download {} terminé. Press 'r' to refresh manga list, or continue viewing logs.",
                self.current_manga().map_or("unknown", |m| &m.name)
            );
        }
    }
    self.current_page = (self.current_page + 1) % 10; // Incrémente pour l'indicateur
}

    pub fn handle_key(&mut self, event: crossterm::event::Event) -> Result<bool> {
        match self.state {
            AppState::BrowseManga => Ok(self.handle_browse_input(event)),
            AppState::ViewMangaDetails => match event {
                Event::Key(key) => Ok(self.handle_details_input(key)),
                Event::Mouse(mouse) => match mouse.kind {
                    MouseEventKind::ScrollUp => {
                        if let Some(manga) = self.current_manga() {
                            if !manga.chapters.is_empty() {
                                self.selected_chapter = Some(match self.selected_chapter {
                                    Some(i) => if i == 0 { manga.chapters.len() - 1 } else { i - 1 },
                                    None => 0,
                                });
                            }
                        }
                        Ok(false)
                    }
                    MouseEventKind::ScrollDown => {
                        if let Some(manga) = self.current_manga() {
                            if !manga.chapters.is_empty() {
                                self.selected_chapter = Some(match self.selected_chapter {
                                    Some(i) => (i + 1) % manga.chapters.len(),
                                    None => 0,
                                });
                            }
                        }
                        Ok(false)
                    }
                    _ => Ok(false),
                },
                _ => Ok(false),
            },
            AppState::DownloadInput => if let Event::Key(key) = event {
                Ok(self.handle_download_input(key))
            } else {
                Ok(false)
            },
            AppState::Downloading => if let Event::Key(key) = event {
                Ok(self.handle_downloading_input(key))
            } else {
                Ok(false)
            },
            AppState::Settings => if let Event::Key(key) = event {
                Ok(self.handle_settings_input(key))
            } else {
                Ok(false)
            },
        }
    }

    fn handle_browse_input(&mut self, event: Event) -> bool {
        if self.input_mode && self.input_field != InputField::MangaDir {
            if let Event::Key(key) = event {
                match key.code {
                    KeyCode::Esc => {
                        self.input_mode = false;
                        self.filter.clear();
                        self.input_field = InputField::None;
                        self.status = "Filter cleared".to_string();
                        return false;
                    }
                    KeyCode::Enter => {
                        self.input_mode = false;
                        self.status = "Filter applied".to_string();
                        return false;
                    }
                    KeyCode::Char(c) => {
                        self.filter.push(c);
                        return false;
                    }
                    KeyCode::Backspace => {
                        self.filter.pop();
                        return false;
                    }
                    _ => return false,
                }
            } else {
                return false;
            }
        }

        debug!("Event received: {:?}", event);
        debug!("Focus: {}", if self.is_manga_list_focused { "Manga List" } else { "Chapter List" });

        match event {
            Event::Key(key) => match key.code {
                KeyCode::Char('q') => return true,
                KeyCode::Char('?') => {
                    self.show_help = !self.show_help;
                    self.status = if self.show_help { "Help displayed".to_string() } else { "Help hidden".to_string() };
                    return false;
                }
                KeyCode::Char('r') => {
                    if let Ok(()) = self.refresh_manga_list() {
                        self.status = "Liste de mangas actualisée".to_string();
                    }
                    return false;
                }
                KeyCode::Char('c') => {
                    self.state = AppState::Settings;
                    self.input_mode = true;
                    self.input_field = InputField::MangaDir;
                    self.filter = self.manga_dir.to_string_lossy().to_string();
                    self.status = "Editing manga folder path (Enter to confirm)".to_string();
                    debug!("Entered settings: input_mode=true, input_field=MangaDir, filter={}", self.filter);
                    return false;
                }
                KeyCode::Char('d') => {
                    self.state = AppState::DownloadInput;
                    self.input_mode = true;
                    self.input_field = InputField::Url;
                    self.status = "Enter the URL, then press Tab to select chapters.".to_string();
                    return false;
                }
                KeyCode::Char('/') => {
                    self.input_mode = true;
                    self.input_field = InputField::None;
                    self.status = "Filtering manga list".to_string();
                    return false;
                }
                KeyCode::Tab => {
                    self.is_manga_list_focused = !self.is_manga_list_focused;
                    self.status = if self.is_manga_list_focused {
                        "Focus: Manga List".to_string()
                    } else {
                        "Focus: Chapter List".to_string()
                    };
                    debug!("Focus switched to: {}", self.status);
                    if !self.is_manga_list_focused {
                        if let Some(manga) = self.current_manga() {
                            let last_read_index = manga.chapters.iter().rposition(|c| c.read);
                            self.selected_chapter = match last_read_index {
                                Some(idx) => {
                                    if idx + 1 < manga.chapters.len() {
                                        Some(idx + 1)
                                    } else if idx > 0 {
                                        Some(idx - 1)
                                    } else {
                                        Some(0)
                                    }
                                }
                                None => Some(0),
                            };
                            debug!("Selected chapter: {:?}", self.selected_chapter);
                        }
                    }
                    return false;
                }
                KeyCode::Left => {
                    self.is_manga_list_focused = true;
                    self.status = "Focus: Manga List".to_string();
                    debug!("Focus set to Manga List");
                    return false;
                }
                KeyCode::Right => {
                    self.is_manga_list_focused = false;
                    self.status = "Focus: Chapter List".to_string();
                    debug!("Focus set to Chapter List");
                    if let Some(manga) = self.current_manga() {
                        let last_read_index = manga.chapters.iter().rposition(|c| c.read);
                        self.selected_chapter = match last_read_index {
                            Some(idx) => {
                                if idx + 1 < manga.chapters.len() {
                                    Some(idx + 1)
                                } else if idx > 0 {
                                    Some(idx - 1)
                                } else {
                                    Some(0)
                                }
                            }
                            None => Some(0),
                        };
                        debug!("Selected chapter: {:?}", self.selected_chapter);
                    }
                    return false;
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    if self.is_manga_list_focused {
                        let filtered = self.filtered_mangas();
                        if !filtered.is_empty() {
                            self.selected_manga = Some(match self.selected_manga {
                                Some(i) => if i == 0 { filtered.len() - 1 } else { i - 1 },
                                None => 0,
                            });
                            self.selected_chapter = if let Some(manga) = self.current_manga() {
                                if manga.chapters.is_empty() { None } else { Some(0) }
                            } else {
                                None
                            };
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga: {:?}", self.selected_manga);
                            }
                        }
                    } else if let Some(manga) = self.current_manga() {
                        if !manga.chapters.is_empty() {
                            self.selected_chapter = Some(match self.selected_chapter {
                                Some(i) => if i == 0 { manga.chapters.len() - 1 } else { i - 1 },
                                None => 0,
                            });
                            debug!("Selected chapter: {:?}", self.selected_chapter);
                        }
                    }
                    return false;
                }
                KeyCode::Down | KeyCode::Char('j') => {
                    if self.is_manga_list_focused {
                        let filtered = self.filtered_mangas();
                        if !filtered.is_empty() {
                            self.selected_manga = Some(match self.selected_manga {
                                Some(i) => (i + 1) % filtered.len(),
                                None => 0,
                            });
                            self.selected_chapter = if let Some(manga) = self.current_manga() {
                                if manga.chapters.is_empty() { None } else { Some(0) }
                            } else {
                                None
                            };
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga: {:?}", self.selected_manga);
                            }
                        }
                    } else if let Some(manga) = self.current_manga() {
                        if !manga.chapters.is_empty() {
                            self.selected_chapter = Some(match self.selected_chapter {
                                Some(i) => (i + 1) % manga.chapters.len(),
                                None => 0,
                            });
                            debug!("Selected chapter: {:?}", self.selected_chapter);
                        }
                    }
                    return false;
                }
                KeyCode::Enter | KeyCode::Char('o') => {
                    if !self.is_manga_list_focused {
                        if let Err(e) = self.open_external() {
                            self.status = format!("Erreur: {}", e);
                        } else {
                            self.status = "Chapter opened".to_string();
                        }
                    }
                    return false;
                }
                KeyCode::Char('v') => {
                    if self.is_manga_list_focused {
                        self.state = AppState::ViewMangaDetails;
                        self.status = "Viewing manga details".to_string();
                        debug!("Switched to ViewMangaDetails state");
                    }
                    return false;
                }
                KeyCode::Char('m') => {
                    if !self.is_manga_list_focused {
                        if let Some(chapter) = self.current_chapter() {
                            let is_read = chapter.read;
                            let path = chapter.path.clone();
                            if is_read {
                                if let Err(e) = self.config.mark_chapter_as_unread(&path) {
                                    self.status = format!("Erreur: {}", e);
                                } else if let (Some(manga_idx), Some(chapter_idx)) = (self.selected_manga, self.selected_chapter) {
                                    if let Some(manga) = self.mangas.get_mut(manga_idx) {
                                        if let Some(chapter) = manga.chapters.get_mut(chapter_idx) {
                                            chapter.read = false;
                                            self.status = "Chapitre marqué comme non lu".to_string();
                                        }
                                    }
                                }
                            } else {
                                if let Err(e) = self.mark_current_chapter_as_read() {
                                    self.status = format!("Erreur: {}", e);
                                } else {
                                    self.status = "Chapitre marqué comme lu".to_string();
                                }
                            }
                        }
                    }
                    return false;
                }
                _ => return false,
            },
            Event::Mouse(mouse_event) => match mouse_event.kind {
                MouseEventKind::ScrollUp => {
                    debug!("Mouse ScrollUp, is_manga_list_focused: {}", self.is_manga_list_focused);
                    if self.is_manga_list_focused {
                        let filtered_mangas = self.filtered_mangas();
                        if let Some(idx) = self.selected_manga {
                            let new_idx = if idx == 0 { filtered_mangas.len() - 1 } else { idx - 1 };
                            self.selected_manga = Some(new_idx);
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga after ScrollUp: {:?}", self.selected_manga);
                            }
                        } else if !filtered_mangas.is_empty() {
                            self.selected_manga = Some(0);
                        }
                    } else if let Some(manga) = self.current_manga() {
                        debug!("Current manga chapters: {}", manga.chapters.len());
                        if !manga.chapters.is_empty() {
                            self.selected_chapter = Some(match self.selected_chapter {
                                Some(i) => if i == 0 { manga.chapters.len() - 1 } else { i - 1 },
                                None => 0,
                            });
                            debug!("Selected chapter after ScrollUp: {:?}", self.selected_chapter);
                        }
                    }
                    return false;
                }
                MouseEventKind::ScrollDown => {
                    debug!("Mouse ScrollDown, is_manga_list_focused: {}", self.is_manga_list_focused);
                    if self.is_manga_list_focused {
                        let filtered_mangas = self.filtered_mangas();
                        if let Some(idx) = self.selected_manga {
                            let new_idx = (idx + 1) % filtered_mangas.len();
                            self.selected_manga = Some(new_idx);
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga after ScrollDown: {:?}", self.selected_manga);
                            }
                        } else if !filtered_mangas.is_empty() {
                            self.selected_manga = Some(0);
                        }
                    } else if let Some(manga) = self.current_manga() {
                        debug!("Current manga chapters: {}", manga.chapters.len());
                        if !manga.chapters.is_empty() {
                            self.selected_chapter = Some(match self.selected_chapter {
                                Some(i) => (i + 1) % manga.chapters.len(),
                                None => 0,
                            });
                            debug!("Selected chapter after ScrollDown: {:?}", self.selected_chapter);
                        }
                    }
                    return false;
                }
                _ => return false,
            },
            _ => return false,
        }
    }

    fn handle_details_input(&mut self, key: KeyEvent) -> bool {
        match key.code {
            KeyCode::Char('q') | KeyCode::Esc => {
                self.state = AppState::BrowseManga;
                self.status = "Returned to manga list".to_string();
                return false;
            }
            KeyCode::Up | KeyCode::Char('k') => {
                if let Some(manga) = self.current_manga() {
                    if !manga.chapters.is_empty() {
                        self.selected_chapter = Some(match self.selected_chapter {
                            Some(i) => if i == 0 { manga.chapters.len() - 1 } else { i - 1 },
                            None => 0,
                        });
                        debug!("Selected chapter in details: {:?}", self.selected_chapter);
                    }
                }
                return false;
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if let Some(manga) = self.current_manga() {
                    if !manga.chapters.is_empty() {
                        self.selected_chapter = Some(match self.selected_chapter {
                            Some(i) => (i + 1) % manga.chapters.len(),
                            None => 0,
                        });
                        debug!("Selected chapter in details: {:?}", self.selected_chapter);
                    }
                }
                return false;
            }
            KeyCode::Enter | KeyCode::Char('o') => {
                if let Err(e) = self.open_external() {
                    self.status = format!("Erreur: {}", e);
                }
                return false;
            }
            KeyCode::Char('m') => {
                let chapter_info = self.current_chapter().map(|chapter| (chapter.read, chapter.path.clone()));
                if let Some((is_read, path)) = chapter_info {
                    if is_read {
                        if let Err(e) = self.config.mark_chapter_as_unread(&path) {
                            self.status = format!("Erreur: {}", e);
                        } else if let (Some(manga_idx), Some(chapter_idx)) = (self.selected_manga, self.selected_chapter) {
                            if let Some(manga) = self.mangas.get_mut(manga_idx) {
                                if let Some(chapter) = manga.chapters.get_mut(chapter_idx) {
                                    chapter.read = false;
                                    self.status = "Chapitre marqué comme non lu".to_string();
                                }
                            }
                        }
                    } else {
                        if let Err(e) = self.mark_current_chapter_as_read() {
                            self.status = format!("Erreur: {}", e);
                        } else {
                            self.status = "Chapitre marqué comme lu".to_string();
                        }
                    }
                }
                return false;
            }
            KeyCode::Char('d') => {
                self.state = AppState::DownloadInput;
                self.input_mode = true;
                self.input_field = InputField::Url;
                self.status = "Enter the URL, then press Tab to select chapters.".to_string();
                return false;
            }
            _ => return false,
        }
    }
    
    fn handle_download_input(&mut self, key: KeyEvent) -> bool {
        match key.code {
            KeyCode::Esc => {
                self.state = AppState::BrowseManga;
                self.input_mode = false;
                self.input_field = InputField::None;
                self.status = "Returned to manga list".to_string();
                self.is_downloading = false;
                self.download_logs.clear();
                self.download_log_receiver = None;
                return false;
            }
            KeyCode::Tab => {
                self.input_field = match self.input_field {
                    InputField::Url => InputField::Chapters,
                    InputField::Chapters => InputField::Url,
                    InputField::MangaDir => InputField::Url,
                    InputField::None => InputField::Url,
                };
                self.status = match self.input_field {
                    InputField::Url => "Editing URL".to_string(),
                    InputField::Chapters => "Editing chapters (e.g., 1,2,3 or 1-3)".to_string(),
                    InputField::MangaDir => "Manga folder editing not allowed here".to_string(),
                    InputField::None => "No field selected".to_string(),
                };
                return false;
            }
            KeyCode::Enter => {
                if let Err(e) = self.launch_webtoon_downloader() {
                    self.status = format!("Error: {}", e);
                } else {
                    self.status = "Download started. Showing logs below...".to_string();
                }
                return false;
            }
            KeyCode::Char(c) => {
                if self.input_mode {
                    match self.input_field {
                        InputField::Url => {
                            self.download_url.push(c);
                        }
                        InputField::Chapters => {
                            self.selected_chapters_input.push(c);
                        }
                        InputField::MangaDir => {}
                        InputField::None => {}
                    }
                }
                return false;
            }
            KeyCode::Backspace => {
                if self.input_mode {
                    match self.input_field {
                        InputField::Url => {
                            self.download_url.pop();
                        }
                        InputField::Chapters => {
                            self.selected_chapters_input.pop();
                        }
                        InputField::MangaDir => {}
                        InputField::None => {}
                    }
                }
                return false;
            }
            _ => return false,
        }
    }

    fn handle_downloading_input(&mut self, key: KeyEvent) -> bool {
        match key.code {
            KeyCode::Esc => {
                self.is_downloading = false;
                self.download_finished = false;
                self.download_logs.push("Download cancelled.".to_string());
                self.download_log_receiver = None;
                self.state = AppState::BrowseManga;
                self.is_manga_list_focused = true; // Focus sur la première colonne
                self.status = "Download cancelled. Manga list refreshed and focused.".to_string();
                self.scroll_offset = 0;
                self.has_user_scrolled = false;
                let _ = self.refresh_manga_list();
                return false;
            }
            KeyCode::Char('r') => {
                self.is_downloading = false;
                self.download_finished = false;
                self.download_log_receiver = None;
                self.state = AppState::BrowseManga;
                self.is_manga_list_focused = true; // Focus sur la première colonne
                self.scroll_offset = 0;
                self.has_user_scrolled = false;
                let _ = self.refresh_manga_list();
                self.status = "Manga list refreshed.".to_string();
                return false;
            }
            KeyCode::Up | KeyCode::Char('k') => {
                self.scroll_offset = self.scroll_offset.saturating_sub(1);
                self.has_user_scrolled = true;
                return false;
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if self.scroll_offset < self.download_logs.len().saturating_sub(1) as u16 {
                    self.scroll_offset += 1;
                }
                self.has_user_scrolled = true;
                return false;
            }
            _ => return false,
        }
    }

    fn handle_settings_input(&mut self, key: KeyEvent) -> bool {
        match key.code {
            KeyCode::Esc => {
                self.state = AppState::BrowseManga;
                self.input_mode = false;
                self.input_field = InputField::None;
                self.status = "Liste des mangas".to_string();
                return false;
            }
            KeyCode::Enter => {
                if self.input_mode && self.input_field == InputField::MangaDir {
                    let new_path = PathBuf::from(&self.filter);
                    if new_path.exists() && new_path.is_dir() {
                        self.manga_dir = new_path.clone();
                        self.config.last_manga_dir = Some(new_path);
                        if let Ok(()) = self.config.save() {
                            if let Ok(()) = self.refresh_manga_list() {
                                self.state = AppState::BrowseManga;
                                self.input_mode = false;
                                self.input_field = InputField::None;
                                self.filter.clear();
                                self.status = "Manga folder updated".to_string();
                            }
                        }
                    } else {
                        if let Ok(()) = std::fs::create_dir_all(&new_path) {
                            self.manga_dir = new_path.clone();
                            self.config.last_manga_dir = Some(new_path);
                            if let Ok(()) = self.config.save() {
                                if let Ok(()) = self.refresh_manga_list() {
                                    self.state = AppState::BrowseManga;
                                    self.input_mode = false;
                                    self.input_field = InputField::None;
                                    self.filter.clear();
                                    self.status = "Manga folder created and updated".to_string();
                                }
                            }
                        } else {
                            self.status = "Error: Invalid or inaccessible path".to_string();
                        }
                    }
                }
                return false;
            }
            KeyCode::Char(c) => {
                if self.input_mode && self.input_field == InputField::MangaDir {
                    self.filter.push(c);
                }
                return false;
            }
            KeyCode::Backspace => {
                if self.input_mode && self.input_field == InputField::MangaDir {
                    self.filter.pop();
                }
                return false;
            }
            _ => return false,
        }
    }
}

fn strip_ansi_escapes(s: &str) -> String {
    s.chars().filter(|c| !c.is_control()).collect()
}