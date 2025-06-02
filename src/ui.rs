use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect, Margin},
    style::{Modifier, Style, Color},
    text::{Line, Span, Text},
    widgets::{Block, Borders, List, ListItem, Paragraph, Wrap, Scrollbar, ScrollbarOrientation},
    Frame,
};
use ratatui_image::StatefulImage;
use log::debug;
use std::cmp;
use std::path::PathBuf;

use crate::app::{App, AppState, InputField};
use crate::util;
use crate::manga::Manga;

pub fn draw(f: &mut Frame, app: &mut App) {
    let area = f.area();
    
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(1),
            Constraint::Length(1),
        ])
        .split(area);
    
    let title = format!(" Manga Reader ");
    let title = Paragraph::new(title)
        .style(Style::default().fg(app.theme.foreground))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[3]))
                .style(Style::default().bg(app.theme.background)),
        )
        .alignment(Alignment::Center);
    f.render_widget(title, chunks[0]);
    
    match app.state {
        AppState::BrowseManga | AppState::DownloadInput | AppState::Downloading => {
            draw_browse(f, app, chunks[1])
        }
        AppState::ViewMangaDetails => draw_details(f, app, chunks[1]),
        AppState::Settings => draw_settings(f, app, chunks[1]),
    };
    
    let status = format!(" {} ", app.status);
    let status = Paragraph::new(status)
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Left)
        .block(
            Block::default()
                .borders(Borders::NONE)
                .style(Style::default().bg(app.theme.background)),
        );
    let status_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(70),
            Constraint::Percentage(30),
        ])
        .split(chunks[2]);
    
    f.render_widget(status, status_chunks[0]);
    
    let keys = match app.state {
        AppState::BrowseManga => {
            if app.is_manga_list_focused {
                "Tab:Focus Chapters j/k:Nav r:Refresh c:Config d:Download ?:Help"
            } else {
                "Tab:Focus Manga j/k:Nav Enter:Read o:Open m:Mark ?:Help"
            }
        }
        AppState::ViewMangaDetails => "j/k:Nav Enter:Open o:Open m:Mark d:Download Esc:Back",
        AppState::Settings => "Enter:Modify Esc:Back",
        AppState::DownloadInput => "Tab:Switch Field Enter:Download Esc:Cancel",
        AppState::Downloading => "Esc:Cancel r:Refresh j/k:Scroll",
    };
    
    let keys_widget = Paragraph::new(keys)
        .style(Style::default().fg(app.theme.colors[2]))
        .alignment(Alignment::Right)
        .block(Block::default().borders(Borders::NONE));
    
    f.render_widget(keys_widget, status_chunks[1]);
    
    if app.show_help {
        draw_help_overlay(f, app, area);
    }
}

fn render_cover_image(f: &mut Frame, app: &mut App, cover_area: Rect, thumbnail_path: Option<&PathBuf>) {
    let cover_block = Block::default()
        .title(" Cover ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]));
    f.render_widget(&cover_block, cover_area);
    let inner_area = cover_block.inner(cover_area);

    if app.config.settings.enable_image_rendering {
        debug!("Cover area dimensions: width={}, height={}", inner_area.width, inner_area.height);
        if let Some(state) = &mut app.image_state {
            let image_widget = StatefulImage::new(None);
            f.render_stateful_widget(image_widget, inner_area, state);
        } else if let Some(thumb_path) = thumbnail_path {
            let ascii_width = cmp::min(100, inner_area.width as u32);
            let placeholder = match util::image_to_ascii(thumb_path, ascii_width) {
                Ok(ascii) => ascii,
                Err(e) => {
                    debug!("Failed to generate ASCII: {}", e);
                    "No cover image available".to_string()
                }
            };
            let image_text = Text::from(placeholder);
            let image_paragraph = Paragraph::new(image_text)
                .wrap(Wrap { trim: true })
                .alignment(Alignment::Center);
            f.render_widget(image_paragraph, inner_area);
        }
    }
}

fn draw_browse(f: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(25),
            Constraint::Percentage(35),
            Constraint::Percentage(40),
        ])
        .split(area);

    let filtered_mangas_vec: Vec<&Manga> = app.filtered_mangas().collect();
    let items: Vec<ListItem> = filtered_mangas_vec
        .iter()
        .map(|manga| {
            let (read, total, progress) = app.manga_progress(manga);
            let display_name = manga.name.replace("_", " ");
            let title = format!("{} ({}/{})", display_name, read, total);

            let available_width = (chunks[0].width.saturating_sub(4)) as usize;
            let bar_width = 20.min(available_width);
            let filled = (progress * bar_width as f32) as usize;
            let empty = bar_width.saturating_sub(filled);
            let progress_bar: String = "━".repeat(filled) + &"━".repeat(empty);
            let progress_bar_line = Line::from(vec![Span::styled(
                format!("{}", progress_bar),
                Style::default().fg(if progress < 0.1 {
                    app.theme.colors[1]
                } else if progress < 0.25 {
                    app.theme.colors[3]
                } else if progress < 0.5 {
                    app.theme.colors[5]
                } else if progress < 0.75 {
                    app.theme.colors[11]
                } else {
                    app.theme.colors[13]
                }),
            )]);

            ListItem::new(vec![
                Line::from(vec![Span::styled(title, Style::default().fg(app.theme.foreground))]),
                Line::from(vec![
                    Span::styled(format!("{:.0}% ", progress * 100.0), Style::default().fg(if progress < 0.1 {
                        app.theme.colors[1]
                    } else if progress < 0.25 {
                        app.theme.colors[3]
                    } else if progress < 0.5 {
                        app.theme.colors[5]
                    } else if progress < 0.75 {
                        app.theme.colors[11]
                    } else {
                        app.theme.colors[13]
                    })),
                    Span::styled(
                        format!("- {} chapters", manga.chapters.len()),
                        Style::default().fg(app.theme.colors[11]),
                    ),
                ]),
                progress_bar_line,
            ])
        })
        .collect();

    let manga_list = List::new(items)
        .block(
            Block::default()
                .title(" Manga List ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(
                    if app.is_manga_list_focused {
                        app.theme.colors[13]
                    } else {
                        app.theme.colors[9]
                    },
                )),
        )
        .highlight_style(
            Style::default()
                .bg(app.theme.colors[8])
                .fg(app.theme.background)
                .add_modifier(Modifier::BOLD),
        );

    let mut state = ratatui::widgets::ListState::default();
    let filtered_mangas_vec: Vec<&Manga> = app.filtered_mangas().collect();
    if let Some(idx) = app.selected_manga {
        if idx < filtered_mangas_vec.len() {
            state.select(Some(idx));
        }
    }
    f.render_stateful_widget(manga_list, chunks[0], &mut state);

    let chapter_area = chunks[1];
    if let Some(manga) = app.current_manga() {
        let items: Vec<ListItem> = manga
            .chapters
            .iter()
            .map(|chapter| {
                let mut style = Style::default().fg(app.theme.foreground);
                let mut prefix = "☐ ";
                if chapter.read {
                    style = Style::default().fg(app.theme.colors[13]);
                    prefix = "✓ ";
                } else if chapter.last_page_read.is_some() {
                    style = Style::default().fg(app.theme.colors[12]);
                    prefix = "▶ ";
                }
                ListItem::new(vec![
                    Line::from(vec![Span::styled(
                        format!("{}{} - {}", prefix, chapter.number_display(), chapter.title),
                        style,
                    )]),
                    Line::from(vec![Span::styled(
                        format!(
                            "   {}{}",
                            chapter.size_display(),
                            chapter.last_page_read.map_or(String::new(), |page| {
                                chapter.full_pages_read.map_or(
                                    format!(" - Page {}", page),
                                    |total| format!(" - Page {} / {}", page, total)
                                )
                            })
                        ),
                        Style::default().fg(app.theme.colors[11]),
                    )]),
                ])
            })
            .collect();
        let display_name = manga.name.replace("_", " ");
        let chapter_list = List::new(items)
            .block(
                Block::default()
                    .title(format!(" {} - Chapters ", display_name))
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(
                        if !app.is_manga_list_focused {
                            app.theme.colors[2]
                        } else {
                            app.theme.colors[14]
                        },
                    )),
            )
            .highlight_style(
                Style::default()
                    .bg(app.theme.colors[11])
                    .fg(app.theme.background)
                    .add_modifier(Modifier::BOLD),
            );

        let mut chapter_state = ratatui::widgets::ListState::default();
        if let Some(idx) = app.selected_chapter {
            if idx < manga.chapters.len() {
                chapter_state.select(Some(idx));
                debug!("Rendering chapter list with selected index: {}", idx);
            }
        }
        f.render_stateful_widget(chapter_list, chapter_area, &mut chapter_state);
    } else {
        let message = "No manga selected or no chapters available";
        let paragraph = Paragraph::new(message)
            .block(
                Block::default()
                    .title(" Chapters ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[8])),
            )
            .style(Style::default().fg(app.theme.foreground))
            .alignment(Alignment::Center);
        f.render_widget(paragraph, chapter_area);
    }

    let manga_info_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage(60),
            Constraint::Percentage(40),
        ])
        .split(chunks[2]);

    let cover_synopsis_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(40),
            Constraint::Percentage(60),
        ])
        .split(manga_info_chunks[0]);

    let (thumbnail_path, synopsis) = match app.current_manga() {
        Some(manga) => (
            manga.thumbnail.clone(),
            manga.synopsis.as_ref().unwrap_or(&"No synopsis available.".to_string()).clone(),
        ),
        None => (None, "No manga selected.".to_string()),
    };

    render_cover_image(f, app, cover_synopsis_chunks[0], thumbnail_path.as_ref());

    let synopsis_widget = Paragraph::new(synopsis)
        .block(
            Block::default()
                .title(" Synopsis ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[11])),
        )
        .style(Style::default().fg(app.theme.foreground))
        .wrap(Wrap { trim: true });
    f.render_widget(synopsis_widget, cover_synopsis_chunks[1]);

    if app.state == AppState::DownloadInput {
        draw_download_input(f, app, manga_info_chunks[1]);
    } else if app.state == AppState::Downloading {
        draw_downloading(f, app, manga_info_chunks[1]);
    }
}

fn draw_details(f: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(40),
            Constraint::Percentage(60),
        ])
        .split(area);

    let (thumbnail_path, synopsis) = match app.current_manga() {
        Some(manga) => (
            manga.thumbnail.clone(),
            manga.synopsis.as_ref().unwrap_or(&"No synopsis available.".to_string()).clone(),
        ),
        None => (None, "No manga selected.".to_string()),
    };

    render_cover_image(f, app, chunks[0], thumbnail_path.as_ref());

    let right_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage(40),
            Constraint::Percentage(60),
        ])
        .split(chunks[1]);

    let synopsis_widget = Paragraph::new(synopsis)
        .block(
            Block::default()
                .title(" Synopsis ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[11])),
        )
        .style(Style::default().fg(app.theme.foreground))
        .wrap(Wrap { trim: true });
    f.render_widget(synopsis_widget, right_chunks[0]);

    if let Some(manga) = app.current_manga() {
        let items: Vec<ListItem> = manga
            .chapters
            .iter()
            .map(|chapter| {
                let mut style = Style::default().fg(app.theme.foreground);
                let mut prefix = "☐ ";
                if chapter.read {
                    style = Style::default().fg(app.theme.colors[13]);
                    prefix = "✓ ";
                } else if chapter.last_page_read.is_some() {
                    style = Style::default().fg(app.theme.colors[12]);
                    prefix = "▶ ";
                }
                ListItem::new(vec![
                    Line::from(vec![Span::styled(
                        format!("{}{} - {}", prefix, chapter.number_display(), chapter.title),
                        style,
                    )]),
                    Line::from(vec![Span::styled(
                        format!(
                            "   {}{}",
                            chapter.size_display(),
                            chapter.last_page_read.map_or(String::new(), |page| {
                                chapter.full_pages_read.map_or(
                                    format!(" - Page {}", page),
                                    |total| format!(" - Page {} / {}", page, total)
                                )
                            })
                        ),
                        Style::default().fg(app.theme.colors[11]),
                    )]),
                ])
            })
            .collect();
        let display_name = manga.name.replace("_", " ");
        let chapter_list = List::new(items)
            .block(
                Block::default()
                    .title(format!(" {} - Chapters ", display_name))
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[2])),
            )
            .highlight_style(
                Style::default()
                    .bg(app.theme.colors[11])
                    .fg(app.theme.background)
                    .add_modifier(Modifier::BOLD),
            );

        let mut chapter_state = ratatui::widgets::ListState::default();
        if let Some(idx) = app.selected_chapter {
            if idx < manga.chapters.len() {
                chapter_state.select(Some(idx));
            }
        }
        f.render_stateful_widget(chapter_list, right_chunks[1], &mut chapter_state);
    } else {
        let message = "No manga selected or no chapters available";
        let paragraph = Paragraph::new(message)
            .block(
                Block::default()
                    .title(" Chapters ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[8])),
            )
            .style(Style::default().fg(app.theme.foreground))
            .alignment(Alignment::Center);
        f.render_widget(paragraph, right_chunks[1]);
    }
}

fn draw_download_input(f: &mut Frame, app: &mut App, area: Rect) {
    let block = Block::default()
        .title(" Download Manga ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]));
    f.render_widget(block.clone(), area);
    
    let inner_area = block.inner(area);
    
    let input_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Length(3),
        ])
        .split(inner_area);
    
    let url_style = if app.input_field == InputField::Url {
        Style::default().fg(app.theme.colors[13]).add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(app.theme.foreground)
    };
    
    let url_input = Paragraph::new(app.download_url.as_str())
        .style(url_style)
        .block(
            Block::default()
                .title(" URL ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[3])),
        );
    f.render_widget(url_input, input_chunks[0]);
    
    let chapters_style = if app.input_field == InputField::Chapters {
        Style::default().fg(app.theme.colors[13]).add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(app.theme.foreground)
    };
    
    let chapters_input = Paragraph::new(app.selected_chapters_input.as_str())
        .style(chapters_style)
        .block(
            Block::default()
                .title(" Chapters (e.g., 1,2,3 or 1-3) ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[3])),
        );
    f.render_widget(chapters_input, input_chunks[1]);
}

fn draw_downloading(f: &mut Frame, app: &mut App, area: Rect) {
    let download_block = Block::default()
        .title(" Download ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]));
    
    f.render_widget(download_block.clone(), area);
    
    let inner_area = download_block.inner(area);
    
    let logs_text: Vec<Line> = app.download_logs
        .iter()
        .map(|log| Line::from(log.as_str()))
        .collect();
    
    let log_count = app.download_logs.len();
    let mut is_new_download = false;
    for log in app.download_logs.iter().rev() {
        if log.contains("Download Complete!") {
            app.last_download_complete = true;
        } else if log.contains("Downloading Chapter") {
            if let Some(chap_str) = log.split(" of ").next() {
                if let Some(num_str) = chap_str.split("Chapter ").last() {
                    if let Ok(num) = num_str.trim().parse::<usize>() {
                        if num == 1 && app.last_download_complete {
                            is_new_download = true;
                            break;
                        }
                    }
                }
            }
        }
    }
    if is_new_download {
        debug!("New download detected, resetting progress");
        app.last_download_complete = false;
    } else if log_count < app.last_log_count {
        debug!("Log count decreased, resetting progress");
    }
    app.last_log_count = log_count;

    let (total_chapters, completed_chapters, progress, _current_chapter_images, _total_images_in_current_chapter, current_chapter) = app.calculate_download_progress();
    
    let logs_area = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(1),
            Constraint::Length(1),
        ])
        .split(inner_area);

    let logs_content_area = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Min(1),
            Constraint::Length(1),
        ])
        .split(logs_area[0])[0];

    if app.is_downloading && !app.has_user_scrolled && logs_text.len() > logs_content_area.height as usize {
        app.scroll_offset = logs_text.len().saturating_sub(logs_content_area.height as usize) as u16;
    }

    let live_indicator = if app.download_finished {
        format!("Download : {} (finished)", app.current_download_manga_name)
    } else {
        if app.current_page % 2 == 0 {
            format!("Download : {} live ─_", app.current_download_manga_name)
        } else {
            format!("Download : {} live _─", app.current_download_manga_name)
        }
    };

    let logs_widget = Paragraph::new(Text::from(logs_text.clone()))
        .style(Style::default().fg(app.theme.foreground))
        .wrap(Wrap { trim: false })
        .scroll((app.scroll_offset, 0))
        .block(
            Block::default()
                .title(live_indicator)
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[13]))
        );

    f.render_widget(logs_widget, logs_content_area);

    if logs_text.len() > logs_content_area.height as usize {
        let mut scrollbar_state = ratatui::widgets::ScrollbarState::default()
            .content_length(logs_text.len())
            .viewport_content_length(logs_content_area.height as usize)
            .position(app.scroll_offset as usize);

        let scrollbar = Scrollbar::default()
            .orientation(ScrollbarOrientation::VerticalRight)
            .style(Style::default().fg(app.theme.colors[4]));

        f.render_stateful_widget(
            scrollbar,
            logs_area[0].inner(Margin {
                vertical: 1,
                horizontal: 0,
            }),
            &mut scrollbar_state,
        );
    }

    let bar_width = (logs_area[1].width.saturating_sub(10)) as usize;
    let filled = (progress / 100.0 * bar_width as f32) as usize;
    let empty = bar_width.saturating_sub(filled);
    let progress_color = if progress >= 75.0 {
        Color::Rgb(0, 255, 32)
    } else if progress >= 50.0 {
        Color::Rgb(0, 241, 255)
    } else if progress >= 25.0 {
        Color::Rgb(150, 0, 255)
    } else {
        Color::Rgb(255, 0, 196)
    };
    let progress_bar = format!(
        "Chapitre {} : {:.0}% {} ({}/{})",
        current_chapter,
        progress,
        "━".repeat(filled) + &" ".repeat(empty),
        completed_chapters,
        total_chapters
    );
    let progress_line = Line::from(vec![Span::styled(
        progress_bar,
        Style::default().fg(progress_color)
    )]);
    let progress_widget = Paragraph::new(Text::from(vec![progress_line]))
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Left);
    f.render_widget(progress_widget, logs_area[1]);
}

fn draw_settings(f: &mut Frame, app: &mut App, area: Rect) {
    let block = Block::default()
        .title(" Settings ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]));
    f.render_widget(block.clone(), area);
    
    let inner_area = block.inner(area);
    
    let settings_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
        ])
        .split(inner_area);
    
    let manga_dir_input = Paragraph::new(app.filter.as_str())
        .style(Style::default().fg(app.theme.colors[13]).add_modifier(Modifier::BOLD))
        .block(
            Block::default()
                .title(" Manga Directory ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[3])),
        );
    f.render_widget(manga_dir_input, settings_chunks[0]);
}

fn draw_help_overlay(f: &mut Frame, app: &mut App, area: Rect) {
    let popup_area = centered_rect(60, 60, area);
    
    let block = Block::default()
        .title(" Help ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]))
        .style(Style::default().bg(app.theme.background));
    f.render_widget(block.clone(), popup_area);
    
    let inner_area = block.inner(popup_area);
    
    let help_text = vec![
        Line::from("Navigation:"),
        Line::from("  j/k or Up/Down: Move up/down"),
        Line::from("  Tab: Switch focus (Manga/Chapters)"),
        Line::from("  Left: Focus Manga List"),
        Line::from("  Right: Focus Chapter List"),
        Line::from(""),
        Line::from("Actions:"),
        Line::from("  Enter/o: Open chapter with external reader"),
        Line::from("  m: Toggle chapter read/unread"),
        Line::from("  M: Mark all chapters as unread"),
        Line::from("  v: View manga details"),
        Line::from("  r: Refresh manga list"),
        Line::from("  c: Open settings"),
        Line::from("  d: Start download"),
        Line::from("  /: Filter manga list"),
        Line::from("  ?: Toggle help"),
        Line::from("  q: Quit"),
        Line::from(""),
        Line::from("Download Mode:"),
        Line::from("  Tab: Switch between URL and Chapters"),
        Line::from("  Enter: Start download"),
        Line::from("  Esc: Cancel"),
        Line::from(""),
        Line::from("Downloading:"),
        Line::from("  j/k: Scroll logs"),
        Line::from("  r: Refresh manga list"),
        Line::from("  Esc: Cancel download"),
    ];
    
    let help_widget = Paragraph::new(Text::from(help_text))
        .style(Style::default().fg(app.theme.foreground))
        .wrap(Wrap { trim: true });
    f.render_widget(help_widget, inner_area);
}

fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(r);
    
    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}