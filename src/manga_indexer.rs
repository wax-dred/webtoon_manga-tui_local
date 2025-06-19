use anyhow::Result;
use log::debug;
use rusqlite::Connection;
use rusqlite::OptionalExtension;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::mpsc;
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};
use walkdir::WalkDir;

#[allow(dead_code)]
pub struct Manga {
    pub id: i64,
    pub name: String,
    pub ta: Option<String>,         // chemin vers image
    pub synopsis: Option<String>,   // texte synopsis
    pub source_url: Option<String>, // url source
}

pub fn open_db() -> Result<Connection> {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let db_dir = Path::new(&home).join(".config/manga_reader");
    let db_path = db_dir.join("library.db");

    if let Err(e) = fs::create_dir_all(&db_dir) {
        return Err(anyhow::anyhow!(
            "Failed to create database directory: {}",
            e
        ));
    }

    debug!("Opening database at: {:?}", db_path);

    let conn = Connection::open(&db_path)?;
    debug!("Database connection established");

    conn.execute("PRAGMA foreign_keys = ON", [])?;

    // Check and create mangas table
    let mangas_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'mangas'",
            [],
            |row| row.get::<_, i32>(0),
        )
        .map(|count| count > 0)
        .unwrap_or(false);

    if !mangas_exists {
        debug!("Table 'mangas' does not exist, creating it");
        conn.execute(
            "CREATE TABLE mangas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                cover TEXT,
                thumbnail TEXT,
                synopsis TEXT,
                source_url TEXT
            )",
            [],
        )?;
        debug!("Table 'mangas' created successfully");
    } else {
        // Check if the synopsis column exists
        let synopsis_exists: bool = conn
            .query_row(
                "SELECT COUNT(*) FROM pragma_table_info('mangas') WHERE name = 'synopsis'",
                [],
                |row| row.get::<_, i32>(0),
            )
            .map(|count| count > 0)
            .unwrap_or(false);

        if !synopsis_exists {
            debug!("Column 'synopsis' not found, performing migration");
            conn.execute(
                "CREATE TABLE mangas_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    cover TEXT,
                    thumbnail TEXT,
                    synopsis TEXT,
                    source_url TEXT
                )",
                [],
            )?;
            conn.execute(
                "INSERT INTO mangas_temp (id, name, cover, thumbnail, source_url)
                 SELECT id, name, cover, thumbnail, source_url FROM mangas",
                [],
            )?;
            conn.execute("DROP TABLE mangas", [])?;
            conn.execute("ALTER TABLE mangas_temp RENAME TO mangas", [])?;
            debug!("Migration completed: added 'synopsis' column");
        }
    }

    // Create or update chapters table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL,
            num INTEGER NOT NULL,
            file TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            last_page_read INTEGER,
            full_pages_read INTEGER,
            size INTEGER NOT NULL DEFAULT 0,
            modified INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (manga_id) REFERENCES mangas(id)
        )",
        [],
    )?;
    debug!("Table 'chapters' ensured");

    // Check if size and modified columns exist
    let size_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) FROM pragma_table_info('chapters') WHERE name = 'size'",
            [],
            |row| row.get::<_, i32>(0),
        )
        .map(|count| count > 0)
        .unwrap_or(false);

    if !size_exists {
        debug!("Column 'size' not found, adding it");
        conn.execute(
            "ALTER TABLE chapters ADD COLUMN size INTEGER NOT NULL DEFAULT 0",
            [],
        )?;
        conn.execute(
            "ALTER TABLE chapters ADD COLUMN modified INTEGER NOT NULL DEFAULT 0",
            [],
        )?;
        debug!("Columns 'size' and 'modified' added");
    }

    // Create metadata table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value INTEGER
        )",
        [],
    )?;
    debug!("Table 'metadata' ensured");

    // Create index
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapters_manga_id ON chapters(manga_id)",
        [],
    )?;
    debug!("Index 'idx_chapters_manga_id' ensured");

    Ok(conn)
}


// Replace scan_and_index function (as requested)
pub fn scan_and_index(conn: &Connection, root: &Path) -> Result<()> {
    let last_scan_time = conn
        .query_row(
            "SELECT value FROM metadata WHERE key = 'last_scan_time'",
            [],
            |row| row.get::<_, i64>(0),
        )
        .optional()?
        .unwrap_or(0);

    let mut needs_scan = false;
    for entry in WalkDir::new(root).into_iter().filter_map(|e| e.ok()) {
        if entry.file_type().is_file() {
            let metadata = fs::metadata(entry.path())?;
            let modified = metadata.modified()?.duration_since(UNIX_EPOCH)?.as_secs() as i64;
            if modified > last_scan_time {
                needs_scan = true;
                break;
            }
        }
    }

    if !needs_scan {
        debug!("No changes detected since last scan, skipping reindexing");
        return Ok(());
    }

    // Clear outdated data
    conn.execute("DELETE FROM chapters", [])?;
    conn.execute("DELETE FROM mangas", [])?;

    let (tx, rx) = mpsc::channel();
    let root_path = root.to_path_buf();

    thread::spawn(move || {
        for entry in WalkDir::new(&root_path).into_iter().filter_map(|e| e.ok()) {
            if entry.file_type().is_file() {
                if let Some(ext) = entry.path().extension() {
                    if ext == "cbz" || ext == "cbr" {
                        let _ = tx.send(entry.path().to_path_buf());
                    }
                }
            }
        }
    });

    let mut manga_cache: HashMap<String, i64> = HashMap::new();

    for path in rx {
        let manga_dir = path.parent().unwrap_or_else(|| Path::new("."));
        let manga_name = manga_dir
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("Unknown")
            .to_string();

        let cover_candidates = [
            "cover.jpg",
            "cover.jpeg",
            "cover.png",
            "thumbnail.jpg",
            "thumbnail.jpeg",
            "thumbnail.png",
            "poster.jpg",
            "poster.jpeg",
            "poster.png",
        ];
        let thumbnail_path = cover_candidates
            .iter()
            .map(|fname| manga_dir.join(fname))
            .find(|p| p.exists())
            .map(|p| p.to_string_lossy().to_string());

        let synopsis_path = manga_dir.join("synopsis.txt");
        let (synopsis, source_url) = if synopsis_path.exists() {
            match fs::read_to_string(&synopsis_path) {
                Ok(text) => {
                    let parts: Vec<&str> = text.split("\nSource: ").collect();
                    let synopsis_text = parts[0].trim().to_string();
                    let source = parts
                        .get(1)
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty() && s.starts_with("http"));
                    debug!("Synopsis: {}, Source URL: {:?}", synopsis_text, source);
                    (Some(synopsis_text), source)
                }
                Err(e) => {
                    debug!("Failed to read synopsis.txt: {}", e);
                    (None, None)
                }
            }
        } else {
            debug!("No synopsis.txt found in {:?}", manga_dir);
            (None, None)
        };

        let manga_id = if let Some(&id) = manga_cache.get(&manga_name) {
            id
        } else {
            conn.execute(
                "INSERT INTO mangas (name, thumbnail, synopsis, source_url) VALUES (?1, ?2, ?3, ?4)
                 ON CONFLICT(name) DO UPDATE SET thumbnail=excluded.thumbnail, synopsis=excluded.synopsis, source_url=excluded.source_url",
                rusqlite::params![
                    manga_name.clone(),
                    thumbnail_path.as_deref(),
                    synopsis.as_deref(),
                    source_url.as_deref()
                ],
            )?;
            let id: i64 = conn.query_row(
                "SELECT id FROM mangas WHERE name = ?1",
                [manga_name.clone()],
                |row| row.get(0),
            )?;
            manga_cache.insert(manga_name.clone(), id);
            id
        };

        if let Some(num) =
            extract_chapter_num(path.file_name().and_then(|n| n.to_str()).unwrap_or(""))
        {
            let metadata = fs::metadata(&path)?;
            let size = metadata.len();
            let modified = metadata.modified()?.duration_since(UNIX_EPOCH)?.as_secs() as i64;

            conn.execute(
                "INSERT OR IGNORE INTO chapters (manga_id, num, file, size, modified) VALUES (?1, ?2, ?3, ?4, ?5)",
                rusqlite::params![manga_id, num as i64, path.to_string_lossy().to_string(), size as i64, modified],
            )?;
        }
    }

    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_scan_time', ?1)",
        [SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64],
    )?;

    Ok(())
}

pub fn extract_chapter_num(filename: &str) -> Option<u32> {
    let number = crate::manga::extract_chapter_number(filename)?;
    if number == (number as u32) as f32 {
        Some(number as u32)
    } else {
        None
    }
}
