use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;
use std::io::{self, BufReader, BufWriter};
use anyhow::Result;
use log::{debug, error};
use crate::config::Config;
use std::collections::HashMap;
use serde::{Serialize, Deserialize};
use rayon::prelude::*;

/// Represents the progress of a chapter
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterProgress {
    pub last_page: usize,
    pub total_pages: usize,
    pub read: bool,
}

#[derive(Serialize, Deserialize)]
struct MangaCache {
    entries: HashMap<String, (u64, u64)>, // Path -> (size, modified)
    last_updated: u64,
}

/// Represents a manga series
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manga {
    pub name: String,
    #[allow(dead_code)]
    pub path: PathBuf,
    pub chapters: Vec<Chapter>,
    pub thumbnail: Option<PathBuf>,
    pub synopsis: Option<String>,
}

/// Represents a manga chapter
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chapter {
    pub number: f32,
    pub title: String,
    pub path: PathBuf,
    pub size: u64,
    #[allow(dead_code)]
    pub modified: u64,
    pub read: bool,
    pub last_page_read: Option<usize>,
    pub full_pages_read: Option<usize>, // Total pages
}

/// Represents the source of a manga (local or MangaDex)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MangaSource {
    Local(Manga),
    MangaDex {
        id: String,
        name: String,
        synopsis: Option<String>,
        thumbnail: Option<String>,
    },
}

/// Represents the source of a chapter (local or MangaDex)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ChapterSource {
    Local(Chapter),
    MangaDex {
        id: String,
        number: String,
        title: Option<String>,
        language: String,
    },
}

pub type ChapterProgressMap = HashMap<String, ChapterProgress>;
pub type MangaProgressMap = HashMap<String, ChapterProgressMap>;

impl Manga {
    fn load_cache() -> Result<MangaCache> {
        let cache_path = PathBuf::from("manga_cache.json");
        if cache_path.exists() {
            let cache_str = fs::read_to_string(&cache_path)?;
            Ok(serde_json::from_str(&cache_str)?)
        } else {
            Ok(MangaCache {
                entries: HashMap::new(),
                last_updated: 0,
            })
        }
    }

    fn save_cache(cache: &MangaCache) -> Result<()> {
        let cache_path = PathBuf::from("manga_cache.json");
        let cache_str = serde_json::to_string_pretty(cache)?;
        fs::write(&cache_path, cache_str)?;
        Ok(())
    }

    pub fn from_path<P: AsRef<Path>>(path: P, config: &Config) -> Result<Self> {
        let path = path.as_ref();
        let mut cache = Self::load_cache()?;
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("Unknown").to_string();
    
        let thumbnail_candidates = [
            "cover.jpg", "cover.jpeg", "cover.png",
            "thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png",
            "poster.jpg", "poster.jpeg", "poster.png",
        ];
    
        let thumbnail = thumbnail_candidates
            .iter()
            .map(|c| path.join(c))
            .find(|p| p.exists());
    
        let synopsis_path = path.join("synopsis.txt");
        let synopsis = if synopsis_path.exists() {
            match fs::read_to_string(&synopsis_path) {
                Ok(text) => {
                    debug!("Found synopsis ({} chars)", text.len());
                    Some(text)
                }
                Err(e) => {
                    error!("Failed to read synopsis: {}", e);
                    return Err(anyhow::anyhow!("Failed to read synopsis file: {}", e));
                }
            }
        } else {
            None
        };
    
        let mut chapters = Vec::new();
    
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                let entry_path = entry.path();
                if entry_path.is_dir() {
                    continue;
                }
    
                if let Some(file_name) = entry_path.file_name().and_then(|n| n.to_str()) {
                    if file_name.ends_with(".pagecache") {
                        debug!("Removing old pagecache file: {:?}", entry_path);
                        if let Err(e) = fs::remove_file(&entry_path) {
                            error!("Failed to remove pagecache file {:?}: {}", entry_path, e);
                        }
                        continue;
                    }
                }
    
                let path_str = entry_path.to_string_lossy().to_string();
                let extension = entry_path
                    .extension()
                    .and_then(|e| e.to_str())
                    .unwrap_or("")
                    .to_lowercase();
    
                if ["cbr", "cbz", "pdf"].contains(&extension.as_str()) {
                    // Update cache if necessary
                    if !cache.entries.contains_key(&path_str) {
                        let meta = fs::metadata(&entry_path)?;
                        let modified = meta.modified()?.duration_since(UNIX_EPOCH)?.as_secs();
                        cache.entries.insert(path_str.clone(), (meta.len(), modified));
                    }
    
                    match Chapter::from_path(&entry_path, config, &name) {
                        Ok(chapter) => {
                            chapters.push(chapter);
                            debug!("Added chapter: {}", entry_path.display());
                        }
                        Err(e) => {
                            error!("Failed to load chapter {:?}: {}", entry_path, e);
                        }
                    }
                }
            }
        }
    
        Self::save_cache(&cache)?;
    
        chapters.sort_by(|a, b| a.number.partial_cmp(&b.number).unwrap_or(std::cmp::Ordering::Equal));
        debug!("Sorted {} chapters", chapters.len());
    
        Ok(Manga {
            name,
            path: path.to_path_buf(),
            chapters,
            thumbnail,
            synopsis,
        })
    }

    pub fn scan_directory<P: AsRef<Path>>(path: P, config: &Config) -> Result<Vec<Manga>> {
        let path = path.as_ref();
        debug!("Scanning directory for manga: {:?}", path);

        if !path.exists() {
            return Err(anyhow::anyhow!("Directory does not exist: {:?}", path));
        }

        if !path.is_dir() {
            return Err(anyhow::anyhow!("Path is not a directory: {:?}", path));
        }

        let mut mangas = Vec::new();

        let is_manga = fs::read_dir(path)?
            .filter_map(Result::ok)
            .any(|entry| {
                let path = entry.path();
                if path.is_file() {
                    if let Some(ext) = path.extension() {
                        if let Some(ext_str) = ext.to_str() {
                            let ext_lower = ext_str.to_lowercase();
                            return ["cbr", "cbz", "pdf"].contains(&ext_lower.as_str());
                        }
                    }
                }
                false
            });

        if is_manga {
            if let Ok(manga) = Self::from_path(path, config) {
                debug!("Found manga in root directory: {}", manga.name);
                mangas.push(manga);
            }
        } else {
            let entries: Vec<_> = fs::read_dir(path)?.filter_map(Result::ok).collect();
            let new_mangas: Vec<Manga> = entries
                .par_iter()
                .filter(|entry| entry.path().is_dir())
                .filter_map(|entry| {
                    match Self::from_path(entry.path(), config) {
                        Ok(manga) if !manga.chapters.is_empty() => {
                            debug!("Found manga in subdirectory: {}", manga.name);
                            Some(manga)
                        }
                        Ok(_) => {
                            debug!("Skipping empty manga: {:?}", entry.path());
                            None
                        }
                        Err(e) => {
                            error!("Failed to load manga from subdirectory: {}", e);
                            None
                        }
                    }
                })
                .collect();

            mangas.extend(new_mangas);
        }
        Ok(mangas)
    }

    pub fn load_chapter_progress(manga_name: &str, chapter_number: &str) -> Option<ChapterProgress> {
        let progress_path = Self::get_progress_file_path();
        if let Ok(file) = File::open(&progress_path) {
            if let Ok(progress_map) = serde_json::from_reader::<_, MangaProgressMap>(BufReader::new(file)) {
                if let Some(manga_map) = progress_map.get(manga_name) {
                    if let Some(prog) = manga_map.get(chapter_number) {
                        return Some(prog.clone());
                    }
                }
            }
        }
        None
    }

    pub fn save_chapter_progress(manga_name: &str, chapter_number: &str, last_page: usize, total_pages: usize, read: bool) -> io::Result<()> {
        let progress_path = Self::get_progress_file_path();
        let mut progress_map: MangaProgressMap = if let Ok(file) = File::open(&progress_path) {
            serde_json::from_reader(BufReader::new(file)).unwrap_or_default()
        } else {
            HashMap::new()
        };
        let manga_entry = progress_map.entry(manga_name.to_string()).or_default();
        manga_entry.insert(
            chapter_number.to_string(),
            ChapterProgress {
                last_page,
                total_pages,
                read,
            },
        );
        if let Some(parent) = progress_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = File::create(progress_path)?;
        serde_json::to_writer_pretty(BufWriter::new(file), &progress_map)?;
        Ok(())
    }

    fn get_progress_file_path() -> PathBuf {
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".config/manga_reader/progress.json")
    }

    pub fn reload_progress(&mut self) {
        for chapter in &mut self.chapters {
            let chapter_key = format!("{:.1}", chapter.number);
            if let Some(progress) = Self::load_chapter_progress(&self.name, &chapter_key) {
                chapter.read = progress.read;
                chapter.last_page_read = if progress.last_page > 0 {
                    Some(progress.last_page)
                } else {
                    None
                };
                chapter.full_pages_read = Some(progress.total_pages);
                debug!(
                    "Updated chapter {}: read={}, last_page_read={:?}, full_pages_read={:?}",
                    chapter.number, chapter.read, chapter.last_page_read, chapter.full_pages_read
                );
            }
        }
    }
}

impl Chapter {
    pub fn from_path<P: AsRef<Path>>(path: P, _config: &Config, manga_name: &str) -> Result<Self> {
        let path = path.as_ref();
        let metadata = fs::metadata(path)?;
        let filename = path.file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("Unknown")
            .to_string();
        let number = extract_chapter_number(&filename).unwrap_or(0.0);
    
        let chapter_key = format!("{:.1}", number);
        let progress = Manga::load_chapter_progress(manga_name, &chapter_key);
        let read = progress.as_ref().map_or(false, |p| p.read);
        let last_page_read = progress.as_ref().and_then(|p| if p.last_page > 0 { Some(p.last_page) } else { None });
        let full_pages_read = progress.map(|p| p.total_pages); // Load total_pages
    
        Ok(Self {
            number,
            title: filename,
            path: path.to_path_buf(),
            size: metadata.len(),
            modified: metadata.modified()?.duration_since(UNIX_EPOCH)?.as_secs(),
            read,
            last_page_read,
            full_pages_read,
        })
    }

    pub fn update_progress(&mut self, manga_name: &str, last_page: usize, total_pages: usize, read: bool) -> io::Result<()> {
        let chapter_key = format!("{:.1}", self.number);
        Manga::save_chapter_progress(manga_name, &chapter_key, last_page, total_pages, read)?;
        self.read = read;
        self.last_page_read = if last_page > 0 { Some(last_page) } else { None };
        self.full_pages_read = Some(total_pages);
        Ok(())
    }

    pub fn number_display(&self) -> String {
        if self.number == (self.number as u32) as f32 {
            format!("#{:.0}", self.number)
        } else {
            format!("#{:.1}", self.number)
        }
    }

    #[allow(dead_code)]
    pub fn date_display(&self) -> String {
        use chrono::{DateTime, Local};
        use std::time::{Duration, UNIX_EPOCH};
        let timestamp = UNIX_EPOCH + Duration::from_secs(self.modified);
        let datetime: DateTime<Local> = DateTime::from(timestamp);
        datetime.format("%Y-%m-%d").to_string()
    }

    pub fn size_display(&self) -> String {
        if self.size < 1024 {
            format!("{}B", self.size)
        } else if self.size < 1024 * 1024 {
            format!("{:.1}KB", self.size as f32 / 1024.0)
        } else if self.size < 1024 * 1024 * 1024 {
            format!("{:.1}MB", self.size as f32 / 1024.0 / 1024.0)
        } else {
            format!("{:.1}GB", self.size as f32 / 1024.0 / 1024.0 / 1024.0)
        }
    }
}

fn extract_chapter_number(filename: &str) -> Option<f32> {
    let lowercase = filename.to_lowercase();
    let patterns = [
        "ch", "chapitre", "chapter", "chap", "#", "tome"
    ];

    for pattern in &patterns {
        if let Some(pos) = lowercase.find(pattern) {
            let after_pattern = &lowercase[pos + pattern.len()..];
            let number_str = after_pattern
                .trim_start_matches(|c: char| !c.is_digit(10) && c != '.')
                .chars()
                .take_while(|c| c.is_digit(10) || *c == '.')
                .collect::<String>();

            if let Ok(num) = number_str.parse::<f32>() {
                return Some(num);
            }
        }
    }
    let first_numbers = lowercase
        .chars()
        .skip_while(|c| !c.is_digit(10))
        .take_while(|c| c.is_digit(10) || *c == '.')
        .collect::<String>();
    if !first_numbers.is_empty() {
        if let Ok(num) = first_numbers.parse::<f32>() {
            return Some(num);
        }
    }
    if let Ok(re) = regex::Regex::new(r"(\d{2,3})") {
        if let Some(caps) = re.captures(&lowercase) {
            if let Some(m) = caps.get(1) {
                if let Ok(num) = m.as_str().parse::<f32>() {
                    return Some(num);
                }
            }
        }
    }
    None
}