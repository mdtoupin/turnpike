// Turnpike Deck: lightweight desktop supervisor + visualizer for turnpike.
//
// Supervision contract:
// - If the monitor server (port 8642) is already running, attach to it and never
//   touch its lifecycle (it belongs to whoever started it).
// - If it is not running, spawn `python monitor.py` hidden, wait for the port,
//   and kill that child (only that child) when the window closes.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const PORT: u16 = 8642;
// Written next to the installed exe by install.ps1: the turnpike checkout it came from.
const DIR_FILE: &str = "turnpike.dir";
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct Supervised(Mutex<Option<Child>>);

fn port_open() -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], PORT).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

// Where turnpike lives, in priority order: $TURNPIKE_DIR, the turnpike.dir file
// beside the exe (installed copy), else the nearest ancestor of the exe holding
// monitor.py (a dev build under deck/src-tauri/target/).
fn turnpike_dir() -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("TURNPIKE_DIR") {
        return Some(PathBuf::from(dir));
    }
    let exe = std::env::current_exe().ok()?;
    if let Ok(dir) = std::fs::read_to_string(exe.with_file_name(DIR_FILE)) {
        return Some(PathBuf::from(dir.trim()));
    }
    exe.ancestors().find(|p| p.join("monitor.py").is_file()).map(PathBuf::from)
}

fn spawn_monitor() -> Option<Child> {
    let Some(dir) = turnpike_dir() else {
        eprintln!("cannot find turnpike: set TURNPIKE_DIR or re-run install.ps1");
        return None;
    };
    let script = dir.join("monitor.py");
    let mut cmd = Command::new("python");
    cmd.arg(&script).current_dir(&dir);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    match cmd.spawn() {
        Ok(child) => {
            for _ in 0..60 {
                if port_open() {
                    return Some(child);
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Some(child) // window will show the connection error if it never came up
        }
        Err(e) => {
            eprintln!("failed to spawn monitor.py ({}): {e}", script.display());
            None
        }
    }
}

fn main() {
    let supervised = if port_open() { None } else { spawn_monitor() };

    tauri::Builder::default()
        .manage(Supervised(Mutex::new(supervised)))
        .setup(|app| {
            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(format!("http://127.0.0.1:{PORT}").parse().unwrap()),
            )
            .title("Turnpike Deck")
            .inner_size(1380.0, 880.0)
            .min_inner_size(900.0, 600.0)
            .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Turnpike Deck")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Supervised>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
