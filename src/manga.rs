use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use chrono::{DateTime, Local};
use log::{debug, error, info};

use crate::config::Config;

/// Represents a manga series
#[derive(Debug, Clone)]
pub struct Manga {
    /// Manga name
    pub name: String,
    /// Path to the manga directory
    pub path: PathBuf,
    /// List of chapters
    pub chapters: Vec<Chapter>,
    /// Thumbnail image path
    pub thumbnail: Option<PathBuf>,
    /// Synopsis (if available)
    pub synopsis: Option<String>,
    /// Total page count
    pub total_pages: usize,
}

/// Represents a manga chapter
#[derive(Debug, Clone)]
pub struct Chapter {
    /// Chapter number
    pub number: f32,
    /// Chapter title
    pub title: String,
    /// Path to the chapter file
    pub path: PathBuf,
    /// Chapter file size
    pub size: u64,
    /// Number of pages
    pub pages: usize,
    /// Last modified date
    pub modified: u64,
    /// Is the chapter read
    pub read: bool,
}

impl Manga {
    /// Load a manga from a path
    pub fn from_path<P: AsRef<Path>>(path: P, config: &Config) -> Result<Self> {
        let path = path.as_ref();
        debug!("Loading manga from path: {:?}", path);
        
        // Get manga name from directory name
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("Unknown")
            .to_string();
        
        debug!("Manga name: {}", name);
        
        // Find thumbnail
        let thumbnail_candidates = [
            "cover.jpg", "cover.jpeg", "cover.png", 
            "thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png",
            "poster.jpg", "poster.jpeg", "poster.png",
        ];
        
        let mut thumbnail = None;
        for candidate in &thumbnail_candidates {
            let thumb_path = path.join(candidate);
            if thumb_path.exists() {
                debug!("Found thumbnail: {:?}", &thumb_path);
                thumbnail = Some(thumb_path.clone());
                break;
            }
        }

        for candidate in &thumbnail_candidates {
            let thumb_path = path.join(candidate);
            if thumb_path.exists() {
                debug!("Found thumbnail: {:?}", &thumb_path);
                thumbnail = Some(thumb_path.clone());
                break;
            }
        }
        if thumbnail.is_none() {
            debug!("No thumbnail found for manga: {}", name);
        }
        
        // Try to find synopsis
        let synopsis_path = path.join("synopsis.txt");
        let synopsis = if synopsis_path.exists() {
            match fs::read_to_string(&synopsis_path) {
                Ok(text) => {
                    debug!("Found synopsis ({} chars)", text.len());
                    Some(text)
                },
                Err(e) => {
                    error!("Failed to read synopsis: {}", e);
                    None
                }
            }
        } else {
            debug!("No synopsis found");
            None
        };
        
        // Find and load chapters
        let mut chapters = Vec::new();
        let mut total_pages = 0;
        
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                let entry_path = entry.path();
                
                // Skip directories, only check files
                if entry_path.is_dir() {
                    continue;
                }
                
                // Check if file is a chapter (CBR/CBZ files)
                let extension = entry_path
                    .extension()
                    .and_then(|e| e.to_str())
                    .unwrap_or("")
                    .to_lowercase();
                
                if extension == "cbr" || extension == "cbz" || extension == "pdf" {
                    match Chapter::from_path(&entry_path, config) {
                        Ok(mut chapter) => {
                            // Check if chapter is read
                            chapter.read = config.is_chapter_read(&entry_path);
                            total_pages += chapter.pages;
                            let title = chapter.title.clone();
                            let pages = chapter.pages;
                            chapters.push(chapter);
                            debug!("Added chapter: {} with {} pages", title, pages);
                        },
                        Err(e) => {
                            error!("Failed to load chapter {:?}: {}", entry_path, e);
                        }
                    }
                }
            }
        }
        
        // Sort chapters
        chapters.sort_by(|a, b| a.number.partial_cmp(&b.number).unwrap_or(std::cmp::Ordering::Equal));
        debug!("Sorted {} chapters", chapters.len());
        
        let manga = Self {
            name,
            path: path.to_path_buf(),
            chapters,
            thumbnail,
            synopsis,
            total_pages,
        };
        
        Ok(manga)
    }

    /// Scan a directory for manga
    pub fn scan_directory<P: AsRef<Path>>(path: P, config: &Config) -> Result<Vec<Self>> {
        let path = path.as_ref();
        info!("Scanning directory for manga: {:?}", path);
        
        if !path.exists() {
            return Err(anyhow::anyhow!("Directory does not exist: {:?}", path));
        }
        
        if !path.is_dir() {
            return Err(anyhow::anyhow!("Path is not a directory: {:?}", path));
        }
        
        let mut mangas = Vec::new();
        
        // First check if this directory is itself a manga
        let entries = fs::read_dir(path)?;
        let is_manga = entries
            .filter_map(Result::ok)
            .any(|entry| {
                let path = entry.path();
                if path.is_file() {
                    if let Some(ext) = path.extension() {
                        if let Some(ext_str) = ext.to_str() {
                            let ext_lower = ext_str.to_lowercase();
                            return ext_lower == "cbr" || ext_lower == "cbz";
                        }
                    }
                }
                false
            });
        
        if is_manga {
            // This directory contains CBR/CBZ files, load it as a manga
            match Self::from_path(path, config) {
                Ok(manga) => {
                    debug!("Found manga in root directory: {}", manga.name);
                    mangas.push(manga);
                },
                Err(e) => {
                    error!("Failed to load manga from root: {}", e);
                }
            }
        } else {
            // Scan subdirectories
            if let Ok(entries) = fs::read_dir(path) {
                for entry in entries.flatten() {
                    let entry_path = entry.path();
                    
                    if entry_path.is_dir() {
                        // Check if this subdirectory is a manga
                        match Self::from_path(&entry_path, config) {
                            Ok(manga) => {
                                if !manga.chapters.is_empty() {
                                    debug!("Found manga in subdirectory: {}", manga.name);
                                    mangas.push(manga);
                                } else {
                                    debug!("Skipping empty manga: {:?}", entry_path);
                                }
                            },
                            Err(e) => {
                                error!("Failed to load manga from subdirectory: {}", e);
                            }
                        }
                    }
                }
            }
        }
        
        debug!("Found {} mangas", mangas.len());
        Ok(mangas)
    }
}

impl Chapter {
    /// Create a new chapter from a path
    pub fn from_path<P: AsRef<Path>>(path: P, _config: &Config) -> Result<Self> {
        let path = path.as_ref();
        
        let metadata = fs::metadata(path).context("Failed to get chapter metadata")?;
        
        // Extract chapter number from filename
        let filename = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("Unknown")
            .to_string();
        
        let number = extract_chapter_number(&filename).unwrap_or(0.0);
        
        let modified = metadata
            .modified()
            .unwrap_or_else(|_| SystemTime::now())
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        
        let size = metadata.len();
        
        let pages = estimate_page_count(size);
        
        Ok(Self {
            number,
            title: filename,
            path: path.to_path_buf(),
            size,
            pages,
            modified,
            read: false,
        })
    }

    /// Format the chapter number as a string (e.g. "#12")
    pub fn number_display(&self) -> String {
        if self.number == (self.number as u32) as f32 {
            format!("#{:.0}", self.number)
        } else {
            format!("#{:.1}", self.number)
        }
    }

    /// Format last modified date
    pub fn date_display(&self) -> String {
        let timestamp = UNIX_EPOCH + std::time::Duration::from_secs(self.modified);
        let datetime: DateTime<Local> = DateTime::from(timestamp);
        datetime.format("%Y-%m-%d").to_string()
    }

    /// Format file size
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

/// Extract chapter number from filename
fn extract_chapter_number(filename: &str) -> Option<f32> {
    let lowercase = filename.to_lowercase();
    
    // Common chapter indicators
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
    
    // Try to find just numbers at the beginning
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
    
    // Try to extract from file number pattern like 001, 002, etc.
    let re = regex::Regex::new(r"(\d{2,3})").ok()?;
    if let Some(caps) = re.captures(&lowercase) {
        if let Some(m) = caps.get(1) {
            if let Ok(num) = m.as_str().parse::<f32>() {
                return Some(num);
            }
        }
    }
    
    None
}

/// Estimate number of pages based on file size
fn estimate_page_count(size: u64) -> usize {
    // Average page size is about 100KB
    const AVG_PAGE_SIZE: u64 = 100 * 1024;
    
    if size == 0 {
        0
    } else {
        (size / AVG_PAGE_SIZE).max(1) as usize
    }
}
