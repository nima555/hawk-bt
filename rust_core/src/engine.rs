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

    pub fn init_candles<'a>(&'a self, py: Python<'a>, ohlc5: &PyAny, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let payload = encode_mat_f64_py(py, ohlc5.extract()?)?;
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let _ = srv.send_run_and_wait(wire::FN_INIT_CANDLES, &payload, dur).await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    /// Reset to a specific episode by index.
    /// Payload: [u32 episode_index, u8 episode_type (0=train, 1=test)]
    pub fn reset_episode<'a>(&'a self, py: Python<'a>, episode_index: u32, episode_type: String, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let type_byte: u8 = if episode_type.to_lowercase() == "test" { 1 } else { 0 };
        let mut payload = Vec::with_capacity(5);
        payload.extend_from_slice(&episode_index.to_le_bytes());
        payload.push(type_byte);

        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let result = srv.send_run_and_wait(wire::FN_RESET_EPISODE, &payload, dur).await?;
            let rows = if result.len() >= 4 {
                u32::from_le_bytes([result[0], result[1], result[2], result[3]])
            } else {
                0
            };
            Ok(rows)
        })?;
        Ok(fut.into())
    }

    /// Get RL config from UI (seed, episode counts, etc.). Returns JSON string.
    pub fn get_rl_config<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let result = srv.send_run_and_wait(wire::FN_GET_RL_CONFIG, &[], dur).await?;
            let json_str = String::from_utf8(result).unwrap_or_else(|_| "{}".to_string());
            Ok(json_str)
        })?;
        Ok(fut.into())
    }

    pub fn step_next<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let _ = srv.send_run_and_wait(wire::FN_STEP_NEXT, &[], dur).await?;
            Ok(())
        })?;
        Ok(fut.into())
    }

    pub fn step_and_sync<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py::<_, PyObject>(py, async move {
            let payload = srv
                .send_run_and_wait(wire::FN_STEP_AND_SYNC, &[], dur)
                .await?;
            Python::with_gil(|py| {
                let (vec_obj, mat_obj) = decode_vec_mat_f64_py(py, &payload)?;
                let tup = PyTuple::new(py, &[mat_obj, vec_obj]);
                Ok(tup.into_py(py))
            })
        })?;
        Ok(fut.into())
    }

    pub fn get_snapshot<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_SNAPSHOT, &[], dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn get_ticket_list<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_TICKET_LIST, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn get_ohlc<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_OHLC, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn fetch_events<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_FETCH_EVENTS, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn end_session<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_END_SESSION, &[], dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &payload))
        })?;
        Ok(fut.into())
    }

    pub fn get_sync_policy<'a>(&'a self, py: Python<'a>, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(5.0));
        let fut = future_into_py(py, async move {
            let payload = srv.send_run_and_wait(wire::FN_GET_SYNC_POLICY, &[], dur).await?;
            let result = if payload.is_empty() {
                None
            } else {
                match payload[0] {
                    1 => Some("eager".to_string()),
                    0 => Some("deferred".to_string()),
                    _ => None,
                }
            };
            Ok(result)
        })?;
        Ok(fut.into())
    }

    pub fn close_positions<'a>(&'a self, py: Python<'a>, position_ids: &PyAny, actions: &PyAny, ratios: &PyAny, timeout_secs: Option<f64>) -> PyResult<PyObject> {
        let ids_arr: Vec<i32> = position_ids.extract()?;
        let actions_arr: Vec<i32> = actions.extract()?;
        let ratios_arr: Vec<f64> = ratios.extract()?;
        if !(ids_arr.len() == actions_arr.len() && actions_arr.len() == ratios_arr.len()) {
            return Err(pyo3::exceptions::PyValueError::new_err("close_positions: arrays must have equal length"));
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
        let payload = codec::encode_close_step(&ids_arr, &actions_arr, &ratios_norm)?;
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_CLOSE_POSITIONS, &payload, dur).await?;
            Python::with_gil(|py| decode_mat_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }

    pub fn place_order<'a>(
        &'a self,
        py: Python<'a>,
        side: String,
        order_type: String,
        price: f64,
        units: i32,
        take_profit: Option<f64>,
        stop_loss: Option<f64>,
        trailing_stop: Option<f64>,
        time_limit: Option<f64>,
        timeout_secs: Option<f64>,
    ) -> PyResult<PyObject> {
        let side_n = side.trim().to_ascii_lowercase();
        if side_n != "buy" && side_n != "sell" {
            return Err(pyo3::exceptions::PyValueError::new_err("side must be 'buy' or 'sell'"));
        }
        let order_n = order_type.trim().to_ascii_lowercase();
        if order_n != "limit" && order_n != "stop" {
            return Err(pyo3::exceptions::PyValueError::new_err("order_type must be 'limit' or 'stop'"));
        }
        if !price.is_finite() {
            return Err(pyo3::exceptions::PyValueError::new_err("price must be finite"));
        }
        if units <= 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("units must be > 0"));
        }
        let opt_flag = |v: Option<f64>| if v.is_some() { 1.0 } else { -1.0 };
        let to_slot = |p: f64| -> PyResult<f64> {
            if !p.is_finite() || p < 0.0 {
                Err(pyo3::exceptions::PyValueError::new_err("value must be finite and >= 0"))
            } else {
                Ok(p * 100.0 - 1.0)
            }
        };

        let mut buf = vec![0.0f64; 13];
        buf[0] = 1.0;
        buf[1] = price;
        buf[2] = opt_flag(take_profit);
        buf[3] = opt_flag(stop_loss);
        buf[4] = opt_flag(trailing_stop);
        buf[5] = opt_flag(time_limit);
        buf[6] = if side_n == "buy" { 1.0 } else { -1.0 };
        buf[7] = if order_n == "limit" { 1.0 } else { -1.0 };
        buf[8] = units as f64;
        buf[9] = take_profit.map_or(0.0, |p| to_slot(p).unwrap());
        buf[10] = stop_loss.map_or(0.0, |p| to_slot(p).unwrap());
        buf[11] = trailing_stop.map_or(0.0, |p| to_slot(p).unwrap());
        buf[12] = time_limit.unwrap_or(0.0);

        let payload = codec::encode_vec_f64(&buf);
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_PLACE_ORDER, &payload, dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }

    pub fn place_ticket<'a>(
        &'a self,
        py: Python<'a>,
        side: String,
        units: i32,
        take_profit: Option<f64>,
        stop_loss: Option<f64>,
        trailing_stop: Option<f64>,
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
        let to_slot = |p: f64| -> PyResult<f64> {
            if !p.is_finite() || p < 0.0 {
                Err(pyo3::exceptions::PyValueError::new_err("value must be finite and >= 0"))
            } else {
                Ok(p - 1.0)
            }
        };

        let mut buf = vec![0.0f64; 9];
        buf[0] = 1.0;
        buf[1] = opt_if(take_profit);
        buf[2] = opt_if(stop_loss);
        buf[3] = opt_if(trailing_stop);
        buf[4] = if side_n == "buy" { 1.0 } else { 0.0 };
        buf[5] = units as f64;
        buf[6] = take_profit.map_or(0.0, |p| to_slot(p).unwrap());
        buf[7] = stop_loss.map_or(0.0, |p| to_slot(p).unwrap());
        buf[8] = trailing_stop.map_or(0.0, |p| to_slot(p).unwrap());

        let payload = codec::encode_vec_f64(&buf);
        let srv = self.server.clone();
        let dur = Duration::from_secs_f64(timeout_secs.unwrap_or(10.0));
        let fut = future_into_py(py, async move {
            let out = srv.send_run_and_wait(wire::FN_PLACE_TICKET, &payload, dur).await?;
            Python::with_gil(|py| decode_vec_f64_py(py, &out))
        })?;
        Ok(fut.into())
    }
}
