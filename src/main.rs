mod app;
mod config;
mod event;
mod image;
mod manga;
mod manga_indexer;
mod theme;
mod ui;
mod util;

use env_logger;
use std::io;
use std::path::PathBuf;
use std::time::Duration;


use anyhow::{Context, Result};
use app::App;
use clap::Parser;
use crossterm::{
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use env_logger::Builder;
use event::Event as AppEvent;
use log::{debug, info};
use ratatui::{prelude::*, Terminal};
use std::fs::OpenOptions;
use std::io::Write;

#[derive(Parser, Debug)]
#[clap(author, version)]
struct Args {
    #[clap(short, long, default_value = "~/Documents/Scan")]
    manga_dir: String,
    #[clap(short, long)]
    debug: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();

    // Initialiser le logger
    let log_file = OpenOptions::new()
        .write(true)
        .append(true)
        .create(true)
        .open("manga_reader.log")
        .context("Failed to open log file")?;

    Builder::new()
        .filter(
            None,
            if args.debug {
                log::LevelFilter::Debug
            } else {
                log::LevelFilter::Info
            },
        )
        .format(|buf, record| {
            use chrono::Local;
            writeln!(
                buf,
                "[{}] {} - {}",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                record.level(),
                record.args()
            )
        })
        .target(env_logger::Target::Pipe(Box::new(log_file)))
        .init();

    info!("Démarrage de l'application manga reader");
    manga_indexer::open_db().context("Failed to initialize SQLite database")?;

    let manga_dir = PathBuf::from(shellexpand::tilde(&args.manga_dir).to_string());
    run(manga_dir)
}

fn run(manga_dir: PathBuf) -> Result<()> {
    // Configurer le terminal
    enable_raw_mode().context("Échec de l'activation du mode brut")?;
    io::stdout()
        .execute(EnterAlternateScreen)
        .context("Échec de l'entrée dans l'écran alternatif")?;

    // Activer la capture de la souris
    io::stdout()
        .execute(crossterm::event::EnableMouseCapture)
        .context("Échec de l'activation de la capture de la souris")?;
    debug!("Capture de la souris activée");

    let backend = CrosstermBackend::new(io::stdout());
    let mut terminal = Terminal::new(backend).context("Échec de la création du terminal")?;
    terminal.clear()?;

    // Charger le thème
    let theme = match theme::Theme::load("~/.cache/wal/wal.json") {
        Ok(theme) => theme,
        Err(_) => {
            debug!("Échec du chargement du thème, utilisation du thème par défaut");
            theme::Theme {
                background: Color::Black,
                foreground: Color::White,
                cursor: Color::White,
                colors: [
                    Color::Black,
                    Color::Red,
                    Color::Green,
                    Color::Yellow,
                    Color::Blue,
                    Color::Magenta,
                    Color::Cyan,
                    Color::Gray,
                    Color::DarkGray,
                    Color::LightRed,
                    Color::LightGreen,
                    Color::LightYellow,
                    Color::LightBlue,
                    Color::LightMagenta,
                    Color::LightCyan,
                    Color::White,
                ],
            }
        }
    };

    // Charger la configuration
    let config = config::Config::load()?;
    let manga_dir =
        if manga_dir != PathBuf::from(shellexpand::tilde("~/Documents/Scan").to_string()) {
            manga_dir
        } else if let Some(last_dir) = config.last_manga_dir {
            last_dir
        } else {
            manga_dir
        };

    // Créer l'état de l'application
    let mut app = App::new(manga_dir, theme)?;

    // Créer le gestionnaire d'événements
    let event_handler = event::EventHandler::new(Duration::from_millis(100));

    // Boucle principale
    loop {
        terminal.draw(|frame| ui::draw(frame, &mut app))?;

        match event_handler.next()? {
            AppEvent::Tick => {
                app.tick()?;
            }
            AppEvent::Key(key_event) => {
                debug!("Événement clé: {:?}", key_event);
                if app.handle_key(&AppEvent::Key(key_event))? {
                    break;
                }
                if app.needs_refresh {
                    terminal.draw(|frame| ui::draw(frame, &mut app))?;
                    app.reset_refresh();
                }
            }
            AppEvent::Resize(width, height) => {
                debug!("Redimensionnement: {}x{}", width, height);
                app.on_resize(width, height)?;
                terminal.draw(|frame| ui::draw(frame, &mut app))?;
            }
            AppEvent::Mouse(mouse_event) => {
                debug!("Événement souris: {:?}", mouse_event);
                if app.handle_key(&AppEvent::Mouse(mouse_event))? {
                    break;
                }
                if app.needs_refresh {
                    terminal.draw(|frame| ui::draw(frame, &mut app))?;
                    app.reset_refresh();
                }
            }
            AppEvent::None => {}
        }
    }

    // Restaurer le terminal
    io::stdout()
        .execute(crossterm::event::DisableMouseCapture)
        .context("Échec de la désactivation de la capture de la souris")?;
    debug!("Capture de la souris désactivée");

    disable_raw_mode().context("Échec de la désactivation du mode brut")?;
    io::stdout()
        .execute(LeaveAlternateScreen)
        .context("Échec de la sortie de l'écran alternatif")?;

    Ok(())
}
