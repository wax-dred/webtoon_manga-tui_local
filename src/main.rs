mod app;
mod config;
mod event;
mod manga;
mod theme;
mod ui;
mod util;
mod image;

use std::io;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Context, Result};
use clap::Parser;
use crossterm::{
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use ratatui::{prelude::*, Terminal};

use app::App;

/// Terminal-based manga reader written in Rust
#[derive(Parser, Debug)]
#[clap(author, version, about)]
struct Args {
    /// Path to manga directory
    #[clap(short, long, default_value = "~/Documents/Scan")]
    manga_dir: String,

    /// Enable debug logging
    #[clap(short, long)]
    debug: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    
    // Initialize logger
    if args.debug {
        std::env::set_var("RUST_LOG", "debug");
        env_logger::init();
    }
    
    let manga_dir = PathBuf::from(shellexpand::tilde(&args.manga_dir).to_string());
    run(manga_dir)
}

fn run(manga_dir: PathBuf) -> Result<()> {
    // Setup terminal
    enable_raw_mode().context("Failed to enable raw mode")?;
    io::stdout()
        .execute(EnterAlternateScreen)
        .context("Failed to enter alternate screen")?;
    
    // Enable mouse capture
    io::stdout()
        .execute(crossterm::event::EnableMouseCapture)
        .context("Failed to enable mouse capture")?;

    let backend = CrosstermBackend::new(io::stdout());
    let mut terminal = Terminal::new(backend).context("Failed to create terminal")?;
    terminal.clear()?;

    // Load theme
    let theme = match theme::Theme::load("~/.cache/wal/wal.json") {
        Ok(theme) => theme,
        Err(_) => {
            // Fallback default theme
            theme::Theme {
                background: Color::Black,
                foreground: Color::White,
                cursor: Color::White,
                colors: [
                    Color::Black, Color::Red, Color::Green, Color::Yellow,
                    Color::Blue, Color::Magenta, Color::Cyan, Color::Gray,
                    Color::DarkGray, Color::LightRed, Color::LightGreen, Color::LightYellow,
                    Color::LightBlue, Color::LightMagenta, Color::LightCyan, Color::White,
                ],
            }
        }
    };
    
    // Load config to check last_manga_dir
    let config = config::Config::load()?;
    let manga_dir = if manga_dir != PathBuf::from(shellexpand::tilde("~/Documents/Scan").to_string()) {
        // Use command-line manga_dir if specified
        manga_dir
    } else if let Some(last_dir) = config.last_manga_dir {
        // Use last_manga_dir from config if available
        last_dir
    } else {
        // Fallback to default
        manga_dir
    };

    // Create app state
    let mut app = App::new(manga_dir, theme)?;
    
    // Create event handler
    let event_handler = event::EventHandler::new(Duration::from_millis(100));

    // Main loop
    loop {
        // Draw UI
        terminal.draw(|frame| ui::draw(frame, &mut app))?;
        
        // Handle events
        match event_handler.next()? {
            event::Event::Tick => app.tick(),
            event::Event::Key(key_event) => {
                if app.handle_key(crossterm::event::Event::Key(key_event))? {
                    break;
                }
            }
            event::Event::Resize(width, height) => {
                app.on_resize(width, height);
            }
            event::Event::Mouse(mouse_event) => {
                if app.handle_key(crossterm::event::Event::Mouse(mouse_event))? {
                    break;
                }
            }
        }
    }
    
    // Restore terminal
    disable_raw_mode().context("Failed to disable raw mode")?;
    io::stdout()
        .execute(LeaveAlternateScreen)
        .context("Failed to leave alternate screen")?;
    io::stdout()
        .execute(crossterm::event::DisableMouseCapture)
        .context("Failed to disable mouse capture")?;
    
    Ok(())
}