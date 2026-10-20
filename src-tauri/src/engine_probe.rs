#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn server(
        response: &'static [u8],
        delay: Duration,
        keep_open: Duration,
    ) -> (SocketAddr, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let thread = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 512];
            let _ = stream.read(&mut request);
            std::thread::sleep(delay);
            let _ = stream.write_all(response);
            std::thread::sleep(keep_open);
        });
        (address, thread)
    }

    #[test]
    fn timeout_is_pending_not_a_confirmed_conflict() {
        let (address, thread) = server(b"", Duration::from_millis(150), Duration::ZERO);
        assert_eq!(
            probe(address, Duration::from_millis(30)).state,
            EngineProbe::Pending
        );
        thread.join().unwrap();
    }

    #[test]
    fn reads_complete_content_length_without_waiting_for_eof() {
        let body =
            br#"{"ok":true,"apiRevision":2,"capabilities":["jobs.delete"],"ytDlp":"2026.test"}"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            std::str::from_utf8(body).unwrap()
        );
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let thread = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 512];
            let _ = stream.read(&mut request);
            stream.write_all(response.as_bytes()).unwrap();
            std::thread::sleep(Duration::from_millis(150));
        });
        let report = probe(address, Duration::from_millis(30));
        assert_eq!(report.state, EngineProbe::Compatible);
        assert_eq!(report.yt_dlp.as_deref(), Some("2026.test"));
        thread.join().unwrap();
    }

    #[test]
    fn foreign_http_service_is_distinguished_from_legacy_engine() {
        let (address, thread) = server(
            b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n",
            Duration::ZERO,
            Duration::ZERO,
        );
        let report = probe(address, Duration::from_millis(100));
        assert_eq!(report.state, EngineProbe::Incompatible);
        assert!(report.detail.contains("404"));
        assert!(!report.detail.contains("旧版"));
        thread.join().unwrap();
    }

    #[test]
    fn free_port_is_unavailable() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);
        assert_eq!(
            probe(address, Duration::from_millis(50)).state,
            EngineProbe::Unavailable
        );
    }

    #[test]
    fn restart_waits_for_the_previous_listener_to_release() {
        let mut probes = 0;
        wait_for_release(Duration::from_secs(1), Duration::ZERO, || {
            probes += 1;
            report(
                if probes < 3 {
                    EngineProbe::Compatible
                } else {
                    EngineProbe::Unavailable
                },
                "test listener",
            )
        })
        .unwrap();
        assert_eq!(probes, 3);
    }

    #[test]
    fn restart_does_not_reuse_a_listener_that_failed_to_stop() {
        let result = wait_for_release(Duration::ZERO, Duration::ZERO, || {
            report(EngineProbe::Compatible, "test listener")
        });
        assert!(result.is_err());
    }
}
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EngineProbe {
    Unavailable,
    Pending,
    Compatible,
    Incompatible,
}

#[derive(Debug)]
pub struct ProbeReport {
    pub state: EngineProbe,
    pub detail: String,
    pub yt_dlp: Option<String>,
}

pub fn health_body_is_compatible(body: &[u8]) -> bool {
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

fn report(state: EngineProbe, detail: impl Into<String>) -> ProbeReport {
    ProbeReport {
        state,
        detail: detail.into(),
        yt_dlp: None,
    }
}

pub fn wait_for_release(
    timeout: Duration,
    interval: Duration,
    mut probe_listener: impl FnMut() -> ProbeReport,
) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    loop {
        let response = probe_listener();
        if response.state == EngineProbe::Unavailable {
            return Ok(());
        }
        if response.state == EngineProbe::Incompatible {
            return Err(format!("Port 8765 is occupied: {}", response.detail));
        }
        if Instant::now() >= deadline {
            return Err("旧引擎尚未释放 8765 端口，请稍后重新检查".into());
        }
        std::thread::sleep(interval);
    }
}

pub fn probe(address: SocketAddr, timeout: Duration) -> ProbeReport {
    let mut stream = match TcpStream::connect_timeout(&address, timeout) {
        Ok(stream) => stream,
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionRefused => {
            return report(EngineProbe::Unavailable, "没有监听服务");
        }
        Err(error) => return report(EngineProbe::Pending, format!("连接检查尚未完成: {error}")),
    };
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!("GET /healthz HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n");
    if let Err(error) = stream.write_all(request.as_bytes()) {
        return report(EngineProbe::Pending, format!("健康检查请求失败: {error}"));
    }
    let deadline = Instant::now() + timeout;
    let mut response = Vec::new();
    loop {
        if let Some(offset) = response.windows(4).position(|window| window == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&response[..offset]);
            let status = headers.lines().next().unwrap_or_default();
            if !status.starts_with("HTTP/")
                || !status
                    .split_whitespace()
                    .nth(1)
                    .is_some_and(|code| code == "200")
            {
                return report(
                    EngineProbe::Incompatible,
                    format!("8765 上的服务返回 {status}，不是可用的下载引擎"),
                );
            }
            let body = &response[offset + 4..];
            let length = headers.lines().find_map(|line| {
                let (key, value) = line.split_once(':')?;
                key.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())
                    .flatten()
            });
            // A complete framed response does not require the server to close its socket.
            if length.is_some_and(|size| body.len() >= size) {
                return parse_health(&body[..length.unwrap()]);
            }
        }
        if response.len() > 64 * 1024 {
            return report(
                EngineProbe::Incompatible,
                "健康响应超过 64 KiB，无法识别该服务",
            );
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return report(EngineProbe::Pending, "服务已监听，但健康响应超时");
        }
        let _ = stream.set_read_timeout(Some(remaining));
        let mut buffer = [0; 4096];
        match stream.read(&mut buffer) {
            Ok(0) => {
                return response
                    .windows(4)
                    .position(|window| window == b"\r\n\r\n")
                    .map(|offset| parse_health(&response[offset + 4..]))
                    .unwrap_or_else(|| {
                        report(EngineProbe::Pending, "服务在返回完整健康响应前断开连接")
                    });
            }
            Ok(size) => response.extend_from_slice(&buffer[..size]),
            Err(error) => {
                return report(
                    EngineProbe::Pending,
                    format!("服务已监听，健康检查未完成: {error}"),
                )
            }
        }
    }
}

fn parse_health(body: &[u8]) -> ProbeReport {
    if health_body_is_compatible(body) {
        let value: serde_json::Value = serde_json::from_slice(body).unwrap();
        ProbeReport {
            state: EngineProbe::Compatible,
            detail: "健康检查通过".to_string(),
            yt_dlp: value
                .get("ytDlp")
                .and_then(|item| item.as_str())
                .map(str::to_owned),
        }
    } else {
        report(
            EngineProbe::Incompatible,
            "服务的健康响应不兼容当前下载 API",
        )
    }
}
