#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod engine_probe;
#[cfg(test)]
use engine_probe::health_body_is_compatible;
use engine_probe::EngineProbe;

use serde::Serialize;
use signal_hook::{consts::SIGUSR1, iterator::Signals};
#[cfg(not(debug_assertions))]
use std::collections::HashMap;
use std::fs;
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
use tauri::api::process::{Command as SidecarCommand, CommandChild, CommandEvent};
use tauri::{
    AppHandle, CustomMenuItem, Manager, RunEvent, State, SystemTray, SystemTrayEvent,
    SystemTrayMenu, SystemTrayMenuItem, WindowEvent,
};

const TRAY_STATUS_ID: &str = "download-status";
const TRAY_OPEN_ID: &str = "open-window";
const TRAY_QUIT_ID: &str = "quit-app";

enum EngineProcess {
    External,
    #[cfg(debug_assertions)]
    Native(Child),
    #[cfg(not(debug_assertions))]
    Sidecar(CommandChild, Arc<Mutex<Option<String>>>),
}

impl EngineProcess {
    fn exit_error(&mut self) -> Option<String> {
        #[cfg(not(debug_assertions))]
        if let Self::Sidecar(_, exit) = self {
            return exit.lock().unwrap().clone();
        }
        #[cfg(debug_assertions)]
        if let Self::Native(child) = self {
            return match child.try_wait() {
                Ok(Some(status)) => Some(format!("引擎进程提前退出: {status}")),
                Err(error) => Some(format!("无法检查引擎进程: {error}")),
                Ok(None) => None,
            };
        }
        None
    }
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
            Self::Sidecar(child, _) => {
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
    progress: Arc<Mutex<StartupProgress>>,
    stopping: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct StartupProgress {
    stage: String,
    detail: String,
    attempt: usize,
    #[serde(skip)]
    started: Instant,
    elapsed_ms: u64,
    yt_dlp: Option<String>,
}

impl Default for StartupProgress {
    fn default() -> Self {
        Self {
            stage: "checking".into(),
            detail: "检查本地服务".into(),
            attempt: 1,
            started: Instant::now(),
            elapsed_ms: 0,
            yt_dlp: None,
        }
    }
}

impl EngineManager {
    fn stage(&self, stage: &str, detail: impl Into<String>) {
        let mut progress = self.progress.lock().unwrap();
        progress.stage = stage.into();
        progress.detail = detail.into();
    }
}

#[derive(Clone, Default)]
struct AppLifecycle {
    quitting: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineStatus {
    state: String,
    message: String,
    managed: bool,
    progress: Option<StartupProgress>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct TrayMetrics {
    active: usize,
    speed_bytes_per_second: u64,
}

fn tray_metrics_from_jobs(body: &[u8]) -> Result<TrayMetrics, serde_json::Error> {
    let jobs = serde_json::from_slice::<Vec<serde_json::Value>>(body)?;
    Ok(jobs
        .into_iter()
        .fold(TrayMetrics::default(), |mut metrics, job| {
            let active = matches!(
                job.get("status").and_then(serde_json::Value::as_str),
                Some("queued" | "probing" | "downloading" | "muxing" | "validating")
            );
            if active {
                metrics.active += 1;
                metrics.speed_bytes_per_second = metrics.speed_bytes_per_second.saturating_add(
                    job.get("speedBytesPerSecond")
                        .and_then(serde_json::Value::as_u64)
                        .unwrap_or(0),
                );
            }
            metrics
        }))
}

fn format_tray_speed(bytes_per_second: u64) -> String {
    const KIB: f64 = 1024.0;
    const MIB: f64 = KIB * 1024.0;
    const GIB: f64 = MIB * 1024.0;
    let bytes = bytes_per_second as f64;
    if bytes >= GIB {
        format!("{:.1} GiB/s", bytes / GIB)
    } else if bytes >= MIB {
        format!("{:.1} MiB/s", bytes / MIB)
    } else if bytes >= KIB {
        format!("{:.0} KiB/s", bytes / KIB)
    } else {
        format!("{bytes_per_second} B/s")
    }
}

fn tray_title(metrics: TrayMetrics) -> String {
    if metrics.active == 0 {
        String::new()
    } else {
        format_tray_speed(metrics.speed_bytes_per_second)
    }
}

fn tray_status_label(metrics: TrayMetrics) -> String {
    if metrics.active == 0 {
        "当前没有下载任务".to_string()
    } else {
        format!(
            "下载中 · {} 个任务 · {}",
            metrics.active,
            format_tray_speed(metrics.speed_bytes_per_second)
        )
    }
}

fn should_hide_window(quitting: bool) -> bool {
    !quitting
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
            progress: None,
        },
        EngineProbe::Incompatible => EngineStatus {
            state: "incompatible".to_string(),
            message: last_error
                .unwrap_or_else(|| "端口 8765 上的服务不是兼容的下载引擎".to_string()),
            managed: false,
            progress: None,
        },
        EngineProbe::Unavailable if starting => EngineStatus {
            state: "starting".to_string(),
            message: "正在准备本地下载引擎".to_string(),
            managed,
            progress: None,
        },
        EngineProbe::Pending if starting => EngineStatus {
            state: "starting".into(),
            message: "等待本地服务完成健康检查".into(),
            managed,
            progress: None,
        },
        EngineProbe::Pending => EngineStatus {
            state: "offline".into(),
            message: last_error.unwrap_or_else(|| "8765 上的服务未完成健康检查，请重新检查".into()),
            managed,
            progress: None,
        },
        EngineProbe::Unavailable => EngineStatus {
            state: "offline".to_string(),
            message: last_error.unwrap_or_else(|| "本地下载引擎未运行".to_string()),
            managed,
            progress: None,
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

fn probe_engine() -> EngineProbe {
    probe_engine_report().state
}

fn probe_engine_report() -> engine_probe::ProbeReport {
    engine_probe::probe(
        SocketAddr::from(([127, 0, 0, 1], 8765)),
        Duration::from_millis(500),
    )
}

fn listener_diagnostic(detail: &str) -> String {
    let owner = Command::new("/usr/sbin/lsof")
        .args(["-nP", "-a", "-iTCP:8765", "-sTCP:LISTEN", "-Fpc"])
        .output()
        .ok()
        .map(|output| String::from_utf8_lossy(&output.stdout).into_owned())
        .unwrap_or_default();
    let mut descriptions = Vec::new();
    let mut pid = "";
    for line in owner.lines() {
        if let Some(value) = line.strip_prefix('p') {
            pid = value;
        }
        if let Some(value) = line.strip_prefix('c') {
            descriptions.push(format!("{value} (PID {pid})"));
        }
    }
    format!("Port 8765 is occupied: {detail}。监听进程: {}。请关闭该服务或将其改用其他端口，再点击重新检查。", if descriptions.is_empty() { "未能获取；可运行 lsof -nP -iTCP:8765 -sTCP:LISTEN".into() } else { descriptions.join(", ") })
}

fn engine_get(path: &str, token: Option<&str>) -> Result<Vec<u8>, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], 8765));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(350))
        .map_err(|error| error.to_string())?;
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    let authorization = token
        .map(|value| format!("Authorization: Bearer {value}\r\n"))
        .unwrap_or_default();
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n{authorization}Connection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut response = Vec::new();
    stream
        .read_to_end(&mut response)
        .map_err(|error| error.to_string())?;
    let body_offset = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "Local engine returned an invalid HTTP response".to_string())?;
    let status_line = response
        .split(|byte| *byte == b'\n')
        .next()
        .and_then(|line| std::str::from_utf8(line).ok())
        .unwrap_or_default();
    if !status_line.contains(" 200 ") {
        return Err(format!(
            "Local engine request failed: {}",
            status_line.trim()
        ));
    }
    Ok(response[body_offset + 4..].to_vec())
}

fn fetch_engine_session_token() -> Result<String, String> {
    let body = engine_get("/api/session", None)?;
    serde_json::from_slice::<serde_json::Value>(&body)
        .map_err(|error| error.to_string())?
        .get("token")
        .and_then(serde_json::Value::as_str)
        .filter(|token| !token.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| "Local engine did not return a session token".to_string())
}

fn fetch_tray_metrics(token: &str) -> Result<TrayMetrics, String> {
    tray_metrics_from_jobs(&engine_get("/api/jobs", Some(token))?)
        .map_err(|error| error.to_string())
}

fn update_tray(app: &AppHandle, metrics: TrayMetrics) {
    let tray = app.tray_handle();
    #[cfg(target_os = "macos")]
    let _ = tray.set_title(&tray_title(metrics));
    let label = tray_status_label(metrics);
    let _ = tray.get_item(TRAY_STATUS_ID).set_title(&label);
    let tooltip = if metrics.active == 0 {
        "yet another downloader".to_string()
    } else {
        format!("yet another downloader · {label}")
    };
    let _ = tray.set_tooltip(&tooltip);
}

fn begin_tray_monitor(app: AppHandle, lifecycle: AppLifecycle) -> Result<(), String> {
    std::thread::Builder::new()
        .name("tray-download-monitor".to_string())
        .spawn(move || {
            let mut token: Option<String> = None;
            let mut displayed: Option<TrayMetrics> = None;
            while !lifecycle.quitting.load(Ordering::SeqCst) {
                let result = (|| {
                    if token.is_none() {
                        token = Some(fetch_engine_session_token()?);
                    }
                    fetch_tray_metrics(token.as_deref().unwrap_or_default())
                })();
                match result {
                    Ok(metrics) => {
                        if displayed != Some(metrics) {
                            update_tray(&app, metrics);
                            displayed = Some(metrics);
                        }
                    }
                    Err(_) => {
                        token = None;
                        if probe_engine() != EngineProbe::Compatible
                            && displayed != Some(TrayMetrics::default())
                        {
                            update_tray(&app, TrayMetrics::default());
                            displayed = Some(TrayMetrics::default());
                        }
                    }
                }
                std::thread::sleep(Duration::from_secs(1));
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn wait_for_engine(
    mut process: EngineProcess,
    manager: &EngineManager,
) -> Result<EngineProcess, String> {
    #[cfg(debug_assertions)]
    let timeout = Duration::from_secs(15);
    #[cfg(not(debug_assertions))]
    let timeout = Duration::from_secs(60);
    let deadline = Instant::now() + timeout;
    let mut last_event = String::new();
    while Instant::now() < deadline {
        if let Ok(event) = fs::read_to_string(startup_status_path()) {
            if event != last_event {
                record_startup_event(manager, &format!("ENGINE_STARTUP {event}"));
                last_event = event;
            }
        }
        if manager.stopping.load(Ordering::SeqCst) {
            process.kill();
            return Err("应用正在退出".into());
        }
        if let Some(error) = process.exit_error() {
            process.kill();
            return Err(format!("{error}；请查看引擎日志"));
        }
        let report = probe_engine_report();
        match report.state {
            EngineProbe::Compatible => {
                manager.progress.lock().unwrap().yt_dlp = report.yt_dlp;
                manager.stage("ready", "本地 API 与 yt-dlp 初始化完成");
                let mut progress = manager.progress.lock().unwrap();
                progress.elapsed_ms = progress.started.elapsed().as_millis() as u64;
                let _ = fs::remove_file(startup_status_path());
                return Ok(process);
            }
            EngineProbe::Incompatible => {
                process.kill();
                return Err(listener_diagnostic(&report.detail));
            }
            EngineProbe::Unavailable | EngineProbe::Pending => {
                std::thread::sleep(Duration::from_millis(200))
            }
        }
    }
    process.kill();
    let _ = fs::remove_file(startup_status_path());
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

fn append_engine_log(line: &str) {
    let path = engine_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut log) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(log, "{line}");
    }
}

fn startup_status_path() -> PathBuf {
    engine_log_path().with_file_name(format!("startup-{}.json", std::process::id()))
}

fn record_startup_event(manager: &EngineManager, line: &str) {
    let Some(json) = line.strip_prefix("ENGINE_STARTUP ") else {
        return;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(json) else {
        return;
    };
    if let (Some(stage), Some(detail)) = (value["stage"].as_str(), value["detail"].as_str()) {
        if matches!(stage, "initializing" | "ytdlp" | "healthcheck") {
            manager.stage(stage, detail);
        }
    }
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

fn start_engine(app: &AppHandle, manager: &EngineManager) -> Result<EngineProcess, String> {
    if manager.stopping.load(Ordering::SeqCst) {
        return Err("应用正在退出".into());
    }
    manager.stage("checking", "检查 127.0.0.1:8765 与现有引擎兼容性");
    let deadline = Instant::now() + Duration::from_secs(5);
    let report = loop {
        let report = probe_engine_report();
        if report.state != EngineProbe::Pending || Instant::now() >= deadline {
            break report;
        }
        manager.stage("checking", &report.detail);
        std::thread::sleep(Duration::from_millis(200));
    };
    match report.state {
        EngineProbe::Compatible => {
            manager.progress.lock().unwrap().yt_dlp = report.yt_dlp;
            manager.stage("ready", "已连接现有兼容引擎");
            let mut progress = manager.progress.lock().unwrap();
            progress.elapsed_ms = progress.started.elapsed().as_millis() as u64;
            return Ok(EngineProcess::External);
        }
        EngineProbe::Incompatible => {
            return Err(listener_diagnostic(&report.detail));
        }
        EngineProbe::Pending => {
            return Err(format!(
                "8765 上的服务健康检查超时: {}；尚不能判断兼容性。请稍后重新检查。",
                report.detail
            ))
        }
        EngineProbe::Unavailable => {}
    }
    manager.stage("preparing", "准备 Python 与本地下载组件");
    append_engine_log("Starting local engine components");
    let status_path = startup_status_path();
    if let Some(parent) = status_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let _ = fs::remove_file(&status_path);

    #[cfg(not(debug_assertions))]
    {
        let mut vars = HashMap::new();
        vars.insert(
            "M3U8_BRIDGE_STARTUP_STATUS".into(),
            status_path.to_string_lossy().into_owned(),
        );
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
        let (mut events, child) = SidecarCommand::new_sidecar("m3u8-bridge-engine")
            .map_err(|error| error.to_string())?
            .envs(vars)
            .spawn()
            .map_err(|error| error.to_string())?;
        let child_exit = Arc::new(Mutex::new(None));
        let event_exit = child_exit.clone();
        manager.stage("launching", "已启动内置 Python 引擎；首次运行正在解包组件");
        tauri::async_runtime::spawn(async move {
            while let Some(event) = events.recv().await {
                match event {
                    CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                        append_engine_log(&line);
                        // The per-launch status file is authoritative for progress.
                    }
                    CommandEvent::Terminated(payload) => {
                        *event_exit.lock().unwrap() = Some(format!(
                            "引擎进程提前退出 (code {:?}, signal {:?})",
                            payload.code, payload.signal
                        ));
                    }
                    CommandEvent::Error(error) => {
                        append_engine_log(&format!("Sidecar monitor: {error}"))
                    }
                    _ => {}
                }
            }
        });
        wait_for_engine(EngineProcess::Sidecar(child, child_exit), manager)
    }

    #[cfg(debug_assertions)]
    {
        let _ = app;
        let root = project_root();
        let mut command = Command::new(root.join("scripts/run-engine.sh"));
        command.current_dir(root);
        command.env("M3U8_BRIDGE_DESKTOP_PID", std::process::id().to_string());
        command.env("M3U8_BRIDGE_STARTUP_STATUS", &status_path);
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
        manager.stage("launching", "已启动 Miniforge Python，等待引擎初始化");
        wait_for_engine(process, manager)
    }
}

fn begin_engine_startup(app: AppHandle, manager: EngineManager) -> Result<(), String> {
    if manager.starting.swap(true, Ordering::SeqCst) {
        return Ok(());
    }
    *manager.last_error.lock().unwrap() = None;
    *manager.progress.lock().unwrap() = StartupProgress::default();
    let thread_manager = manager.clone();
    std::thread::Builder::new()
        .name("engine-startup".to_string())
        .spawn(move || {
            let _restart = thread_manager.restart_lock.lock().unwrap();
            let old_process = thread_manager.process.lock().unwrap().take();
            let stopped_owned = old_process.as_ref().is_some_and(EngineProcess::is_owned);
            if let Some(process) = old_process {
                thread_manager.stage("checking", "正在停止旧引擎并等待端口释放");
                process.kill();
            }
            let released = if stopped_owned {
                engine_probe::wait_for_release(
                    Duration::from_secs(5),
                    Duration::from_millis(100),
                    probe_engine_report,
                )
            } else {
                Ok(())
            };
            let mut attempt = 0;
            let result = released.and_then(|_| {
                retry_startup(3, Duration::from_millis(500), || {
                    attempt += 1;
                    thread_manager.progress.lock().unwrap().attempt = attempt;
                    start_engine(&app, &thread_manager)
                })
            });
            match result {
                Ok(process) => {
                    let mut current = thread_manager.process.lock().unwrap();
                    if thread_manager.stopping.load(Ordering::SeqCst) {
                        process.kill();
                        thread_manager.starting.store(false, Ordering::SeqCst);
                        return;
                    }
                    *current = Some(process);
                    *thread_manager.last_error.lock().unwrap() = None;
                }
                Err(error) => {
                    append_engine_log(&format!("Engine startup failed: {error}"));
                    let mut progress = thread_manager.progress.lock().unwrap();
                    progress.detail = error.clone();
                    progress.elapsed_ms = progress.started.elapsed().as_millis() as u64;
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

fn manager_status(manager: &EngineManager) -> EngineStatus {
    let managed = manager
        .process
        .lock()
        .unwrap()
        .as_ref()
        .is_some_and(EngineProcess::is_owned);
    let last_error = manager.last_error.lock().unwrap().clone();
    let report = if manager.starting.load(Ordering::SeqCst) {
        None
    } else {
        Some(probe_engine_report())
    };
    let last_error = last_error.or_else(|| {
        report
            .as_ref()
            .filter(|report| report.state == EngineProbe::Incompatible)
            .map(|report| listener_diagnostic(&report.detail))
    });
    let mut status = engine_status_from_probe(
        report
            .map(|report| report.state)
            .unwrap_or(EngineProbe::Unavailable),
        managed,
        last_error,
        manager.starting.load(Ordering::SeqCst),
    );
    let mut progress = manager.progress.lock().unwrap().clone();
    if manager.starting.load(Ordering::SeqCst) {
        progress.elapsed_ms = progress.started.elapsed().as_millis() as u64;
    }
    status.progress = Some(progress);
    status
}

#[tauri::command]
fn engine_status(manager: State<'_, EngineManager>) -> EngineStatus {
    manager_status(&manager)
}

#[tauri::command]
fn restart_engine(
    app: AppHandle,
    manager: State<'_, EngineManager>,
) -> Result<EngineStatus, String> {
    if manager.starting.load(Ordering::SeqCst) {
        return Ok(manager_status(&manager));
    }
    {
        let _restart = manager
            .restart_lock
            .try_lock()
            .map_err(|_| "引擎正在重启，请稍候".to_string())?;
        if let Some(process) = manager.process.lock().unwrap().as_ref() {
            if !process.is_owned() && probe_engine() == EngineProbe::Compatible {
                return Err("当前引擎由其他桌面实例管理，无法在这里重启".to_string());
            }
        }
    }
    begin_engine_startup(app, (*manager).clone())?;
    Ok(manager_status(&manager))
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

fn system_tray() -> SystemTray {
    let menu = SystemTrayMenu::new()
        .add_item(CustomMenuItem::new(TRAY_STATUS_ID, "当前没有下载任务").disabled())
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(CustomMenuItem::new(TRAY_OPEN_ID, "打开主窗口"))
        .add_item(CustomMenuItem::new(
            TRAY_QUIT_ID,
            "退出 yet another downloader",
        ));
    let tray = SystemTray::new()
        .with_menu(menu)
        .with_tooltip("yet another downloader");
    #[cfg(target_os = "macos")]
    let tray = tray.with_menu_on_left_click(false);
    tray
}

fn main() {
    tauri_plugin_deep_link::prepare("io.github.shumybest.yet-another-downloader");
    let manager = EngineManager::default();
    let manager_for_setup = manager.clone();
    let manager_for_exit = manager.clone();
    let lifecycle = AppLifecycle::default();
    let lifecycle_for_setup = lifecycle.clone();
    let lifecycle_for_close = lifecycle.clone();
    let lifecycle_for_tray = lifecycle.clone();
    let lifecycle_for_exit = lifecycle.clone();
    let app = tauri::Builder::default()
        .manage(manager)
        .system_tray(system_tray())
        .setup(move |app| {
            let activation_handle = app.handle();
            listen_for_activation(activation_handle.clone())?;
            tauri_plugin_deep_link::register("m3u8bridge", move |_request| {
                focus_main_window(&activation_handle);
            })
            .map_err(|error| error.to_string())?;
            begin_engine_startup(app.handle(), manager_for_setup.clone())?;
            begin_tray_monitor(app.handle(), lifecycle_for_setup.clone())?;
            Ok(())
        })
        .on_system_tray_event(move |app, event| match event {
            SystemTrayEvent::LeftClick { .. } => focus_main_window(app),
            SystemTrayEvent::MenuItemClick { id, .. } if id == TRAY_OPEN_ID => {
                focus_main_window(app)
            }
            SystemTrayEvent::MenuItemClick { id, .. } if id == TRAY_QUIT_ID => {
                lifecycle_for_tray.quitting.store(true, Ordering::SeqCst);
                app.exit(0);
            }
            _ => {}
        })
        .on_window_event(move |event| {
            if let WindowEvent::CloseRequested { api, .. } = event.event() {
                if should_hide_window(lifecycle_for_close.quitting.load(Ordering::SeqCst)) {
                    api.prevent_close();
                    let _ = event.window().hide();
                }
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
            lifecycle_for_exit.quitting.store(true, Ordering::SeqCst);
            manager_for_exit.stopping.store(true, Ordering::SeqCst);
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
        health_body_is_compatible, retry_startup, should_hide_window, tray_metrics_from_jobs,
        tray_status_label, tray_title, EngineProbe, TrayMetrics,
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
    fn aggregates_only_active_jobs_for_the_tray() {
        let metrics = tray_metrics_from_jobs(
            br#"[
              {"status":"downloading","speedBytesPerSecond":10485760},
              {"status":"probing","speedBytesPerSecond":0},
              {"status":"completed","speedBytesPerSecond":7340032},
              {"status":"failed","speedBytesPerSecond":2097152}
            ]"#,
        )
        .unwrap();

        assert_eq!(
            metrics,
            TrayMetrics {
                active: 2,
                speed_bytes_per_second: 10 * 1024 * 1024,
            }
        );
    }

    #[test]
    fn formats_live_and_idle_tray_labels() {
        let active = TrayMetrics {
            active: 2,
            speed_bytes_per_second: 19_503_514,
        };

        assert_eq!(tray_title(active), "18.6 MiB/s");
        assert_eq!(tray_status_label(active), "下载中 · 2 个任务 · 18.6 MiB/s");
        assert_eq!(tray_title(TrayMetrics::default()), "");
        assert_eq!(
            tray_status_label(TrayMetrics::default()),
            "当前没有下载任务"
        );
    }

    #[test]
    fn closing_hides_the_window_unless_the_app_is_quitting() {
        assert!(should_hide_window(false));
        assert!(!should_hide_window(true));
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
