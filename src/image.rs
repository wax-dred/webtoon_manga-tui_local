use image::DynamicImage;

pub struct ImageManager {
    pub image_info: Option<(u32, u32, DynamicImage)>,
}

impl ImageManager {
    pub fn new() -> Self {
        Self { image_info: None }
    }

    pub fn clear(&mut self) {
        self.image_info = None;
    }
}