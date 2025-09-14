use anyhow::Result;
use image::{DynamicImage};
use log::debug;
use std::path::{Path, PathBuf};

pub fn expand_path<P: AsRef<Path>>(path: P) -> PathBuf {
    let path_str = path.as_ref().to_string_lossy();
    let expanded = shellexpand::tilde(&path_str);
    PathBuf::from(expanded.to_string())
}

pub fn load_image_info<P: AsRef<Path>>(path: P) -> Result<(u32, u32, DynamicImage)> {
    let path = path.as_ref();
    debug!("Loading image: {:?}", path);
    let img = image::open(path).map_err(|e| anyhow::anyhow!("Failed to load image: {}", e))?;
    let (width, height) = (img.width(), img.height());
    debug!("Image dimensions: {}x{}", width, height);
    Ok((width, height, img))
}


