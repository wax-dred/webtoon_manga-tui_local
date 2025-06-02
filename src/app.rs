use std::path::PathBuf;
use crossbeam_channel::{bounded, Receiver};
use std::thread;
use std::process::{Command, Stdio};
use std::io::{BufRead, BufReader};
use std::collections::HashMap; // Added import
use image::DynamicImage; // Added import
use anyhow::{Result};
use crossterm::event::{KeyCode, KeyEvent, MouseEventKind};
use log::{debug, error};
use std::time::{Duration, Instant};
use crate::config::Config;
use crate::image::ImageManager;
use crate::manga::Manga;
use crate::theme::Theme;
use ratatui_image::picker::Picker;
use ratatui_image::protocol::StatefulProtocol;
use crate::event::Event;

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
    pub download_finished: bool,
    pub has_user_scrolled: bool,
    pub current_download_manga_name: String,
    pub needs_refresh: bool,
    pub refresh_trigger: Option<Receiver<()>>,
    pub last_log_count: usize,
    pub last_download_complete: bool,
    pub should_quit: bool,
    pub last_mouse_scroll: Instant,
    pub image_cache: HashMap<PathBuf, (u32, u32, DynamicImage)>,
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
            current_download_manga_name: String::new(),
            needs_refresh: false,
            refresh_trigger: None,
            last_log_count: 0,
            last_download_complete: false,
            should_quit: false,
            last_mouse_scroll: Instant::now().checked_sub(Duration::from_millis(120)).unwrap_or_else(Instant::now),
            image_cache: HashMap::new(),
        };
        
        app.refresh_manga_list()?;
        
        Ok(app)
    }
    
    pub fn load_cover_image(&mut self) -> Result<()> {
        let thumbnail_path = self
            .selected_manga
            .and_then(|idx| self.mangas.get(idx))
            .and_then(|manga| manga.thumbnail.as_ref());

        self.image_manager.clear();

        if let Some(path) = thumbnail_path {
            if let Some(cached) = self.image_cache.get(path) {
                self.image_manager.image_info = Some(cached.clone());
            } else {
                if let Ok((width, height, img)) = crate::util::load_image_info(path) {
                    self.image_cache.insert(path.to_path_buf(), (width, height, img.clone()));
                    self.image_manager.image_info = Some((width, height, img));
                }
            }
        }

        if let Some((_, _, dyn_img)) = &self.image_manager.image_info {
            self.image_state = Some(self.image_picker.new_resize_protocol(dyn_img.clone()));
        } else {
            self.image_state = None;
        }

        Ok(())
    }

    pub fn refresh_manga_list(&mut self) -> Result<()> {
        debug!("Refreshing manga list from {:?}", self.manga_dir);
        
        let previous_selected_manga = self.selected_manga;
        let previous_selected_manga_name = previous_selected_manga
            .and_then(|idx| self.mangas.get(idx))
            .map(|manga| manga.name.clone());
    
        self.mangas = Manga::scan_directory(&self.manga_dir, &self.config)?;
        
        if let Some(manga_name) = previous_selected_manga_name {
            self.selected_manga = self.mangas.iter().position(|m| m.name == manga_name);
        } else {
            self.selected_manga = if self.mangas.is_empty() { None } else { Some(0) };
        }
    
        if let Some(manga_idx) = self.selected_manga {
            if let Some(manga) = self.mangas.get(manga_idx) {
                let last_unread = manga.chapters.iter().position(|c| !c.read);
                self.selected_chapter = match last_unread {
                    Some(idx) => Some(idx),
                    None => Some(0),
                };
                debug!("Restored selected_manga: {:?}, selected_chapter: {:?}", self.selected_manga, self.selected_chapter);
            } else {
                self.selected_chapter = None;
            }
        } else {
            self.selected_chapter = None;
        }
    
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

    pub fn toggle_chapter_read_state(&mut self, read: bool) -> Result<()> {
        if let Some(chapter) = self.current_chapter() {
            let path = chapter.path.clone();
            let manga_name = self.current_manga().map(|m| m.name.clone()).unwrap_or_default();
            if read {
                self.config.mark_chapter_as_read(&path)?;
            } else {
                self.config.mark_chapter_as_unread(&path)?;
            }
            if let (Some(manga_idx), Some(chapter_idx)) = (self.selected_manga, self.selected_chapter) {
                if let Some(manga) = self.mangas.get_mut(manga_idx) {
                    if let Some(chapter) = manga.chapters.get_mut(chapter_idx) {
                        chapter.read = read;
                        let last_page = chapter.last_page_read.unwrap_or(0);
                        let total_pages = chapter.full_pages_read.unwrap_or(20);
                        chapter.update_progress(&manga_name, last_page, total_pages, read)?;
                        self.status = if read {
                            "Chapitre marqué comme lu".to_string()
                        } else {
                            "Chapitre marqué comme non lu".to_string()
                        };
                    }
                }
            }
        }
        Ok(())
    }

    pub fn filtered_mangas(&self) -> Box<dyn Iterator<Item = &Manga> + '_> {
        if self.filter.is_empty() {
            Box::new(self.mangas.iter())
        } else {
            Box::new(self.mangas.iter().filter(move |manga| {
                manga.name.to_lowercase().contains(&self.filter.to_lowercase())
            }))
        }
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
        let (chapter_path, chapter_title, last_page) = match self.current_chapter() {
            Some(chapter) => (
                chapter.path.clone(),
                chapter.title.clone(),
                chapter.last_page_read,
            ),
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
        
        let (tx, rx) = bounded(1);
        self.refresh_trigger = Some(rx);
        
        let command_result = if cfg!(target_os = "linux") {
            let home_dir = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
            let hypr_script_path = format!("{}/.config/hypr/scripts/mupdf-launcher.sh", home_dir);
            
            if std::path::Path::new(&hypr_script_path).exists() {
                debug!("Using user's hypr script: {}", hypr_script_path);
                let mut cmd = Command::new("manga-live");
                cmd.arg(&chapter_path);
                if last_page.is_none() {
                    cmd.arg("--page").arg("0");
                } else if let Some(page) = last_page {
                    cmd.arg("--page").arg(page.to_string());
                    debug!("Passing --page {} to manga-live", page);
                }
                cmd.stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
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
                let mut cmd = Command::new(&command);
                cmd.arg(&chapter_path);
                if command == "manga-live" {
                    if last_page.is_none() {
                        cmd.arg("--page").arg("0");
                    } else if let Some(page) = last_page {
                        cmd.arg("--page").arg(page.to_string());
                    }
                }
                cmd.stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
            }
        } else {
            debug!("Using standard command");
            let mut cmd = Command::new(&command);
            cmd.arg(&chapter_path)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
        };
        
        match command_result {
            Ok(mut child) => {
                debug!("Command spawned successfully.");
                
                thread::spawn(move || {
                    match child.wait() {
                        Ok(status) => {
                            debug!("External reader closed with status: {}", status);
                            let _ = tx.send(());
                        }
                        Err(e) => {
                            error!("Error waiting for external reader: {}", e);
                            let _ = tx.send(());
                        }
                    }
                });
                
                if let (Some(manga_idx), Some(chapter_idx)) = (self.selected_manga, self.selected_chapter) {
                    if let Some(manga) = self.mangas.get_mut(manga_idx) {
                        if let Some(chapter) = manga.chapters.get_mut(chapter_idx) {
                            if chapter.last_page_read.is_none() {
                                chapter.last_page_read = Some(0);
                                debug!("Initialized last_page_read to 0 for chapter {:?}", chapter_path);
                            }
                            self.status = format!("Opened {} with external reader", chapter_title);
                        }
                        manga.reload_progress();
                        
                        let next_unread = manga.chapters.iter().skip(chapter_idx + 1).position(|c| !c.read);
                        self.selected_chapter = match next_unread {
                            Some(offset) => Some(chapter_idx + 1 + offset),
                            None => {
                                let last_read = manga.chapters.iter().rposition(|c| c.read);
                                last_read.or(Some(0))
                            }
                        };
                        debug!("Updated selected_chapter after opening: {:?}", self.selected_chapter);
                        
                        self.needs_refresh = true;
                    }
                }
                Ok(())
            }
            Err(e) => {
                error!("Failed to execute command: {}", e);
                self.status = format!("Failed to open {}: {}", chapter_title, e);
                self.refresh_trigger = None;
                Err(anyhow::anyhow!("Failed to execute external reader: {}", e))
            }
        }
    }
    
    pub fn reset_refresh(&mut self) {
        self.needs_refresh = false;
    }
    
    pub fn calculate_download_progress(&self) -> (usize, usize, f32, usize, usize, usize) {
        let mut total_chapters = 1;
        let mut completed_chapters = 0;
        let mut current_chapter_images = 0;
        let mut total_images_in_current_chapter = 1;
        let mut current_chapter = 1;
        let mut last_detected_chapter = 0;

        if !self.selected_chapters_input.is_empty() {
            let chapters: Vec<&str> = self.selected_chapters_input.split(',').collect();
            total_chapters = chapters.len().max(1);
            debug!("Total chapters from input: {}", total_chapters);
        }

        for log in &self.download_logs {
            if log.contains("Downloading Chapter") {
                if let Some(chap_str) = log.split(" of ").next() {
                    if let Some(num_str) = chap_str.split("Chapter ").last() {
                        if let Ok(num) = num_str.trim().parse::<usize>() {
                            current_chapter = num;
                            if current_chapter != last_detected_chapter {
                                debug!("New chapter started: {}, resetting image progress", current_chapter);
                                current_chapter_images = 0;
                                total_images_in_current_chapter = 1;
                                last_detected_chapter = current_chapter;
                            }
                        }
                    }
                }
            }
            if log.contains("Found") && log.contains("images for Chapter") {
                if let Some(num_str) = log.split("Found ").nth(1) {
                    if let Some(num) = num_str.split(" images").next() {
                        if let Ok(num) = num.trim().parse::<usize>() {
                            total_images_in_current_chapter = num.max(1);
                            debug!("Total images in current chapter: {}", total_images_in_current_chapter);
                        }
                    }
                }
            }
            if log.contains("Downloaded image") {
                if let Some(img_str) = log.split("Downloaded image ").nth(1) {
                    if let Some(num_str) = img_str.split('/').next() {
                        if let Ok(num) = num_str.trim().parse::<usize>() {
                            current_chapter_images = num;
                            debug!("Images downloaded in current chapter: {}/{}", current_chapter_images, total_images_in_current_chapter);
                        }
                    }
                }
            }
            if log.contains(".cbr created with") {
                completed_chapters += 1;
                current_chapter_images = total_images_in_current_chapter;
                debug!("Detected completed chapter, total completed: {}", completed_chapters);
            }
        }

        let progress = if total_chapters > 0 {
            let chapter_progress = completed_chapters as f32 / total_chapters as f32;
            let image_progress = if completed_chapters < current_chapter {
                (current_chapter_images as f32 / total_images_in_current_chapter as f32) / total_chapters as f32
            } else {
                0.0
            };
            ((chapter_progress + image_progress) * 100.0).min(100.0).max(0.0)
        } else {
            0.0
        };

        (total_chapters, completed_chapters, progress, current_chapter_images, total_images_in_current_chapter, current_chapter)
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

    pub fn on_resize(&mut self, width: u16, height: u16) -> Result<()> {
        self.term_width = width;
        self.term_height = height;
        debug!("Terminal resized to width={}, height={}", width, height);
        self.load_cover_image()?;
        Ok(())
    }

    pub fn tick(&mut self) -> Result<()> {
        if self.is_downloading {
            let mut should_clear_receiver = false;
            {
                if let Some(receiver) = &self.download_log_receiver {
                    while let Ok(log) = receiver.try_recv() {
                        let clean_log = strip_ansi_escapes(&log);
                        if clean_log.contains("📖 Manga en cours de téléchargement:") {
                            if let Some(name) = clean_log.split("📖 Manga en cours de téléchargement: ").nth(1) {
                                self.current_download_manga_name = name.trim().to_string();
                                debug!("Updated current_download_manga_name to: {}", self.current_download_manga_name);
                            }
                        }
                        if clean_log.contains("Download Complete!") {
                            self.is_downloading = false;
                            self.download_finished = true;
                            should_clear_receiver = true;
                            self.status = format!(
                                "Download {} terminé. Press 'r' to refresh manga list, or continue viewing logs.",
                                self.current_download_manga_name
                            );
                        }
                        self.download_logs.push(clean_log);
                        if self.download_logs.len() > 200 {
                            self.download_logs.drain(0..self.download_logs.len() - 200);
                        }
                    }
                }
            }
            if should_clear_receiver {
                self.download_log_receiver = None;
            }
        }
    
        if let Some(ref receiver) = &self.refresh_trigger {
            if receiver.try_recv().is_ok() {
                debug!("External reader closed, refreshing manga list...");
                self.refresh_manga_list()?;
                self.status = "Manga list refreshed after closing external reader.".to_string();
                self.needs_refresh = true;
                self.refresh_trigger = None;
            }
        }
    
        self.current_page = (self.current_page + 1) % 100;
        Ok(())
    }

    pub fn handle_key(&mut self, event: &Event) -> Result<bool> {
        debug!("Handling event: {:?}", event); // Log all events
        match self.state {
            AppState::BrowseManga => Ok(self.handle_browse_input(event)),
            AppState::ViewMangaDetails => match event {
                Event::Key(key) => Ok(self.handle_details_input(*key)),
                Event::Mouse(mouse) => {
                    debug!("Mouse event received: {:?}", mouse); // Log all mouse events
                    match mouse.kind {
                        MouseEventKind::ScrollUp => {
                            debug!("Processing ScrollUp");
                            if let Some(manga) = self.current_manga() {
                                if !manga.chapters.is_empty() {
                                    self.selected_chapter = Some(match self.selected_chapter {
                                        Some(i) => if i == 0 { manga.chapters.len() - 1 } else { i - 1 },
                                        None => 0,
                                    });
                                    debug!("Selected chapter after ScrollUp: {:?}", self.selected_chapter);
                                }
                            }
                            Ok(false)
                        }
                        MouseEventKind::ScrollDown => {
                            debug!("Processing ScrollDown");
                            if let Some(manga) = self.current_manga() {
                                if !manga.chapters.is_empty() {
                                    self.selected_chapter = Some(match self.selected_chapter {
                                        Some(i) => (i + 1) % manga.chapters.len(),
                                        None => 0,
                                    });
                                    debug!("Selected chapter after ScrollDown: {:?}", self.selected_chapter);
                                }
                            }
                            Ok(false)
                        }
                        _ => {
                            debug!("Other mouse event kind: {:?}", mouse.kind);
                            Ok(false)
                        }
                    }
                }
                _ => Ok(false),
            },
            AppState::DownloadInput => if let Event::Key(key) = event {
                Ok(self.handle_download_input(*key))
            } else {
                Ok(false)
            },
            AppState::Downloading => if let Event::Key(key) = event {
                Ok(self.handle_downloading_input(*key))
            } else {
                Ok(false)
            },
            AppState::Settings => if let Event::Key(key) = event {
                Ok(self.handle_settings_input(*key))
            } else {
                Ok(false)
            },
        }
    }

    fn handle_browse_input(&mut self, event: &Event) -> bool {
        // Si on est en mode saisie (champ de filtre), on ne traite QUE les touches liées au filtre
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
    
        match event {
            Event::Key(key) => match key.code {
                KeyCode::Char('q') => {
                    self.should_quit = true;
                    return true;
                }
                KeyCode::Char('?') => {
                    self.show_help = !self.show_help;
                    self.status = if self.show_help { "Help displayed".to_string() } else { "Help hidden".to_string() };
                    return false;
                }
                KeyCode::Char('r') => {
                    if let Ok(()) = self.refresh_manga_list() {
                        self.status = "Liste des mangas actualisée".to_string();
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
                    debug!("Focus switched: {}", self.status);
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
                        let filtered_count = self.filtered_mangas().count();
                        if filtered_count > 0 {
                            self.selected_manga = Some(match self.selected_manga {
                                Some(i) => if i == 0 { filtered_count - 1 } else { i - 1 },
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
                        let filtered_count = self.filtered_mangas().count();
                        if filtered_count > 0 {
                            self.selected_manga = Some(match self.selected_manga {
                                Some(i) => (i + 1) % filtered_count,
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
                            let read = !chapter.read;
                            if let Err(e) = self.toggle_chapter_read_state(read) {
                                self.status = format!("Erreur: {}", e);
                            }
                        }
                    }
                    return false;
                }
                KeyCode::Char('M') if key.modifiers.contains(crossterm::event::KeyModifiers::SHIFT) => {
                    if !self.is_manga_list_focused {
                        if let Some(manga_idx) = self.selected_manga {
                            if let Some(manga) = self.mangas.get_mut(manga_idx) {
                                let manga_name = manga.name.clone();
                                for chapter in &mut manga.chapters {
                                    let path = chapter.path.clone();
                                    if let Err(e) = self.config.mark_chapter_as_unread(&path) {
                                        self.status = format!("Erreur: {}", e);
                                        return false;
                                    }
                                    chapter.read = false;
                                    chapter.last_page_read = None;
                                    if let Err(e) = chapter.update_progress(
                                        &manga_name,
                                        0,
                                        chapter.full_pages_read.unwrap_or(20),
                                        false,
                                    ) {
                                        error!("Failed to save progress: {}", e);
                                        self.status = format!("Erreur lors de la sauvegarde de la progression: {}", e);
                                        return false;
                                    }
                                }
                                self.status = "Tous les chapitres marqués comme non lus".to_string();
                            }
                        }
                    }
                    return false;
                }
                _ => return false,
            },
    
            Event::Mouse(mouse_event) => match mouse_event.kind {
                MouseEventKind::ScrollDown => {
                    let now = Instant::now();
                    debug!("Mouse ScrollDown detected, time since last: {:?}", now.duration_since(self.last_mouse_scroll));
                    if now.duration_since(self.last_mouse_scroll) < Duration::from_millis(120) {
                        debug!("ScrollDown ignored due to debounce");
                        return false;
                    }
                    self.last_mouse_scroll = now;
                    debug!("Mouse ScrollDown, is_manga_list_focused: {}", self.is_manga_list_focused);
                    if self.is_manga_list_focused {
                        let filtered_indices: Vec<usize> = self.mangas
                            .iter()
                            .enumerate()
                            .filter(|(_, manga)| {
                                if self.filter.is_empty() {
                                    true
                                } else {
                                    manga.name.to_lowercase().contains(&self.filter.to_lowercase())
                                }
                            })
                            .map(|(idx, _)| idx)
                            .collect();
                        if !filtered_indices.is_empty() {
                            if let Some(current_idx) = self.selected_manga {
                                if let Some(pos) = filtered_indices.iter().position(|&idx| idx == current_idx) {
                                    let new_pos = (pos + 1) % filtered_indices.len();
                                    self.selected_manga = Some(filtered_indices[new_pos]);
                                } else {
                                    self.selected_manga = Some(filtered_indices[0]);
                                }
                            } else {
                                self.selected_manga = Some(filtered_indices[0]);
                            }
                            self.selected_chapter = if let Some(manga) = self.current_manga() {
                                if manga.chapters.is_empty() { None } else { Some(0) }
                            } else {
                                None
                            };
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga after ScrollDown: {:?}", self.selected_manga);
                            }
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
                    false
                }
                MouseEventKind::ScrollUp => {
                    let now = Instant::now();
                    debug!("Mouse ScrollUp detected, time since last: {:?}", now.duration_since(self.last_mouse_scroll));
                    if now.duration_since(self.last_mouse_scroll) < Duration::from_millis(120) {
                        debug!("ScrollUp ignored due to debounce");
                        return false;
                    }
                    self.last_mouse_scroll = now;
                    debug!("Mouse ScrollUp, is_manga_list_focused: {}", self.is_manga_list_focused);
                    if self.is_manga_list_focused {
                        let filtered_indices: Vec<usize> = self.mangas
                            .iter()
                            .enumerate()
                            .filter(|(_, manga)| {
                                if self.filter.is_empty() {
                                    true
                                } else {
                                    manga.name.to_lowercase().contains(&self.filter.to_lowercase())
                                }
                            })
                            .map(|(idx, _)| idx)
                            .collect();
                        if !filtered_indices.is_empty() {
                            if let Some(current_idx) = self.selected_manga {
                                if let Some(pos) = filtered_indices.iter().position(|&idx| idx == current_idx) {
                                    let new_pos = if pos == 0 { filtered_indices.len() - 1 } else { pos - 1 };
                                    self.selected_manga = Some(filtered_indices[new_pos]);
                                } else {
                                    self.selected_manga = Some(filtered_indices[0]);
                                }
                            } else {
                                self.selected_manga = Some(filtered_indices[0]);
                            }
                            self.selected_chapter = if let Some(manga) = self.current_manga() {
                                if manga.chapters.is_empty() { None } else { Some(0) }
                            } else {
                                None
                            };
                            if let Ok(()) = self.load_cover_image() {
                                debug!("Selected manga after ScrollUp: {:?}", self.selected_manga);
                            }
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
                    false
                }
                _ => {
                    debug!("Other mouse event kind: {:?}", mouse_event.kind);
                    false
                }
            }
            _ => false,
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
                if let Some(chapter) = self.current_chapter() {
                    let read = !chapter.read;
                    if let Err(e) = self.toggle_chapter_read_state(read) {
                        self.status = format!("Erreur: {}", e);
                    }
                }
                return false;
            }
            KeyCode::Char('M') if key.modifiers.contains(crossterm::event::KeyModifiers::SHIFT) => {
                if let Some(manga_idx) = self.selected_manga {
                    if let Some(manga) = self.mangas.get_mut(manga_idx) {
                        let manga_name = manga.name.clone();
                        for chapter in &mut manga.chapters {
                            let path = chapter.path.clone();
                            if let Err(e) = self.config.mark_chapter_as_unread(&path) {
                                self.status = format!("Erreur: {}", e);
                                return false;
                            }
                            chapter.read = false;
                            chapter.last_page_read = None;
                            if let Err(e) = chapter.update_progress(
                                &manga_name,
                                0,
                                chapter.full_pages_read.unwrap_or(20),
                                false,
                            ) {
                                error!("Failed to save progress: {}", e);
                                self.status = format!("Erreur lors de la sauvegarde de la progression: {}", e);
                                return false;
                            }
                        }
                        self.status = "Tous les chapitres marqués comme non lus".to_string();
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
                        InputField::Url => self.download_url.push(c),
                        InputField::Chapters => self.selected_chapters_input.push(c),
                        InputField::MangaDir => {}
                        InputField::None => {}
                    }
                }
                return false;
            }
            KeyCode::Backspace => {
                if self.input_mode {
                    match self.input_field {
                        InputField::Url => { let _ = self.download_url.pop(); }
                        InputField::Chapters => { let _ = self.selected_chapters_input.pop(); }
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
                self.is_manga_list_focused = true;
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
                self.is_manga_list_focused = true;
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
                            self.status = "Error: Invalid or impossible path".to_string();
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