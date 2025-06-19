use anyhow::Result;
use log::debug;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter};
use std::path::PathBuf;

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub enum LoadingProgress {
    ScanningDirectory {
        current: String,
        total: usize,
        completed: usize,
    },
    LoadingManga {
        name: String,
        completed: usize,
        total: usize,
    },
    Complete {
        mangas: Vec<Manga>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterProgress {
    pub last_page: usize,
    pub total_pages: usize,
    pub read: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manga {
    pub id: i64, // Ajouté pour correspondre à la table mangas
    pub name: String,
    pub path: PathBuf,
    pub chapters: Vec<Chapter>,
    pub thumbnail: Option<PathBuf>,
    pub synopsis: Option<String>,
    pub source_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chapter {
    pub id: i64,
    pub manga_id: i64,
    pub num: u32,
    pub path: PathBuf,
    pub title: String,
    pub read: bool,
    pub last_page_read: Option<usize>,
    pub full_pages_read: Option<usize>,
    pub size: u64,
    pub modified: u64,
}

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
    pub fn load_all_from_db(
        conn: &Connection,
        _config: &crate::config::Config,
    ) -> Result<Vec<Manga>, anyhow::Error> {
        let mut mangas = Vec::new();
        let mut stmt =
            conn.prepare("SELECT id, name, thumbnail, synopsis, source_url FROM mangas")?;
        let manga_iter = stmt.query_map([], |row| {
            let thumbnail: Option<String> = row.get(2)?;
            Ok(Manga {
                id: row.get(0)?,
                name: row.get(1)?,
                path: PathBuf::from(&row.get::<_, String>(1)?), // Adjust as needed
                thumbnail: thumbnail.map(PathBuf::from),
                synopsis: row.get(3)?,
                source_url: row.get(4)?,
                chapters: Vec::new(),
            })
        })?;

        for manga in manga_iter {
            let mut manga = manga?;
            let mut chapter_stmt = conn.prepare(
                "SELECT id, manga_id, num, file, read, last_page_read, full_pages_read, size, modified 
                 FROM chapters WHERE manga_id = ? ORDER BY num",
            )?;
            let chapters = chapter_stmt.query_map([manga.id], |row| {
                let path: String = row.get(3)?;
                // Safely handle size and modified columns
                let size: i64 = row.get::<_, Option<i64>>(7)?.unwrap_or(0);
                let modified: i64 = row.get::<_, Option<i64>>(8)?.unwrap_or(0);
                Ok(Chapter {
                    id: row.get(0)?,
                    manga_id: row.get(1)?,
                    num: row.get(2)?,
                    path: PathBuf::from(path),
                    title: format!("Chapter {}", row.get::<_, u32>(2)?),
                    read: row.get::<_, i32>(4)? != 0,
                    last_page_read: row.get::<_, Option<i64>>(5)?.map(|v| v as usize),
                    full_pages_read: row.get::<_, Option<i64>>(6)?.map(|v| v as usize),
                    size: size as u64,
                    modified: modified as u64,
                })
            })?;

            manga.chapters = chapters.collect::<Result<Vec<_>, rusqlite::Error>>()?;
            mangas.push(manga);
        }

        Ok(mangas)
    }

    pub fn load_progress_lazy(&mut self) {
        // La progression est désormais gérée par la base de données, pas besoin de charger depuis progress.json
        // Cette méthode peut être laissée vide ou supprimée si elle n'est plus utilisée
    }

    pub fn reload_progress(&mut self) {
        self.load_progress_lazy();
    }

    #[allow(dead_code)]
    pub fn load_chapter_progress(manga_name: &str, chapter_num: &str) -> Option<ChapterProgress> {
        // Cette méthode est conservée pour compatibilité, mais elle ne sera plus utilisée
        let progress_path = Self::get_progress_file_path();
        if let Ok(file) = File::open(&progress_path) {
            if let Ok(progress_map) =
                serde_json::from_reader::<_, MangaProgressMap>(BufReader::new(file))
            {
                if let Some(manga_map) = progress_map.get(manga_name) {
                    if let Some(prog) = manga_map.get(chapter_num) {
                        return Some(prog.clone());
                    }
                }
            }
        }
        None
    }

    #[allow(dead_code)]
    pub fn save_chapter_progress(
        manga_name: &str,
        chapter_num: &str,
        last_page: usize,
        total_pages: usize,
        read: bool,
    ) -> io::Result<()> {
        // Cette méthode est conservée pour compatibilité, mais elle ne sera plus utilisée
        let progress_path = Self::get_progress_file_path();
        let mut progress_map: MangaProgressMap = if let Ok(file) = File::open(&progress_path) {
            serde_json::from_reader(BufReader::new(file)).unwrap_or_default()
        } else {
            HashMap::new()
        };
        let manga_entry = progress_map.entry(manga_name.to_string()).or_default();
        manga_entry.insert(
            chapter_num.to_string(),
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
}

impl Chapter {
    pub fn update_progress(
        &mut self,
        manga_name: &str,
        last_page: usize,
        total_pages: usize,
        read: bool,
    ) -> Result<(), anyhow::Error> {
        self.read = read;
        self.last_page_read = Some(last_page);
        self.full_pages_read = Some(total_pages);

        let conn = crate::manga_indexer::open_db()?;
        conn.execute(
            "UPDATE chapters SET read = ?1, last_page_read = ?2, full_pages_read = ?3 WHERE id = ?4",
            rusqlite::params![read as i32, last_page as i64, total_pages as i64, self.id],
        )?;

        debug!(
            "Progress updated for chapter {} of manga {}: read={}, last_page={}, total_pages={}",
            self.num, manga_name, read, last_page, total_pages
        );

        Ok(())
    }

    pub fn number_display(&self) -> String {
        format!("#{}", self.num)
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

pub fn extract_chapter_number(filename: &str) -> Option<f32> {
    let lowercase = filename.to_lowercase();
    let patterns = ["ch", "chapitre", "chapter", "chap", "#", "tome"];

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
