use anyhow::Result;
use image::DynamicImage;
use log::debug;

pub struct ImageManager {
    pub image_info: Option<(u32, u32, DynamicImage)>,
    pub image: Option<DynamicImage>,
}

impl ImageManager {
    pub fn new() -> Self {
        Self {
            image_info: None,
            image: None,
        }
    }

    pub fn load_cover_image(&mut self, thumbnail_path: Option<&std::path::PathBuf>) -> Result<()> {
        self.clear(); // Nettoyer l'état avant de charger une nouvelle image
        if let Some(thumb_path) = thumbnail_path {
            debug!("Chargement de l'image de couverture depuis {:?}", thumb_path);
            match crate::util::load_image_info(thumb_path) {
                Ok((width, height, img)) => {
                    self.image_info = Some((width, height, img.clone()));
                    self.image = Some(img);
                    debug!("Image de couverture chargée avec succès");
                }
                Err(e) => {
                    debug!("Échec du chargement de l'image: {}", e);
                    self.image_info = None;
                    self.image = None;
                }
            }
        } else {
            debug!("Aucune image de couverture trouvée");
            self.image_info = None;
            self.image = None;
        }
        
        Ok(())
    }

    pub fn clear(&mut self) {
        debug!("Nettoyage de l'état de l'image");
        self.image_info = None;
        self.image = None;
    }
}