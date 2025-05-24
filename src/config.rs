use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use log::{debug, error};
use serde::{Deserialize, Serialize};

/// Application configuration
#[derive(Debug, Serialize, Deserialize)]
pub struct Config {
    /// Last manga directory
    pub last_manga_dir: Option<PathBuf>,
    /// Set of read chapters (paths are stored as strings)
    pub read_chapters: HashSet<String>,
    /// External command to open manga files
    pub open_command: Option<String>,
    /// Display settings
    pub settings: Settings,
    /// Last download URL
    #[serde(default)]
    pub last_download_url: Option<String>,
    /// Last downloaded chapters
    #[serde(default)]
    pub last_downloaded_chapters: Vec<u32>,
}

/// Display and behavior settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    /// Use external viewer instead of built-in
    pub prefer_external: bool,
    /// Auto-mark chapters as read
    pub auto_mark_read: bool,
    /// Default download provider
    pub default_provider: String,
    pub enable_image_rendering: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            prefer_external: false,
            auto_mark_read: true,
            default_provider: "manual".to_string(),
            enable_image_rendering: true,
        }
    }
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

impl Config {
    /// Load configuration from file
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

    /// Save configuration to file
    pub fn save(&self) -> Result<()> {
        let config_dir = Self::config_dir()?;
        let config_path = config_dir.join("config.json");

        debug!("Saving config to {:?}", config_path);

        // Create config directory if it doesn't exist
        if !config_dir.exists() {
            fs::create_dir_all(&config_dir).context("Failed to create config directory")?;
        }

        let config_str =
            serde_json::to_string_pretty(self).context("Failed to serialize config")?;

        fs::write(&config_path, config_str).context("Failed to write config file")?;

        debug!("Config saved successfully");
        Ok(())
    }

    /// Get configuration directory
    fn config_dir() -> Result<PathBuf> {
        let home_dir = shellexpand::tilde("~/.config/manga_reader");
        let config_dir = Path::new(&home_dir.to_string()).to_path_buf();
        Ok(config_dir)
    }

    /// Check if a chapter is marked as read
    pub fn is_chapter_read<P: AsRef<Path>>(&self, path: P) -> bool {
        let path_str = path.as_ref().to_string_lossy().to_string();
        self.read_chapters.contains(&path_str)
    }

    /// Mark a chapter as read
    pub fn mark_chapter_as_read<P: AsRef<Path>>(&mut self, path: P) -> Result<()> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        self.read_chapters.insert(path_str);
        self.save()?;
        Ok(())
    }

    /// Mark a chapter as unread
    pub fn mark_chapter_as_unread<P: AsRef<Path>>(&mut self, path: P) -> Result<()> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        self.read_chapters.remove(&path_str);
        self.save()?;
        Ok(())
    }
}