use pyo3::prelude::*;
use pyo3::types::{PyAny, PyTuple};
use pyo3_asyncio::tokio::future_into_py;
use std::time::Duration;

use crate::decode::{decode_mat_f64_py, decode_vec_f64_py, decode_vec_mat_f64_py};
use crate::encode::encode_mat_f64_py;
use crate::ws::WsServer;
use crate::{codec, wire};

#[pyclass]
pub struct RustEngineAsync {
    server: WsServer,
}

#[pymethods]
impl RustEngineAsync {
    #[new]
    pub fn new(host: String, port: u16, start_seq: Option<u32>) -> Self {
        Self {
            server: WsServer::new(&host, port, start_seq.unwrap_or(1)),
        }
    }

    pub fn start<'a>(&'a self, py: Python<'a>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let fut = future_into_py(py, async move {
            srv.start().await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    pub fn wait_connected<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = timeout_secs.map(Duration::from_secs_f64);
        let fut = future_into_py(py, async move {
            srv.wait_connected(dur).await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    pub fn init_ohlc5<'a>(&'a self, py: Python<'a>, ohlc5: &PyAny, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let payload = encode_mat_f64_py(py, ohlc5.extract()?)?;
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let _ = srv.send_run_and_wait(wire::FN_INIT as u16, &payload, dur).await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    /// Reset to a specific episode by index
    /// payload: [u32 episode_index, u8 episode_type (0=train, 1=test)]
    pub fn reset_episode<'a>(&'a self, py: Python<'a>, episode_index: u32, episode_type: String, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let type_byte: u8 = if episode_type.to_lowercase() == "test" { 1 } else { 0 };
        let mut payload = Vec::with_capacity(5);
        payload.extend_from_slice(&episode_index.to_le_bytes());
        payload.push(type_byte);

        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let result = srv.send_run_and_wait(wire::FN_RESET_EPISODE as u16, &payload, dur).await?;
            // result contains [u32 rows_count]
            let rows = if result.len() >= 4 {
                u32::from_le_bytes([result[0], result[1], result[2], result[3]])
            } else {
                0
            };
            Ok(rows)
        })?;
        Ok(fut.into())
    }

    /// Get RL config from UI (seed, episode counts, etc.)
    /// Returns JSON string
    pub fn get_rl_config<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let result = srv.send_run_and_wait(wire::FN_GET_RL_CONFIG as u16, &[], dur).await?;
            // result contains JSON string as UTF-8 bytes
            let json_str = String::from_utf8(result).unwrap_or_else(|_| "{}".to_string());
            Ok(json_str)
        })?;
        Ok(fut.into())
    }

    pub fn step_next<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let _ = srv.send_run_and_wait(wire::FN_STEP_NEXT as u16, &[], dur).await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    pub fn step_next_affect_statics<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py::<_, PyObject>(py, async move {
            let payload = srv
                .send_run_and_wait(wire::FN_STEP_NEXT_AFFECT_STATICS as u16, &[], dur)
                .await?;
            Python::with_gil(|py| {
                let (vec_obj, mat_obj) = decode_vec_mat_f64_py(py, &payload)?;
                let tup = PyTuple::new(py, &[mat_obj, vec_obj]);
                Ok(tup.into_py(py))
            })
        })?;
        Ok(fut.into())
    }

    pub fn get_statics<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_STATICS as u16, &[], dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn get_ticket_list<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_TICKET_LIST as u16, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn affect<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_AFFECT as u16, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn game_end<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GAME_END as u16, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn get_gate_policy_hint<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(5.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_GATE_POLICY as u16, &[], dur).await?;
            let result = if payload.is_empty() {
                None
            } else {
                match payload[0] {
                    1 => Some("eager".to_string()),
                    0 => Some("step_end".to_string()),
                    _ => None,
                }
            };
            Ok(result)
        })?;
        Ok(fut.into())
    }

    pub fn close_step<'a>(&'a self, py: Python<'a>, flags: &PyAny, actions: &PyAny, ratios: &PyAny, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let flags_arr: Vec<i32> = flags.extract()?;
        let actions_arr: Vec<i32> = actions.extract()?;
        let ratios_arr: Vec<f64> = ratios.extract()?;
        if !(flags_arr.len() == actions_arr.len() && actions_arr.len() == ratios_arr.len()) {
            return Err(pyo3::exceptions::PyValueError::new_err("close_step shape mismatch"));
        }
        let mut ratios_norm = ratios_arr.clone();
        for (a, r) in actions_arr.iter().zip(ratios_norm.iter_mut()) {
            if *a == wire::ACTION_REDUCE {
                if !(*r >= 0.0 && *r <= 1.0) {
                    return Err(pyo3::exceptions::PyValueError::new_err("ratio out of range for reduce"));
                }
            } else {
                *r = 0.0;
            }
        }
        let payload = codec::encode_close_step(&flags_arr, &actions_arr, &ratios_norm)?;
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_CLOSE_STEP as u16, &payload, dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }

    pub fn place_token<'a>(
        &'a self,
        py: Python<'a>,
        side: String,
        order: String,
        price: f64,
        units: i32,
        sub_limit_pips: Option<f64>,
        stop_order_pips: Option<f64>,
        trail_pips: Option<f64>,
        time_limits: Option<f64>,
        timeout_secs: Option<f64>,
    ) -> PyResult<PyObject> {
        let side_n = side.trim().to_ascii_lowercase();
        if side_n != "buy" && side_n != "sell" {
            return Err(pyo3::exceptions::PyValueError::new_err("side must be 'buy' or 'sell'"));
        }
        let order_n = order.trim().to_ascii_lowercase();
        if order_n != "limit" && order_n != "stop" {
            return Err(pyo3::exceptions::PyValueError::new_err("order must be 'limit' or 'stop'"));
        }
        if !price.is_finite() {
            return Err(pyo3::exceptions::PyValueError::new_err("price must be finite"));
        }
        if units <= 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("units must be > 0"));
        }
        let opt_flag = |v: Option<f64>| if v.is_some() { 1.0 } else { -1.0 };
        let pips_to_slot = |p: f64| -> PyResult<f64> {
            if !p.is_finite() || p < 0.0 {
                Err(pyo3::exceptions::PyValueError::new_err("pips must be finite and >=0"))
            } else {
                Ok(p * 100.0 - 1.0)
            }
        };

        let mut actions = vec![0.0f64; 13];
        actions[0] = 1.0;
        actions[1] = price;
        actions[2] = opt_flag(sub_limit_pips);
        actions[3] = opt_flag(stop_order_pips);
        actions[4] = opt_flag(trail_pips);
        actions[5] = opt_flag(time_limits);
        actions[6] = if side_n == "buy" { 1.0 } else { -1.0 };
        actions[7] = if order_n == "limit" { 1.0 } else { -1.0 };
        actions[8] = units as f64;
        actions[9] = sub_limit_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());
        actions[10] = stop_order_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());
        actions[11] = trail_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());
        actions[12] = time_limits.unwrap_or(0.0);

        let payload = codec::encode_vec_f64(&actions);
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_STEP_MAKE_TOKEN as u16, &payload, dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }

    pub fn place_ticket<'a>(
        &'a self,
        py: Python<'a>,
        side: String,
        units: i32,
        sub_limit_pips: Option<f64>,
        stop_order_pips: Option<f64>,
        trail_pips: Option<f64>,
        timeout_secs: Option<f64>,
    ) -> PyResult<PyObject> {
        let side_n = side.trim().to_ascii_lowercase();
        if side_n != "buy" && side_n != "sell" {
            return Err(pyo3::exceptions::PyValueError::new_err("side must be 'buy' or 'sell'"));
        }
        if units <= 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("units must be > 0"));
        }
        let opt_if = |v: Option<f64>| if v.is_some() { 1.0 } else { 0.0 };
        let pips_to_slot = |p: f64| -> PyResult<f64> {
            if !p.is_finite() || p < 0.0 {
                Err(pyo3::exceptions::PyValueError::new_err("pips must be finite and >=0"))
            } else {
                Ok(p - 1.0)
            }
        };

        let mut actions = vec![0.0f64; 9];
        actions[0] = 1.0;
        actions[1] = opt_if(sub_limit_pips);
        actions[2] = opt_if(stop_order_pips);
        actions[3] = opt_if(trail_pips);
        actions[4] = if side_n == "buy" { 1.0 } else { 0.0 };
        actions[5] = units as f64;
        actions[6] = sub_limit_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());
        actions[7] = stop_order_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());
        actions[8] = trail_pips.map_or(0.0, |p| pips_to_slot(p).unwrap());

        let payload = codec::encode_vec_f64(&actions);
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_STEP_MAKE_TICKET as u16, &payload, dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }
}

/// Placeholder for the existing Python rust_bridge PoC. This keeps imports stable
/// until the real batch/statics implementation is ported.
#[pyfunction]
pub fn run_batch_placeholder(_ohlc5: &PyAny) -> PyResult<PyObject> {
    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "run_batch is not implemented in Rust yet",
    ))
}
