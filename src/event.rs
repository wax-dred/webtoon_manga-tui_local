use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use crossterm::event::{self, Event as CrosstermEvent, KeyEvent, MouseEvent};

/// Application events
#[derive(Debug)]
pub enum Event {
    /// Terminal tick (timer)
    Tick,
    /// Key press
    Key(KeyEvent),
    /// Terminal resize
    Resize(u16, u16),
    /// Mouse event
    Mouse(MouseEvent),
}

/// Event handler
pub struct EventHandler {
    /// Event receiver channel
    rx: mpsc::Receiver<Event>,
    /// Handle to the event thread
    #[allow(dead_code)]
    handler: thread::JoinHandle<()>,
}

impl EventHandler {
    /// Create a new event handler with the specified tick rate
    pub fn new(tick_rate: Duration) -> Self {
        let (tx, rx) = mpsc::channel();
        let handler = thread::spawn(move || {
            let mut last_tick = Instant::now();
            loop {
                let timeout = tick_rate
                    .checked_sub(last_tick.elapsed())
                    .unwrap_or(Duration::from_secs(0));

                if event::poll(timeout).expect("Failed to poll for events") {
                    match event::read().expect("Failed to read event") {
                        CrosstermEvent::Key(key) => {
                            if tx.send(Event::Key(key)).is_err() {
                                break;
                            }
                        }
                        CrosstermEvent::Resize(width, height) => {
                            if tx.send(Event::Resize(width, height)).is_err() {
                                break;
                            }
                        }
                        CrosstermEvent::Mouse(mouse) => {
                            if tx.send(Event::Mouse(mouse)).is_err() {
                                break;
                            }
                        }
                        _ => {}
                    }
                }

                if last_tick.elapsed() >= tick_rate {
                    if tx.send(Event::Tick).is_err() {
                        break;
                    }
                    last_tick = Instant::now();
                }
            }
        });

        Self { rx, handler }
    }

    /// Get the next event
    pub fn next(&self) -> Result<Event> {
        self.rx.recv().context("Failed to receive event")
    }
}