use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use serde::Deserialize;
use ratatui::style::Color;

#[derive(Deserialize)]
pub struct WalColors {
    special: SpecialColors,
    colors: ColorMap,
}

#[derive(Deserialize)]
struct SpecialColors {
    background: String,
    foreground: String,
    #[serde(default)]
    cursor: String,
}

#[derive(Deserialize)]
struct ColorMap {
    color0: String,
    color1: String,
    color2: String,
    color3: String,
    color4: String,
    color5: String,
    color6: String,
    color7: String,
    color8: String,
    color9: String,
    color10: String,
    color11: String,
    color12: String,
    color13: String,
    color14: String,
    color15: String,
}

pub struct Theme {
    pub background: Color,
    pub foreground: Color,
    #[allow(dead_code)]
    pub cursor: Color,
    pub colors: [Color; 16],
}

impl Theme {
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self> {
        let path = crate::util::expand_path(path);
        let json = fs::read_to_string(&path).context("Failed to read wal.json")?;
        
        let wal: WalColors = serde_json::from_str(&json).context("Failed to parse wal.json")?;
        
        Ok(Self {
            background: hex_to_color(&wal.special.background)?,
            foreground: hex_to_color(&wal.special.foreground)?,
            cursor: hex_to_color(&wal.special.cursor).unwrap_or(Color::White),
            colors: [
                hex_to_color(&wal.colors.color0)?,
                hex_to_color(&wal.colors.color1)?,
                hex_to_color(&wal.colors.color2)?,
                hex_to_color(&wal.colors.color3)?,
                hex_to_color(&wal.colors.color4)?,
                hex_to_color(&wal.colors.color5)?,
                hex_to_color(&wal.colors.color6)?,
                hex_to_color(&wal.colors.color7)?,
                hex_to_color(&wal.colors.color8)?,
                hex_to_color(&wal.colors.color9)?,
                hex_to_color(&wal.colors.color10)?,
                hex_to_color(&wal.colors.color11)?,
                hex_to_color(&wal.colors.color12)?,
                hex_to_color(&wal.colors.color13)?,
                hex_to_color(&wal.colors.color14)?,
                hex_to_color(&wal.colors.color15)?,
            ],
        })
    }
}

fn hex_to_color(hex: &str) -> Result<Color> {
    let hex = hex.trim_start_matches('#');
    let bytes = hex::decode(hex).context("Failed to decode hex color")?;
    
    if bytes.len() != 3 {
        return Err(anyhow::anyhow!("Invalid hex color length: {}", hex));
    }
    
    Ok(Color::Rgb(bytes[0], bytes[1], bytes[2]))
}