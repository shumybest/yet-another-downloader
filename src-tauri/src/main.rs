#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use signal_hook::{consts::SIGUSR1, iterator::Signals};
#[cfg(not(debug_assertions))]
use std::collections::HashMap;
use std::fs;
#[cfg(debug_assertions)]
use std::fs::OpenOptions;
use std::path::{Path, PathBuf};
use std::process::Command;
#[cfg(debug_assertions)]
use std::process::{Child, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    time::{Duration, Instant},
};
#[cfg(not(debug_assertions))]
use tauri::api::process::{Command as SidecarCommand, CommandChild};
use tauri::{AppHandle, Manager, RunEvent, State, WindowEvent};

enum EngineProcess {
    External,
    #[cfg(debug_assertions)]
    Native(Child),
    #[cfg(not(debug_assertions))]
    Sidecar(CommandChild),
}

impl EngineProcess {
    fn is_owned(&self) -> bool {
        !matches!(self, Self::External)
    }

    fn kill(self) {
        match self {
            Self::External => {}
            #[cfg(debug_assertions)]
            Self::Native(mut child) => {
                let _ = child.kill();
                let _ = child.wait();
            }
            #[cfg(not(debug_assertions))]
            Self::Sidecar(child) => {
                let _ = child.kill();
            }
        }
    }
}

#[derive(Clone, Default)]
struct EngineManager {
    process: Arc<Mutex<Option<EngineProcess>>>,
    last_error: Arc<Mutex<Option<String>>>,
    restart_lock: Arc<Mutex<()>>,
    starting: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineStatus {
    state: String,
    message: String,
    managed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum EngineProbe {
    Unavailable,
    Compatible,
    Incompatible,
}

fn engine_status_from_probe(
    probe: EngineProbe,
    managed: bool,
    last_error: Option<String>,
    starting: bool,
) -> EngineStatus {
    match probe {
        EngineProbe::Compatible => EngineStatus {
            state: "online".to_string(),
            message: "本地下载引擎运行正常".to_string(),
            managed,
        },
        EngineProbe::Incompatible => EngineStatus {
            state: "incompatible".to_string(),
            message: "端口 8765 被旧版或不兼容的引擎占用".to_string(),
            managed: false,
        },
        EngineProbe::Unavailable if starting => EngineStatus {
            state: "starting".to_string(),
            message: "正在准备本地下载引擎".to_string(),
            managed,
        },
        EngineProbe::Unavailable => EngineStatus {
            state: "offline".to_string(),
            message: last_error.unwrap_or_else(|| "本地下载引擎未运行".to_string()),
            managed,
        },
    }
}

fn is_incompatible_error(error: &str) -> bool {
    error.contains("Port 8765 is occupied")
}

fn retry_startup<T, F>(
    max_attempts: usize,
    backoff: Duration,
    mut operation: F,
) -> Result<T, String>
where
    F: FnMut() -> Result<T, String>,
{
    let attempts = max_attempts.max(1);
    for attempt in 1..=attempts {
        match operation() {
            Ok(value) => return Ok(value),
            Err(error) if is_incompatible_error(&error) || attempt == attempts => {
                return Err(error)
            }
            Err(_) => std::thread::sleep(backoff),
        }
    }
    unreachable!()
}

fn copy_directory_recursive(source: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    for entry in fs::read_dir(source).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let file_type = entry.file_type().map_err(|error| error.to_string())?;
        let target = destination.join(entry.file_name());
        if file_type.is_dir() {
            copy_directory_recursive(&entry.path(), &target)?;
        } else if file_type.is_file() {
            fs::copy(entry.path(), target).map_err(|error| error.to_string())?;
        } else {
            return Err("Extension bundle contains an unsupported symbolic link".to_string());
        }
    }
    Ok(())
}

fn copy_directory_contents(source: &Path, destination: &Path) -> Result<(), String> {
    if !source.is_dir() {
        return Err(format!(
            "Bundled extension is missing: {}",
            source.display()
        ));
    }
    let staging = destination.with_extension(format!("staging-{}", std::process::id()));
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|error| error.to_string())?;
    }
    copy_directory_recursive(source, &staging)?;
    if destination.exists() {
        fs::remove_dir_all(destination).map_err(|error| error.to_string())?;
    }
    fs::rename(&staging, destination).map_err(|error| error.to_string())
}

fn health_body_is_compatible(body: &[u8]) -> bool {
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(body) else {
        return false;
    };
    value.get("ok").and_then(|item| item.as_bool()) == Some(true)
        && value
            .get("apiRevision")
            .and_then(|item| item.as_u64())
            .unwrap_or(0)
            >= 2
        && value
            .get("capabilities")
            .and_then(|item| item.as_array())
            .is_some_and(|items| {
                items
                    .iter()
                    .any(|item| item.as_str() == Some("jobs.delete"))
            })
}

fn probe_engine() -> EngineProbe {
    let address = SocketAddr::from(([127, 0, 0, 1], 8765));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return EngineProbe::Unavailable;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return EngineProbe::Incompatible;
    }
    let mut response = Vec::new();
    if stream.read_to_end(&mut response).is_err() {
        return EngineProbe::Incompatible;
    }
    let Some(body_offset) = response.windows(4).position(|window| window == b"\r\n\r\n") else {
        return EngineProbe::Incompatible;
    };
    if health_body_is_compatible(&response[body_offset + 4..]) {
        EngineProbe::Compatible
    } else {
        EngineProbe::Incompatible
    }
}

fn wait_for_engine(process: EngineProcess) -> Result<EngineProcess, String> {
    #[cfg(debug_assertions)]
    let timeout = Duration::from_secs(15);
    #[cfg(not(debug_assertions))]
    let timeout = Duration::from_secs(60);
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        match probe_engine() {
            EngineProbe::Compatible => return Ok(process),
            EngineProbe::Incompatible => {
                process.kill();
                return Err(
                    "Port 8765 is occupied by an outdated or incompatible local engine".to_string(),
                );
            }
            EngineProbe::Unavailable => std::thread::sleep(Duration::from_millis(100)),
        }
    }
    process.kill();
    Err(format!(
        "The local engine did not become ready within {} seconds",
        timeout.as_secs()
    ))
}

#[cfg(debug_assertions)]
fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn engine_log_path() -> PathBuf {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    home.join("Library/Logs/m3u8-bridge/engine.log")
}

#[cfg(any(not(debug_assertions), test))]
fn bundled_binary_candidates(resource_dir: &Path, name: &str) -> [PathBuf; 2] {
    [
        resource_dir.join("binaries").join(name),
        resource_dir.join(name),
    ]
}

#[cfg(not(debug_assertions))]
fn resolve_bundled_binary(app: &AppHandle, name: &str) -> Option<PathBuf> {
    let relative = PathBuf::from("binaries").join(name);
    app.path_resolver()
        .resolve_resource(&relative)
        .filter(|path| path.is_file())
        .or_else(|| {
            app.path_resolver().resource_dir().and_then(|resource_dir| {
                bundled_binary_candidates(&resource_dir, name)
                    .into_iter()
                    .find(|path| path.is_file())
            })
        })
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn listen_for_activation(app: AppHandle) -> Result<(), String> {
    let mut signals = Signals::new([SIGUSR1]).map_err(|error| error.to_string())?;
    std::thread::Builder::new()
        .name("desktop-activation".to_string())
        .spawn(move || {
            for _ in signals.forever() {
                focus_main_window(&app);
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn start_engine(app: &AppHandle) -> Result<EngineProcess, String> {
    match probe_engine() {
        EngineProbe::Compatible => return Ok(EngineProcess::External),
        EngineProbe::Incompatible => {
            return Err("Port 8765 is occupied by an outdated yet another downloader engine. Close the stale engine and start the desktop app again.".to_string())
        }
        EngineProbe::Unavailable => {}
    }

    #[cfg(not(debug_assertions))]
    {
        let mut vars = HashMap::new();
        vars.insert(
            "M3U8_BRIDGE_DESKTOP_PID".to_string(),
            std::process::id().to_string(),
        );
        if let Some(ffmpeg) = resolve_bundled_binary(app, "ffmpeg") {
            vars.insert(
                "M3U8_BRIDGE_FFMPEG".to_string(),
                ffmpeg.to_string_lossy().into_owned(),
            );
        }
        if let Some(ffprobe) = resolve_bundled_binary(app, "ffprobe") {
            vars.insert(
                "M3U8_BRIDGE_FFPROBE".to_string(),
                ffprobe.to_string_lossy().into_owned(),
            );
        }
        let (_events, child) = SidecarCommand::new_sidecar("m3u8-bridge-engine")
            .map_err(|error| error.to_string())?
            .envs(vars)
            .spawn()
            .map_err(|error| error.to_string())?;
        wait_for_engine(EngineProcess::Sidecar(child))
    }

    #[cfg(debug_assertions)]
    {
        let _ = app;
        let root = project_root();
        let mut command = Command::new(root.join("scripts/run-engine.sh"));
        command.current_dir(root);
        command.env("M3U8_BRIDGE_DESKTOP_PID", std::process::id().to_string());
        let log_path = engine_log_path();
        if let Some(parent) = log_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| format!("Could not create engine log directory: {error}"))?;
        }
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|error| format!("Could not open engine log: {error}"))?;
        let stderr = log
            .try_clone()
            .map_err(|error| format!("Could not open engine error log: {error}"))?;
        command.stdin(Stdio::null()).stdout(log).stderr(stderr);
        let process = command
            .spawn()
            .map(EngineProcess::Native)
            .map_err(|error| format!("Could not start the local engine: {error}"))?;
        wait_for_engine(process)
    }
}

fn begin_engine_startup(app: AppHandle, manager: EngineManager) -> Result<(), String> {
    manager.starting.store(true, Ordering::SeqCst);
    *manager.last_error.lock().unwrap() = None;
    let thread_manager = manager.clone();
    std::thread::Builder::new()
        .name("engine-startup".to_string())
        .spawn(move || {
            let _restart = thread_manager.restart_lock.lock().unwrap();
            let result = retry_startup(3, Duration::from_millis(500), || start_engine(&app));
            match result {
                Ok(process) => {
                    *thread_manager.process.lock().unwrap() = Some(process);
                    *thread_manager.last_error.lock().unwrap() = None;
                }
                Err(error) => {
                    *thread_manager.last_error.lock().unwrap() = Some(error);
                }
            }
            thread_manager.starting.store(false, Ordering::SeqCst);
        })
        .map(|_| ())
        .map_err(|error| {
            manager.starting.store(false, Ordering::SeqCst);
            let message = format!("Could not create engine startup worker: {error}");
            *manager.last_error.lock().unwrap() = Some(message.clone());
            message
        })
}

#[tauri::command]
fn engine_status(manager: State<'_, EngineManager>) -> EngineStatus {
    let managed = manager
        .process
        .lock()
        .unwrap()
        .as_ref()
        .is_some_and(EngineProcess::is_owned);
    let last_error = manager.last_error.lock().unwrap().clone();
    engine_status_from_probe(
        probe_engine(),
        managed,
        last_error,
        manager.starting.load(Ordering::SeqCst),
    )
}

#[tauri::command]
fn restart_engine(
    app: AppHandle,
    manager: State<'_, EngineManager>,
) -> Result<EngineStatus, String> {
    let _restart = manager
        .restart_lock
        .try_lock()
        .map_err(|_| "引擎正在重启，请稍候".to_string())?;
    manager.starting.store(true, Ordering::SeqCst);
    let result = (|| {
        if let Some(process) = manager.process.lock().unwrap().take() {
            if !process.is_owned() && probe_engine() == EngineProbe::Compatible {
                *manager.process.lock().unwrap() = Some(process);
                return Err("当前引擎由其他桌面实例管理，无法在这里重启".to_string());
            }
            process.kill();
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while probe_engine() != EngineProbe::Unavailable && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(100));
        }
        match retry_startup(3, Duration::from_millis(500), || start_engine(&app)) {
            Ok(process) => {
                let managed = process.is_owned();
                *manager.process.lock().unwrap() = Some(process);
                *manager.last_error.lock().unwrap() = None;
                Ok(engine_status_from_probe(
                    EngineProbe::Compatible,
                    managed,
                    None,
                    false,
                ))
            }
            Err(error) => {
                *manager.last_error.lock().unwrap() = Some(error.clone());
                Err(error)
            }
        }
    })();
    manager.starting.store(false, Ordering::SeqCst);
    result
}

fn extension_install_path() -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "无法确定当前用户目录".to_string())?;
    Ok(home.join("Library/Application Support/m3u8-bridge/chrome-extension"))
}

fn bundled_extension_path(app: &AppHandle) -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    if let Some(path) = app
        .path_resolver()
        .resolve_resource("resources/chrome-extension")
    {
        candidates.push(path);
    }
    if let Some(resource_dir) = app.path_resolver().resource_dir() {
        candidates.push(resource_dir.join("resources/chrome-extension"));
        candidates.push(resource_dir.join("chrome-extension"));
    }
    #[cfg(debug_assertions)]
    candidates.push(project_root().join("src-tauri/resources/chrome-extension"));
    candidates
        .into_iter()
        .find(|path| path.join("manifest.json").is_file())
        .ok_or_else(|| "应用包内未找到 Chrome 扩展，请重新构建应用".to_string())
}

#[tauri::command]
fn prepare_chrome_extension(app: AppHandle) -> Result<String, String> {
    let source = bundled_extension_path(&app)?;
    let destination = extension_install_path()?;
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    copy_directory_contents(&source, &destination)?;
    Ok(destination.to_string_lossy().into_owned())
}

#[tauri::command]
fn open_chrome_extensions() -> Result<(), String> {
    Command::new("open")
        .args(["-a", "Google Chrome", "chrome://extensions"])
        .status()
        .map_err(|error| format!("无法打开 Chrome: {error}"))
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("Chrome 未能打开扩展管理页面".to_string())
            }
        })
}

#[tauri::command]
fn open_engine_log() -> Result<(), String> {
    let path = engine_log_path();
    if !path.exists() {
        return Err("引擎日志尚未生成".to_string());
    }
    Command::new("open")
        .arg(&path)
        .status()
        .map_err(|error| format!("无法打开引擎日志: {error}"))
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("系统未能打开引擎日志".to_string())
            }
        })
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let value = path.trim();
    if value.is_empty() {
        return Err("Path is empty".to_string());
    }
    let target = Path::new(value);
    if !target.exists() {
        return Err("Path does not exist".to_string());
    }
    Command::new("open")
        .arg("-R")
        .arg(target)
        .status()
        .map_err(|error| format!("Could not open Finder: {error}"))
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("Finder rejected the path".to_string())
            }
        })
}

fn main() {
    tauri_plugin_deep_link::prepare("io.github.shumybest.yet-another-downloader");
    let manager = EngineManager::default();
    let manager_for_setup = manager.clone();
    let manager_for_exit = manager.clone();
    let app = tauri::Builder::default()
        .manage(manager)
        .setup(move |app| {
            let activation_handle = app.handle();
            listen_for_activation(activation_handle.clone())?;
            tauri_plugin_deep_link::register("m3u8bridge", move |_request| {
                focus_main_window(&activation_handle);
            })
            .map_err(|error| error.to_string())?;
            begin_engine_startup(app.handle(), manager_for_setup.clone())?;
            Ok(())
        })
        .on_window_event(|event| {
            if let WindowEvent::CloseRequested { api, .. } = event.event() {
                api.prevent_close();
                let _ = event.window().hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            reveal_path,
            engine_status,
            restart_engine,
            open_engine_log,
            prepare_chrome_extension,
            open_chrome_extensions
        ])
        .build(tauri::generate_context!())
        .expect("failed to build yet another downloader");
    app.run(move |_handle, event| {
        if matches!(event, RunEvent::Exit) {
            if let Some(child) = manager_for_exit.process.lock().unwrap().take() {
                child.kill();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        bundled_binary_candidates, copy_directory_contents, engine_status_from_probe,
        health_body_is_compatible, retry_startup, EngineProbe,
    };
    use std::fs;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::Duration;

    #[test]
    fn accepts_engine_with_current_revision_and_delete_capability() {
        assert!(health_body_is_compatible(
            br#"{"ok":true,"apiRevision":2,"capabilities":["jobs.delete"]}"#
        ));
    }

    #[test]
    fn rejects_legacy_health_response() {
        assert!(!health_body_is_compatible(
            br#"{"ok":true,"version":"0.1.0"}"#
        ));
    }

    #[test]
    fn reports_offline_engine_with_actionable_startup_error() {
        let status = engine_status_from_probe(
            EngineProbe::Unavailable,
            false,
            Some("engine exited".to_string()),
            false,
        );

        assert_eq!(status.state, "offline");
        assert_eq!(status.message, "engine exited");
        assert!(!status.managed);
    }

    #[test]
    fn reports_incompatible_listener_without_claiming_ownership() {
        let status = engine_status_from_probe(EngineProbe::Incompatible, false, None, false);

        assert_eq!(status.state, "incompatible");
        assert!(!status.managed);
    }

    #[test]
    fn reports_starting_before_an_unavailable_engine_is_ready() {
        let status = engine_status_from_probe(EngineProbe::Unavailable, false, None, true);

        assert_eq!(status.state, "starting");
        assert_eq!(status.message, "正在准备本地下载引擎");
    }

    #[test]
    fn retries_transient_startup_failures() {
        let attempts = AtomicUsize::new(0);
        let result = retry_startup(3, Duration::ZERO, || {
            let attempt = attempts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt < 3 {
                Err("engine exited before becoming ready".to_string())
            } else {
                Ok("ready")
            }
        });

        assert_eq!(result.unwrap(), "ready");
        assert_eq!(attempts.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn does_not_retry_an_incompatible_listener() {
        let attempts = AtomicUsize::new(0);
        let result: Result<(), String> = retry_startup(3, Duration::ZERO, || {
            attempts.fetch_add(1, Ordering::SeqCst);
            Err("Port 8765 is occupied by an outdated or incompatible local engine".to_string())
        });

        assert!(result.is_err());
        assert_eq!(attempts.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn replaces_stale_extension_files_when_copying_bundle() {
        let root =
            std::env::temp_dir().join(format!("m3u8-bridge-extension-copy-{}", std::process::id()));
        let source = root.join("source");
        let destination = root.join("destination");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(source.join("icons")).unwrap();
        fs::create_dir_all(&destination).unwrap();
        fs::write(source.join("manifest.json"), "new").unwrap();
        fs::write(source.join("icons/icon-16.png"), "png").unwrap();
        fs::write(destination.join("stale.js"), "stale").unwrap();

        copy_directory_contents(&source, &destination).unwrap();

        assert_eq!(
            fs::read_to_string(destination.join("manifest.json")).unwrap(),
            "new"
        );
        assert!(destination.join("icons/icon-16.png").is_file());
        assert!(!destination.join("stale.js").exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn resolves_bundled_tools_from_the_binaries_resource_directory_first() {
        let resources =
            std::path::Path::new("/Applications/yet another downloader.app/Contents/Resources");
        let candidates = bundled_binary_candidates(resources, "ffmpeg");

        assert_eq!(candidates[0], resources.join("binaries/ffmpeg"));
        assert_eq!(candidates[1], resources.join("ffmpeg"));
    }
}
