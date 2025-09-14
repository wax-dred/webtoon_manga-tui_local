use ratatui::Frame;
use crate::app::App;
use crate::ui_modern;

pub fn draw(f: &mut Frame, app: &mut App) {
    ui_modern::draw_modern(f, app);
}