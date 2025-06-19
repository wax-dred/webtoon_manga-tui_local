use anyhow::Result;
use image::{DynamicImage, GenericImageView};
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

/// Chaque pixel est représenté par 2 caractères horizontaux pour un meilleur aspect ratio.
pub fn image_to_ascii<P: AsRef<Path>>(path: P, width: u32) -> Result<String> {
    let path = path.as_ref();
    debug!("Generating ASCII art for image: {:?}", path);

    if !path.exists() {
        return Err(anyhow::anyhow!("Image file does not exist: {:?}", path));
    }

    let img = image::open(path)?;
    let (img_width, img_height) = img.dimensions();
    let height = (width as f32 * img_height as f32 / img_width as f32) as u32;
    let img = img.resize(width, height, image::imageops::FilterType::Nearest);

    let ascii_chars = [' ', '.', ':', '-', '=', '+', '*', '#', '%', '@'];
    let mut ascii = Vec::with_capacity((width * height * 2 + height) as usize);

    for y in 0..height {
        for x in 0..width {
            let pixel = img.get_pixel(x, y);
            let intensity =
                pixel[0] as f32 * 0.299 + pixel[1] as f32 * 0.587 + pixel[2] as f32 * 0.114;
            let adjusted_intensity = (intensity / 255.0).powf(0.8);
            let index = (adjusted_intensity * (ascii_chars.len() - 1) as f32) as usize;
            ascii.push(ascii_chars[index]);
            ascii.push(ascii_chars[index]);
        }
        ascii.push('\n');
    }

    let result = String::from_iter(ascii);
    debug!("ASCII art generated, length: {}", result.len());
    Ok(result)
}
