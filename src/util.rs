use anyhow::Result;
use image::{DynamicImage, GenericImageView};
use std::path::Path;
use log::debug;

pub fn load_image_info<P: AsRef<Path>>(path: P) -> Result<(u32, u32, DynamicImage)> {
    let path = path.as_ref();
    debug!("Chargement de l'image: {:?}", path);
    
    // Vérifier que le fichier existe
    if !path.exists() {
        debug!("Le fichier image n'existe pas: {:?}", path);
        return Err(anyhow::anyhow!("Le fichier image n'existe pas: {:?}", path));
    }
    
    // Vérifier la taille du fichier
    let file_size = std::fs::metadata(path)?.len();
    debug!("Taille du fichier image: {} octets", file_size);
    
    if file_size == 0 {
        debug!("Le fichier image est vide!");
        return Err(anyhow::anyhow!("Le fichier image est vide!"));
    }
    
    // Charger l'image
    let img = image::open(path).map_err(|e| {
        debug!("Erreur lors du chargement de l'image: {}", e);
        anyhow::anyhow!("Erreur lors du chargement de l'image: {}", e)
    })?;
    
    let width = img.width();
    let height = img.height();
    debug!("Dimensions de l'image: {}x{}", width, height);
    
    Ok((width, height, img))
}

pub fn image_to_ascii<P: AsRef<Path>>(path: P, width: u32) -> Result<String> {
    let path = path.as_ref();
    debug!("Generating ASCII art for image: {:?}", path);
    
    if !path.exists() {
        debug!("Image file does not exist: {:?}", path);
        return Err(anyhow::anyhow!("Image file does not exist: {:?}", path));
    }
    
    let img = image::open(path)?;
    
    let (img_width, img_height) = img.dimensions();
    debug!("Image dimensions: {}x{}", img_width, img_height);
    
    let height = (width as f32 * img_height as f32 / img_width as f32) as u32;
    debug!("Resizing to {}x{}", width, height);
    
    let img = img.resize(width, height, image::imageops::FilterType::Nearest);
    
    let ascii_chars = [' ', '.', ':', '-', '=', '+', '*', '#', '%', '@'];
    
    debug!("Using {} ASCII characters for rendering", ascii_chars.len());
    let mut ascii = String::new();
    
    for y in 0..height {
        for x in 0..width {
            let pixel = img.get_pixel(x, y);
            let intensity = pixel[0] as f32 * 0.299 + pixel[1] as f32 * 0.587 + pixel[2] as f32 * 0.114;
            let adjusted_intensity = (intensity / 255.0).powf(0.8);
            let index = (adjusted_intensity * (ascii_chars.len() - 1) as f32) as usize;
            ascii.push(ascii_chars[index]);
            ascii.push(ascii_chars[index]);
        }
        ascii.push('\n');
    }
    
    debug!("ASCII art generated, length: {}", ascii.len());
    Ok(ascii)
}