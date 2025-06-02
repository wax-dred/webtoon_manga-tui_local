use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::collections::HashMap;

use anyhow::{Context, Result};
use log::{debug, error};
use serde::{Deserialize, Serialize};
use dirs::config_dir;

#[derive(Debug, Serialize, Deserialize)]
pub struct Config {
    pub last_manga_dir: Option<PathBuf>,
    pub read_chapters: HashSet<String>,
    pub open_command: Option<String>,
    pub settings: Settings,
    #[serde(default)]
    pub last_download_url: Option<String>,
    #[serde(default)]
    pub last_downloaded_chapters: Vec<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    pub prefer_external: bool,
    pub auto_mark_read: bool,
    pub default_provider: String,
    pub enable_image_rendering: bool,
    pub reader_options: HashMap<String, String>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            last_manga_dir: None,
            read_chapters: HashSet::new(),
            open_command: None,
            settings: Settings::default(),
            last_download_url: None,
            last_downloaded_chapters: Vec::new(),
        }
    }
}

impl Default for Settings {
    fn default() -> Self {
        let mut reader_options = HashMap::new();
        reader_options.insert("mode".to_string(), "webtoon".to_string());
        
        Self {
            prefer_external: false,
            auto_mark_read: true,
            default_provider: "manual".to_string(),
            enable_image_rendering: true,
            reader_options,
        }
    }
}

impl Config {
    pub fn load() -> Result<Self> {
        let config_dir = Self::config_dir()?;
        let config_path = config_dir.join("config.json");

        debug!("Loading config from {:?}", config_path);

        if !config_path.exists() {
            debug!("Config file doesn't exist, creating default config");
            let config = Self::default();
            config.save()?;
            return Ok(config);
        }

        let config_str = fs::read_to_string(&config_path).context("Failed to read config file")?;

        match serde_json::from_str(&config_str) {
            Ok(config) => {
                debug!("Config loaded successfully");
                Ok(config)
            }
            Err(e) => {
                error!("Failed to parse config file: {}", e);
                debug!("Falling back to default config");
                Ok(Self::default())
            }
        }
    }

    pub fn save(&self) -> Result<()> {
        let config_dir = Self::config_dir()?;
        let config_path = config_dir.join("config.json");

        debug!("Saving config to {:?}", config_path);

        if !config_dir.exists() {
            fs::create_dir_all(&config_dir).context("Failed to create config directory")?;
        }

        let config_str = serde_json::to_string_pretty(self).context("Failed to serialize config")?;

        fs::write(&config_path, config_str).context("Failed to write config file")?;

        debug!("Config saved successfully");
        Ok(())
    }

    fn config_dir() -> Result<PathBuf> {
        let config_dir = config_dir()
            .ok_or_else(|| anyhow::anyhow!("Cannot determine config directory"))?
            .join("manga_reader");
        Ok(config_dir)
    }

    pub fn mark_chapter_as_read<P: AsRef<Path>>(&mut self, path: P) -> Result<()> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        self.read_chapters.insert(path_str);
        self.save()?;
        Ok(())
    }

    pub fn mark_chapter_as_unread<P: AsRef<Path>>(&mut self, path: P) -> Result<()> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        self.read_chapters.remove(&path_str);
        self.save()?;
        Ok(())
    }
}