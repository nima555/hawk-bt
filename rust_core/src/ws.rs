use std::sync::Arc;
use std::time::Duration;

use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{Mutex, Notify};
use tokio::time::timeout;
use tokio_tungstenite::accept_hdr_async;
use tokio_tungstenite::tungstenite::protocol::Message as WsMsg;
use tokio_tungstenite::tungstenite::handshake::server::{Request, Response, ErrorResponse};
use tokio_tungstenite::tungstenite::http::StatusCode;
use futures_util::{SinkExt, StreamExt};

use crate::errors::{RpcError, RpcTransportError, RustError};
use crate::wire;

/// Library version (sync with Cargo.toml)
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Allowed Origin prefixes for WebSocket connections.
const ALLOWED_ORIGINS: &[&str] = &[
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost",
    "https://www2.kisshi-lab.com",
];

type WsStream = tokio_tungstenite::WebSocketStream<TcpStream>;

#[derive(Clone)]
pub struct WsServer {
    host: String,
    port: u16,
    start_seq: u32,
    seq: Arc<tokio::sync::Mutex<u32>>,
    ws: Arc<Mutex<Option<WsStream>>>,
    notify: Arc<Notify>,
}

impl WsServer {
    pub fn new(host: &str, port: u16, start_seq: u32) -> Self {
        Self {
            host: host.to_string(),
            port,
            start_seq,
            seq: Arc::new(tokio::sync::Mutex::new(start_seq)),
            ws: Arc::new(Mutex::new(None)),
            notify: Arc::new(Notify::new()),
        }
    }

    #[inline(always)]
    pub async fn start(&self) -> Result<(), RustError> {
        let addr = format!("{}:{}", self.host, self.port);
        let listener = TcpListener::bind(&addr)
            .await
            .map_err(|e| RustError::Transport(RpcTransportError {
                message: format!("bind failed on {addr}: {e}"),
                seq: None,
                fn_id: None,
            }))?;

        let ws = self.ws.clone();
        let seq = self.seq.clone();
        let start_seq = self.start_seq;
        let notify = self.notify.clone();
        tokio::spawn(async move {
            loop {
                match listener.accept().await {
                    Ok((stream, _)) => {
                        let origin_check = |req: &Request, resp: Response| -> Result<Response, ErrorResponse> {
                            let origin = req.headers()
                                .get("origin")
                                .and_then(|v| v.to_str().ok())
                                .unwrap_or("")
                                .trim_end_matches('/');
                            if origin.is_empty() || ALLOWED_ORIGINS.iter().any(|ao| origin.starts_with(ao)) {
                                Ok(resp)
                            } else {
                                eprintln!("[rust ws server] rejected origin: {origin}");
                                let mut err = ErrorResponse::new(None);
                                *err.status_mut() = StatusCode::FORBIDDEN;
                                Err(err)
                            }
                        };
                        match accept_hdr_async(stream, origin_check).await {
                        Ok(mut conn) => {
                            // Send handshake with version info
                            let handshake = format!(
                                r#"{{"type":"handshake","python_library_version":"{}"}}"#,
                                VERSION
                            );
                            if let Err(e) = conn.send(WsMsg::Text(handshake)).await {
                                eprintln!("[rust ws server] handshake send failed: {e}");
                            }

                            let mut guard = ws.lock().await;
                            // only accept first connection; drop previous
                            *guard = Some(conn);
                            let mut seq_guard = seq.lock().await;
                            *seq_guard = start_seq;
                            notify.notify_waiters();
                        }
                        Err(e) => eprintln!("[rust ws server] accept failed: {e}"),
                    }},
                    Err(e) => {
                        eprintln!("[rust ws server] accept failed: {e}");
                        continue;
                    }
                }
            }
        });
        Ok(())
    }

    #[inline(always)]
    pub async fn wait_connected(&self, timeout_dur: Option<Duration>) -> Result<(), RustError> {
        // fast path
        if self.ws.lock().await.is_some() {
            return Ok(());
        }
        let fut = self.notify.notified();
        if let Some(dur) = timeout_dur {
            timeout(dur, fut)
                .await
                .map_err(|_| RustError::Transport(RpcTransportError {
                    message: "wait_connected timed out".to_string(),
                    seq: None,
                    fn_id: None,
                }))?;
        } else {
            fut.await;
        }
        Ok(())
    }

    #[inline(always)]
    pub async fn send_run_and_wait(
        &self,
        fn_id: u16,
        payload: &[u8],
        timeout_dur: Duration,
    ) -> Result<Vec<u8>, RustError> {
        // ensure connection
        if self.ws.lock().await.is_none() {
            return Err(RustError::Transport(RpcTransportError {
                message: "no websocket connected".to_string(),
                seq: None,
                fn_id: Some(fn_id),
            }));
        }
        let mut seq_guard = self.seq.lock().await;
        let seq = *seq_guard;
        *seq_guard = seq.wrapping_add(1);
        drop(seq_guard);

        let frame = wire::pack_run(seq, fn_id, payload);

        let mut guard = self.ws.lock().await;
        let ws = guard.as_mut().ok_or_else(|| {
            RustError::Transport(RpcTransportError {
                message: "connection missing".to_string(),
                seq: Some(seq),
                fn_id: Some(fn_id),
            })
        })?;

        if let Err(e) = ws.send(WsMsg::Binary(frame)).await {
            *guard = None;
            return Err(RustError::Transport(RpcTransportError {
                message: format!("websocket send failed: {e}"),
                seq: Some(seq),
                fn_id: Some(fn_id),
            }));
        }

        drop(guard); // release lock for recv loop

        let result = self.recv_result(seq, fn_id, timeout_dur).await;
        if matches!(&result, Err(RustError::Transport(_))) {
            let mut guard = self.ws.lock().await;
            *guard = None;
        }
        result
    }

    #[inline(always)]
    async fn recv_result(&self, seq: u32, fn_id: u16, timeout_dur: Duration) -> Result<Vec<u8>, RustError> {
        let mut guard = self.ws.lock().await;
        let ws = guard.as_mut().ok_or_else(|| {
            RustError::Transport(RpcTransportError {
                message: "connection missing".to_string(),
                seq: Some(seq),
                fn_id: Some(fn_id),
            })
        })?;

        let res = timeout(timeout_dur, async {
            loop {
                let msg = ws.next().await;
                let msg = match msg {
                    Some(Ok(m)) => m,
                    Some(Err(e)) => {
                        return Err(RustError::Transport(RpcTransportError {
                            message: format!("websocket recv failed: {e}"),
                            seq: Some(seq),
                            fn_id: Some(fn_id),
                        }))
                    }
                    None => {
                        return Err(RustError::Transport(RpcTransportError {
                            message: "websocket closed".to_string(),
                            seq: Some(seq),
                            fn_id: Some(fn_id),
                        }))
                    }
                };

                match msg {
                    WsMsg::Binary(data) => {
                        let msg = wire::unpack_message(&data)?;
                        if msg.version != wire::PROTOCOL_VERSION {
                            return Err(RustError::Transport(RpcTransportError {
                                message: format!(
                                    "protocol version mismatch: got {}, expected {}",
                                    msg.version, wire::PROTOCOL_VERSION
                                ),
                                seq: Some(seq),
                                fn_id: Some(fn_id),
                            }));
                        }
                        match msg.msg_type {
                            wire::MSG_PING => {
                                let pong = wire::pack_pong(msg.seq, msg.fn_id, &msg.payload);
                                let _ = ws.send(WsMsg::Binary(pong)).await;
                                continue;
                            }
                            wire::MSG_RESULT | wire::MSG_ERROR => {
                                if msg.seq != seq {
                                    return Err(RustError::Transport(RpcTransportError {
                                        message: format!("seq mismatch: expected {seq}, got {}", msg.seq),
                                        seq: Some(seq),
                                        fn_id: Some(fn_id),
                                    }));
                                }
                                if msg.fn_id != fn_id {
                                    return Err(RustError::Transport(RpcTransportError {
                                        message: format!("fnId mismatch: expected {fn_id}, got {}", msg.fn_id),
                                        seq: Some(seq),
                                        fn_id: Some(fn_id),
                                    }));
                                }
                                if msg.msg_type == wire::MSG_RESULT {
                                    return Ok(msg.payload);
                                }
                                let (err_code, sub_code, message) = wire::decode_error_payload(&msg.payload);
                                return Err(RustError::Rpc(RpcError {
                                    seq,
                                    fn_id,
                                    err_code,
                                    sub_code,
                                    message,
                                }));
                            }
                            _ => continue,
                        }
                    }
                    WsMsg::Ping(data) => {
                        let _ = ws.send(WsMsg::Pong(data)).await;
                    }
                    WsMsg::Pong(_) => continue,
                    WsMsg::Text(_) | WsMsg::Frame(_) => continue,
                    WsMsg::Close(_) => {
                        return Err(RustError::Transport(RpcTransportError {
                            message: "websocket closed".to_string(),
                            seq: Some(seq),
                            fn_id: Some(fn_id),
                        }))
                    }
                }
            }
        })
        .await;

        match res {
            Ok(r) => r,
            Err(_) => Err(RustError::Transport(RpcTransportError {
                message: "timeout waiting response".to_string(),
                seq: Some(seq),
                fn_id: Some(fn_id),
            })),
        }
    }
}
