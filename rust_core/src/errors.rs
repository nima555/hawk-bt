use pyo3::exceptions::{PyNotImplementedError, PyRuntimeError, PyValueError};
use pyo3::PyErr;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RustError {
    #[error("length mismatch: {0}")]
    Length(String),
    #[error("decode error: {0}")]
    Decode(String),
    #[error("{0}")]
    Rpc(#[from] RpcError),
    #[error("{0}")]
    Transport(#[from] RpcTransportError),
    #[error("not implemented: {0}")]
    NotImplemented(String),
}

#[derive(Debug, Error)]
#[error("RpcError(seq={seq}, fnId={fn_id}, err={err_code}, sub={sub_code}): {message}")]
pub struct RpcError {
    pub seq: u32,
    pub fn_id: u16,
    pub err_code: u16,
    pub sub_code: u16,
    pub message: String,
}

#[derive(Debug, Error)]
#[error("RpcTransportError(seq={seq:?}, fnId={fn_id:?}): {message}")]
pub struct RpcTransportError {
    pub message: String,
    pub seq: Option<u32>,
    pub fn_id: Option<u16>,
}

impl From<RustError> for PyErr {
    fn from(err: RustError) -> Self {
        match err {
            RustError::Length(msg) => PyValueError::new_err(msg),
            RustError::Decode(msg) => PyRuntimeError::new_err(msg),
            RustError::Rpc(rpc) => PyRuntimeError::new_err(rpc.to_string()),
            RustError::Transport(tr) => PyRuntimeError::new_err(tr.to_string()),
            RustError::NotImplemented(msg) => PyNotImplementedError::new_err(msg),
        }
    }
}
