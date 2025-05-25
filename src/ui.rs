use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect, Margin},
    style::{Modifier, Style, Color},
    text::{Line, Span, Text},
    widgets::{Block, Borders, List, ListItem, Paragraph, Wrap, Scrollbar, ScrollbarOrientation},
    Frame,
};
use ratatui_image::StatefulImage;
use log::debug;
use unicode_width::{UnicodeWidthStr, UnicodeWidthChar};
use crate::app::{App, AppState, InputField};
use crate::util;
use std::cmp;

pub fn draw(f: &mut Frame, app: &mut App) {
    let area = f.area();
    
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Title
            Constraint::Min(1),    // Content
            Constraint::Length(1), // Status
        ])
        .split(area);
    
    let title = format!(" Manga Reader ");
    let title = Paragraph::new(title)
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Center)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(app.theme.colors[3]))
                .style(Style::default().bg(app.theme.background)),
        );
    f.render_widget(title, chunks[0]);
    
    match app.state {
        AppState::BrowseManga | AppState::DownloadInput | AppState::Downloading => {
            draw_browse(f, app, chunks[1])
        }
        AppState::ViewMangaDetails => draw_details(f, app, chunks[1]),
        AppState::Settings => draw_settings(f, app, chunks[1]),
    }
    
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
            Constraint::Percentage(70),  // Status message
            Constraint::Percentage(30),  // Keyboard shortcuts
        ])
        .split(chunks[2]);
    
    f.render_widget(status, status_chunks[0]);
    
    let keys = match app.state {
        AppState::BrowseManga => {
            if app.is_manga_list_focused {
                "Tab:Focus Chapters j/k:Nav r:Refresh c:Config d:Download ?:Help"
            } else {
                "Tab:Focus Mangas j/k:Nav Enter:Read o:Open m:Mark ?:Help"
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

fn draw_browse(f: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(25),  // Manga list
            Constraint::Percentage(35),  // Chapter list
            Constraint::Percentage(40),  // Manga info (cover + synopsis + download)
        ])
        .split(area);

    let filtered_mangas = app.filtered_mangas();
    let items: Vec<ListItem> = filtered_mangas
        .iter()
        .map(|manga| {
            let (read, total, progress) = app.manga_progress(manga);
            let display_name = manga.name.replace("_", " ");
            let title = format!("{} ({}/{})", display_name, read, total);

            // Calculate progress bar
            let available_width = (chunks[0].width.saturating_sub(4)) as usize;
            let bar_width = 20.min(available_width); // Cap at 20 characters or available width
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
    if let Some(idx) = app.selected_manga {
        if idx < filtered_mangas.len() {
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
                }
                ListItem::new(vec![
                    Line::from(vec![Span::styled(
                        format!("{}{} - {}", prefix, chapter.number_display(), chapter.title),
                        style,
                    )]),
                    Line::from(vec![Span::styled(
                        format!(
                            "   {} - {} pages - {}",
                            chapter.date_display(),
                            chapter.pages,
                            chapter.size_display()
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
            } else {
                debug!("Selected chapter index {} out of bounds for {} chapters", idx, manga.chapters.len());
            }
        } else {
            debug!("No selected chapter index");
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
            Constraint::Percentage(60),  // Cover and Synopsis
            Constraint::Percentage(40),  // Download section
        ])
        .split(chunks[2]);

    let cover_synopsis_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(40),
            Constraint::Percentage(60),
        ])
        .split(manga_info_chunks[0]);

    let cover_block = Block::default()
        .title(" Cover ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[11]));
    let cover_area = cover_block.inner(cover_synopsis_chunks[0]);
    f.render_widget(&cover_block, cover_synopsis_chunks[0]);

    let (thumbnail_path, synopsis) = match app.current_manga() {
        Some(manga) => (
            manga.thumbnail.clone(),
            manga.synopsis.as_ref().unwrap_or(&"No synopsis available.".to_string()).clone(),
        ),
        None => (None, "No manga selected.".to_string()),
    };

    if app.config.settings.enable_image_rendering {
        debug!(
            "Cover area dimensions: width={}, height={}",
            cover_area.width, cover_area.height
        );
        if let Some(state) = &mut app.image_state {
            let image_widget = StatefulImage::new(None);
            f.render_stateful_widget(image_widget, cover_area, state);
        } else if let Some(thumb_path) = &thumbnail_path {
            let ascii_width = cmp::min(100, cover_area.width as u32);
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
            f.render_widget(image_paragraph, cover_area);
        }
    }

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

    // Download section
    if app.state == AppState::DownloadInput {
        draw_download_input(f, app, manga_info_chunks[1]);
    } else if app.state == AppState::Downloading {
        let download_block = Block::default()
            .title(" Download ")
            .borders(Borders::ALL)
            .border_style(Style::default().fg(app.theme.colors[11]));
        
        f.render_widget(download_block.clone(), manga_info_chunks[1]);
        
        let inner_area = download_block.inner(manga_info_chunks[1]);
        
        let logs_text: Vec<Line> = app.download_logs
            .iter()
            .map(|log| Line::from(log.as_str()))
            .collect();
        
        // Variables persistantes pour détecter un nouveau téléchargement
        static mut LAST_LOG_COUNT: usize = 0;
        static mut LAST_DOWNLOAD_COMPLETE: bool = false;

        // Calculer l'avancement du téléchargement
        let mut total_chapters = 1; // Valeur par défaut
        let mut completed_chapters = 0; // Compter les chapitres terminés
        let mut current_chapter_images = 0; // Nombre d'images téléchargées dans le chapitre en cours
        let mut total_images_in_current_chapter = 1; // Nombre total d'images dans le chapitre en cours
        let mut current_chapter = 1; // Chapitre en cours (par défaut 1)
        let mut last_detected_chapter = 0; // Suivre le dernier chapitre détecté pour réinitialisation
        let mut progress = 0.0;

        // Vérifier si un nouveau téléchargement a démarré
        let log_count = app.download_logs.len();
        let mut is_new_download = false;
        for log in app.download_logs.iter().rev() { // Parcourir en sens inverse pour détecter les derniers événements
            if log.contains("Download Complete!") {
                unsafe { LAST_DOWNLOAD_COMPLETE = true; }
            } else if log.contains("Downloading Chapter") {
                if let Some(chap_str) = log.split(" of ").next() {
                    if let Some(num_str) = chap_str.split("Chapter ").last() {
                        if let Ok(num) = num_str.trim().parse::<usize>() {
                            if num == 1 && unsafe { LAST_DOWNLOAD_COMPLETE } {
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
            completed_chapters = 0;
            current_chapter_images = 0;
            total_images_in_current_chapter = 1;
            current_chapter = 1;
            last_detected_chapter = 0;
            unsafe { LAST_DOWNLOAD_COMPLETE = false; } // Réinitialiser après détection
        } else if log_count < unsafe { LAST_LOG_COUNT } {
            debug!("Log count decreased, resetting progress");
            completed_chapters = 0;
            current_chapter_images = 0;
            total_images_in_current_chapter = 1;
            current_chapter = 1;
            last_detected_chapter = 0;
        }
        unsafe {
            LAST_LOG_COUNT = log_count;
        }

        // Extraire le nombre total de chapitres depuis selected_chapters_input
        if !app.selected_chapters_input.is_empty() {
            let chapters: Vec<&str> = app.selected_chapters_input.split(',').collect();
            total_chapters = chapters.len().max(1); // Nombre de chapitres demandés (ex. "1,2" → 2)
            debug!("Total chapters from input: {}", total_chapters);
        } else {
            debug!("No chapters input, using default total_chapters = 1");
        }

        // Parcourir les logs pour détecter la progression
        for log in &app.download_logs {
            debug!("Download log: {}", log); // Ajouter pour débogage

            // Détecter le chapitre en cours et réinitialiser si nécessaire
            if log.contains("Downloading Chapter") {
                if let Some(chap_str) = log.split(" of ").next() {
                    if let Some(num_str) = chap_str.split("Chapter ").last() {
                        if let Ok(num) = num_str.trim().parse::<usize>() {
                            current_chapter = num;
                            // Réinitialiser les images pour un nouveau chapitre
                            if current_chapter != last_detected_chapter {
                                debug!("New chapter started: {}, resetting image progress", current_chapter);
                                current_chapter_images = 0;
                                total_images_in_current_chapter = 1; // Valeur par défaut jusqu'à détection
                                last_detected_chapter = current_chapter;
                            }
                            debug!("Current chapter: {}", current_chapter);
                        }
                    }
                }
            }

            // Détecter le nombre total d'images dans le chapitre
            if log.contains("Found") && log.contains("images for Chapter") {
                if let Some(num_str) = log.split("Found ").nth(1) {
                    if let Some(num) = num_str.split(" images").next() {
                        if let Ok(num) = num.trim().parse::<usize>() {
                            total_images_in_current_chapter = num.max(1);
                            debug!("Total images in current chapter: {}", total_images_in_current_chapter);
                        }
                    }
                }
            }

            // Compter les images téléchargées dans le chapitre en cours
            if log.contains("Downloaded image") {
                if let Some(img_str) = log.split("Downloaded image ").nth(1) {
                    if let Some(num_str) = img_str.split('/').next() {
                        if let Ok(num) = num_str.trim().parse::<usize>() {
                            current_chapter_images = num;
                            debug!("Images downloaded in current chapter: {}/{}", current_chapter_images, total_images_in_current_chapter);
                        }
                    }
                }
            }

            // Détecter un chapitre terminé
            if log.contains(".cbr created with") {
                completed_chapters += 1;
                current_chapter_images = total_images_in_current_chapter; // S'assurer que la progression du chapitre est à 100 %
                debug!("Detected completed chapter, total completed: {}", completed_chapters);
            }
        }

        // Calculer la progression globale
        if total_chapters > 0 {
            let chapter_progress = completed_chapters as f32 / total_chapters as f32;
            let image_progress = if completed_chapters < current_chapter {
                (current_chapter_images as f32 / total_images_in_current_chapter as f32) / total_chapters as f32
            } else {
                0.0
            };
            progress = ((chapter_progress + image_progress) * 100.0).min(100.0).max(0.0);
            debug!("Progress calculated: {}% (completed chapters: {}, image progress: {}/{})", 
                progress, completed_chapters, current_chapter_images, total_images_in_current_chapter);
        } else {
            debug!("Total chapters is 0, progress set to 0%");
        }
        
        // Ajuster l'espace pour la barre de progression et les logs
        let logs_area = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(1),      // Logs
            Constraint::Length(1),   // Progress bar
        ])
        .split(inner_area);

        let logs_content_area = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Min(1),      // Logs
            Constraint::Length(1),   // Scrollbar
        ])
        .split(logs_area[0])[0]; // Première partie pour les logs

        // Si le téléchargement est en cours, faire défiler automatiquement à la dernière ligne
        if app.is_downloading && !app.has_user_scrolled && logs_text.len() > logs_content_area.height as usize {
        app.scroll_offset = logs_text.len().saturating_sub(logs_content_area.height as usize) as u16;
        }

        let mut logs_widget = Paragraph::new(Text::from(logs_text.clone()))
        .style(Style::default().fg(app.theme.foreground))
        .wrap(Wrap { trim: false })
        .scroll((app.scroll_offset, 0));

        // Calculer l'avancement du téléchargement
        let mut completed_chapters = 0; // Compter les chapitres terminés
        let mut current_chapter_images = 0; // Nombre d'images téléchargées dans le chapitre en cours
        let mut total_images_in_current_chapter = 1; // Nombre total d'images dans le chapitre en cours
        let mut current_chapter = 1; // Chapitre en cours (par défaut 1)

        // Extraire le nombre total de chapitres depuis selected_chapters_input
        if !app.selected_chapters_input.is_empty() {
        let chapters: Vec<&str> = app.selected_chapters_input.split(',').collect();
        total_chapters = chapters.len().max(1); // Nombre de chapitres demandés (ex. "1,2" → 2)
        debug!("Total chapters from input: {}", total_chapters);
        } else {
        debug!("No chapters input, using default total_chapters = 1");
        }

        // Parcourir les logs pour détecter la progression
        let mut current_chapter_detected = false;
        for log in &app.download_logs {
        debug!("Download log: {}", log);

        // Détecter le chapitre en cours
        if log.contains("Downloading Chapter") {
            if let Some(chap_str) = log.split(" of ").next() {
                if let Some(num_str) = chap_str.split("Chapter ").last() {
                    if let Ok(num) = num_str.trim().parse::<usize>() {
                        // Si on détecte un nouveau chapitre, réinitialiser les compteurs pour ce chapitre
                        if current_chapter != num {
                            current_chapter = num;
                            current_chapter_images = 0; // Réinitialiser les images téléchargées
                            total_images_in_current_chapter = 1; // Réinitialiser jusqu'à détection
                            current_chapter_detected = true;
                            debug!("New chapter started: {}, resetting image progress", current_chapter);
                        }
                    }
                }
            }
        }

        // Détecter le nombre total d'images dans le chapitre
        if log.contains("Found") && log.contains("images for Chapter") {
            if let Some(num_str) = log.split("Found ").nth(1) {
                if let Some(num) = num_str.split(" images").next() {
                    if let Ok(num) = num.trim().parse::<usize>() {
                        total_images_in_current_chapter = num.max(1);
                        debug!("Total images in current chapter: {}", total_images_in_current_chapter);
                    }
                }
            }
        }

        // Compter les images téléchargées dans le chapitre en cours
        if log.contains("Downloaded image") {
            if let Some(img_str) = log.split("Downloaded image ").nth(1) {
                if let Some(num_str) = img_str.split('/').next() {
                    if let Ok(num) = num_str.trim().parse::<usize>() {
                        current_chapter_images = num;
                        debug!("Images downloaded in current chapter: {}/{}", current_chapter_images, total_images_in_current_chapter);
                    }
                }
            }
        }

        // Détecter un chapitre terminé
        if log.contains(".cbr created with") {
            completed_chapters += 1;
            current_chapter_images = total_images_in_current_chapter; // S'assurer que la progression du chapitre est à 100%
            debug!("Detected completed chapter, total completed: {}", completed_chapters);
        }
        }

        // Calculer la progression pour le chapitre en cours uniquement
        if current_chapter_detected && total_images_in_current_chapter > 0 {
        progress = (current_chapter_images as f32 / total_images_in_current_chapter as f32) * 100.0;
        debug!("Progress for current chapter {}: {}%", current_chapter, progress);
        } else {
        progress = 0.0;
        debug!("No chapter detected or no images, progress set to 0%");
        }

        // Modifier le titre avec le nom de l'œuvre
        let live_indicator = if app.download_finished {
            format!("Download : {} (finished)", app.current_download_manga_name)
        } else {
            if app.current_page % 2 == 0 {
                format!("Download : {} live ─_", app.current_download_manga_name)
            } else {
                format!("Download : {} live _─", app.current_download_manga_name)
            }
        };
        logs_widget = logs_widget.block(
        Block::default()
            .title(live_indicator)
            .borders(Borders::ALL)
            .border_style(Style::default().fg(app.theme.colors[13]))
        );

        f.render_widget(logs_widget, logs_content_area);

        // Ajouter une barre de défilement
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

        // Afficher la barre de progression avec un espace après les deux-points
        let bar_width = (logs_area[1].width.saturating_sub(10)) as usize; // Réserver de l'espace pour le texte
        let filled = (progress / 100.0 * bar_width as f32) as usize;
        let empty = bar_width.saturating_sub(filled);
        let progress_color = if progress >= 75.0 {
        Color::Rgb(0, 255, 32) // #00ff20 à 100%
        } else if progress >= 50.0 {
        Color::Rgb(0, 241, 255) // #00f1ff à 75%
        } else if progress >= 25.0 {
        Color::Rgb(150, 0, 255) // #9600ff à 50%
        } else {
        Color::Rgb(255, 0, 196) // #ff00c4 à 25%
        };
        let progress_bar = format!(
        "Chapitre {} : {:.0}% {}",
        current_chapter,
        progress,
        "━".repeat(filled) + &" ".repeat(empty)
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
}

fn draw_details(f: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(70),
            Constraint::Percentage(30),
        ])
        .split(area);
    
    if let Some(manga) = app.current_manga() {
        let items: Vec<ListItem> = manga
            .chapters
            .iter()
            .map(|chapter| {
                let mut style = Style::default().fg(app.theme.colors[2]);
                let mut prefix = "☐ ";
                if chapter.read {
                    style = Style::default().fg(app.theme.colors[12]);
                    prefix = "✓ ";
                }
                ListItem::new(vec![
                    Line::from(vec![
                        Span::styled(
                            format!("{}{} - {}", prefix, chapter.number_display(), chapter.title),
                            style,
                        ),
                    ]),
                    Line::from(vec![
                        Span::styled(
                            format!("   {} - {} pages - {}", 
                                    chapter.date_display(), 
                                    chapter.pages, 
                                    chapter.size_display()),
                            Style::default().fg(app.theme.colors[13]),
                        ),
                    ]),
                ])
            })
            .collect();
        
        let chapter_list = List::new(items)
            .block(
                Block::default()
                    .title(format!(" {} - Chapters ", manga.name))
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[3])),
            )
            .highlight_style(
                Style::default()
                    .bg(app.theme.colors[4])
                    .fg(app.theme.background)
                    .add_modifier(Modifier::BOLD),
            );
        
        let mut state = ratatui::widgets::ListState::default();
        if let Some(idx) = app.selected_chapter {
            if idx < manga.chapters.len() {
                state.select(Some(idx));
            }
        }
        
        f.render_stateful_widget(chapter_list, chunks[0], &mut state);
        
        let cover_height = (app.term_height / 2).max(20).min(40);
        let manga_info_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(cover_height),
                Constraint::Min(1),
            ])
            .split(chunks[1]);
        
        let cover_block = Block::default()
            .title(" Cover ")
            .borders(Borders::ALL)
            .border_style(Style::default().fg(app.theme.colors[4]));
        
        let cover_area = cover_block.inner(manga_info_chunks[0]);
        f.render_widget(&cover_block, manga_info_chunks[0]);
        
        let (thumbnail_path, controls) = match app.current_manga() {
            Some(manga) => (
                manga.thumbnail.clone(),
                vec![format!("Directory: {}", manga.path.display())],
            ),
            None => (None, Vec::new()),
        };
        
        if app.config.settings.enable_image_rendering {
            if let Some(state) = &mut app.image_state {
                let image_widget = StatefulImage::new(None);
                f.render_stateful_widget(image_widget, cover_area, state);
            } else if let Some(thumb_path) = &thumbnail_path {
                let placeholder = match util::image_to_ascii(thumb_path, 100) {
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
                f.render_widget(image_paragraph, cover_area);
            }
        }
        
        let controls_text = Text::from(
            controls
                .iter()
                .map(|s| Line::from(s.as_str()))
                .collect::<Vec<Line>>(),
        );
        
        let controls_widget = Paragraph::new(controls_text)
            .block(
                Block::default()
                    .title(" Controls ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[4])),
            )
            .style(Style::default().fg(app.theme.foreground));
        
        f.render_widget(controls_widget, manga_info_chunks[1]);
    } else {
        let message = "No manga selected or no chapters available";
        let paragraph = Paragraph::new(message)
            .block(
                Block::default()
                    .title(" Chapters ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(app.theme.colors[4])),
            )
            .style(Style::default().fg(app.theme.foreground))
            .alignment(Alignment::Center);
            
        f.render_widget(paragraph, chunks[0]);
    }
}

fn draw_settings(f: &mut Frame, app: &mut App, area: Rect) {
    let settings_block = Block::default()
        .title(" Configuration ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[4]));
    
    f.render_widget(settings_block.clone(), area);
    
    let inner_area = settings_block.inner(area);
    
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // Title
            Constraint::Length(3), // Input field
            Constraint::Min(1),   // Instructions
        ])
        .split(inner_area);
    
    let title = Paragraph::new("Manga Reader Configuration")
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Center);
    
    f.render_widget(title, chunks[0]);
    
    let input_title = if app.input_mode && app.input_field == InputField::MangaDir {
        " Manga folder path (Enter to confirm) "
    } else {
        &format!(" Manga folder: {} ", app.manga_dir.to_string_lossy())
    };
    let input_block = Block::default()
        .title(input_title)
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[4]));
    
    f.render_widget(input_block.clone(), chunks[1]);
    
    let path_text = if app.input_mode && app.input_field == InputField::MangaDir {
        app.filter.clone()
    } else {
        app.manga_dir.to_string_lossy().to_string()
    };
    
    let path_style = if app.input_mode && app.input_field == InputField::MangaDir {
        Style::default().fg(app.theme.colors[2])
    } else {
        Style::default().fg(app.theme.foreground)
    };
    
    let path_widget = Paragraph::new(path_text)
        .style(path_style)
        .wrap(Wrap { trim: false }) // Ensure long paths wrap
        .block(Block::default());
    
    let path_area = chunks[1].inner(Margin {
        horizontal: 1,
        vertical: 1,
    });
    
    f.render_widget(path_widget, path_area);
    
    if app.input_mode && app.input_field == InputField::MangaDir {
        let cursor_x = path_area.x + app.filter.width() as u16;
        let cursor_y = path_area.y;
        f.set_cursor_position((cursor_x, cursor_y));
    }
    
    let instructions = "
Press ENTER to confirm new path
Press ESC to cancel
Path will be created if it doesn't exist
Mangas will be reloaded automatically
";
    
    let instructions_widget = Paragraph::new(instructions)
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Center);
    
    f.render_widget(instructions_widget, chunks[2]);
}

fn draw_download_input(f: &mut Frame, app: &mut App, area: Rect) {
    let download_block = Block::default()
        .title(" Download Chapters ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[4]));
    
    f.render_widget(download_block.clone(), area);
    
    let inner_area = download_block.inner(area);
    
    // Ajuster les contraintes pour utiliser tout l'espace disponible
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Percentage(40), // Instructions (40% de l'espace)
            Constraint::Percentage(30), // Champ URL (30% de l'espace)
            Constraint::Percentage(30), // Champ Chapters (30% de l'espace)
        ])
        .split(inner_area);
    
    // Instructions
    let instructions = "
Sites: https://anime-sama.fr 
Ex:(URL: https://anime-sama.fr/.../scan/vf/)

Sites: https://mangas-origines.fr 
Ex:(URL: https://mangas-origines.fr/.../chapitre-1)

Tab: Switch fields  |  Enter: Start  |  Esc: Cancel

";
    
    let instructions_widget = Paragraph::new(instructions)
        .style(Style::default().fg(app.theme.foreground))
        .alignment(Alignment::Left)
        .wrap(Wrap { trim: false });
    
    f.render_widget(instructions_widget, chunks[0]);
    
    // Champ URL
    let url_block = Block::default()
        .title(" URL ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(
            if app.input_field == InputField::Url {
                app.theme.colors[4]
            } else {
                app.theme.colors[8]
            },
        ));
    
    f.render_widget(url_block.clone(), chunks[1]);
    
    let url_inner_area = url_block.inner(chunks[1].inner(Margin {
        horizontal: 1,
        vertical: 1, // Marge interne pour séparer le texte du titre
    }));

    let url_widget = Paragraph::new(app.download_url.clone())
        .style(Style::default().fg(app.theme.colors[12]))
        .wrap(Wrap { trim: false })
        .block(Block::default()); // Pas de bordure supplémentaire pour l'entrée
    
    f.render_widget(url_widget, url_inner_area);
    
    if app.input_mode && app.input_field == InputField::Url {
        let max_width = url_inner_area.width as usize;
        let mut cursor_x = 0;
        let mut cursor_y = 0;
        let mut char_count = 0;
        
        for ch in app.download_url.chars() {
            let char_width = ch.width().unwrap_or(0);
            if char_count < app.download_url.len() {
                if cursor_x + char_width > max_width {
                    cursor_x = 0;
                    cursor_y += 1;
                }
                cursor_x += char_width;
                char_count += 1;
            }
        }

        let cursor_y = cursor_y.min(url_inner_area.height.saturating_sub(1));
        
        f.set_cursor_position((
            url_inner_area.x + cursor_x as u16,
            url_inner_area.y + cursor_y as u16,
        ));
    }
    
    // Champ Chapters
    let chapters_block = Block::default()
        .title(" Chapters (e.g., 1,2,3 or 1-3) ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(
            if app.input_field == InputField::Chapters {
                app.theme.colors[4]
            } else {
                app.theme.colors[8]
            },
        ));
    
    f.render_widget(chapters_block.clone(), chunks[2]);
    
    let chapters_inner_area = chapters_block.inner(chunks[2].inner(Margin {
        horizontal: 1,
        vertical: 1, // Marge interne pour séparer le texte du titre
    }));
    
    let chapters_widget = Paragraph::new(app.selected_chapters_input.clone())
        .style(Style::default().fg(app.theme.colors[2]))
        .wrap(Wrap { trim: false })
        .block(Block::default()); // Pas de bordure supplémentaire pour l'entrée
    
    f.render_widget(chapters_widget, chapters_inner_area);
    
    if app.input_mode && app.input_field == InputField::Chapters {
        let max_width = chapters_inner_area.width as usize;
        let mut cursor_x = 0;
        let mut cursor_y = 0;
        let mut char_count = 0;
        
        for ch in app.selected_chapters_input.chars() {
            let char_width = ch.width().unwrap_or(0);
            if char_count < app.selected_chapters_input.len() {
                if cursor_x + char_width > max_width {
                    cursor_x = 0;
                    cursor_y += 1;
                }
                cursor_x += char_width;
                char_count += 1;
            }
        }
        
        f.set_cursor_position((
            chapters_inner_area.x + cursor_x as u16,
            chapters_inner_area.y + cursor_y as u16,
        ));
    }
}

fn draw_help_overlay(f: &mut Frame, app: &mut App, area: Rect) {
    let overlay_area = centered_rect(60, 70, area);
    
    let help_block = Block::default()
        .title(" Help ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(app.theme.colors[4]))
        .style(Style::default().bg(app.theme.background));
    
    f.render_widget(help_block.clone(), overlay_area);
    
    let help_text = vec![
        "Global Commands:",
        "q: Quit application",
        "?: Toggle help overlay",
        "",
        "Current Mode Commands:",
    ];
    
    let mode_commands = match app.state {
        AppState::BrowseManga => vec![
            "Up/↓: Select previous manga/chapter",
            "Down/↑: Select next manga/chapter",
            "Tab: Switch focus between manga and chapter lists",
            "Enter: Open with external reader (chapter list focused)",
            "o: Open with external reader (chapter list focused)",
            "m: Mark/unmark chapter as read (chapter list focused)",
            "r: Refresh manga list",
            "c: Open settings",
            "d: Download chapters",
            "/: Filter manga list",
            "Esc: Clear filter",
        ],
        AppState::ViewMangaDetails => vec![
            "j/Down: Select next chapter",
            "k/Up: Select previous chapter",
            "Enter: Open with external reader",
            "o: Open with external reader",
            "m: Mark/unmark as read",
            "d: Download chapters",
            "Esc: Return to manga list",
        ],
        AppState::Settings => vec![
            "Esc: Return to previous screen",
        ],
        AppState::DownloadInput => vec![
            "Tab: Switch between URL and Chapters fields",
            "Enter: Start download",
            "Esc: Cancel and return to manga list",
        ],
        AppState::Downloading => vec![
            "Esc: Cancel download",
            "r: Refresh manga list after download",
            "j/k: Scroll logs",
        ],
    };
    
    let all_help: Vec<&str> = help_text.iter().chain(mode_commands.iter())
        .map(|&s| s)
        .collect();
    
    let help_paragraph = Paragraph::new(
        all_help
            .iter()
            .map(|&line| Line::from(line))
            .collect::<Vec<_>>()
    )
    .style(Style::default().fg(app.theme.foreground))
    .alignment(Alignment::Left)
    .wrap(Wrap { trim: false });
    
    let inner_area = help_block.inner(overlay_area);
    f.render_widget(help_paragraph, inner_area);
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