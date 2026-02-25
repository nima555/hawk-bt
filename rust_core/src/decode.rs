use numpy::{IntoPyArray, PyArray1, PyArray2};
use pyo3::prelude::*;

use crate::codec;
use crate::errors::RustError;

/// Decode VecF64 payload into numpy.ndarray(float64, shape=(n,))
#[inline(always)]
#[pyfunction]
pub fn decode_vec_f64_py(py: Python<'_>, payload: &[u8]) -> PyResult<PyObject> {
    let vec = codec::decode_vec_f64(payload)?;
    Ok(vec.into_pyarray(py).into_py(py))
}

/// Decode MatF64 payload into numpy.ndarray(float64, shape=(rows, cols))
#[inline(always)]
#[pyfunction]
pub fn decode_mat_f64_py(py: Python<'_>, payload: &[u8]) -> PyResult<PyObject> {
    let (_rows, cols, data) = codec::decode_mat_f64(payload)?;
    // PyArray2::from_vec2 は追加コピーが入るが、APIが安定している方法を使う
    let rows_vec: Vec<Vec<f64>> = data.chunks(cols as usize).map(|c| c.to_vec()).collect();
    let arr = PyArray2::from_vec2(py, &rows_vec)
        .map_err(|e| RustError::Decode(format!("reshape failed: {e}")))?;
    Ok(arr.into_py(py))
}

/// Decode CloseStep payload into tuple(flags, actions, ratios) as numpy arrays.
#[inline(always)]
#[pyfunction]
pub fn decode_close_step_py(py: Python<'_>, payload: &[u8]) -> PyResult<(PyObject, PyObject, PyObject)> {
    let (flags, actions, ratios) = codec::decode_close_step(payload)?;
    let f = PyArray1::from_vec(py, flags);
    let a = PyArray1::from_vec(py, actions);
    let r = PyArray1::from_vec(py, ratios);
    Ok((f.into_py(py), a.into_py(py), r.into_py(py)))
}

/// Decode VecF64 + MatF64 payload into (vec, mat).
#[inline(always)]
#[pyfunction]
pub fn decode_vec_mat_f64_py(py: Python<'_>, payload: &[u8]) -> PyResult<(PyObject, PyObject)> {
    let (vec, _rows, cols, data) = codec::decode_vec_mat_f64(payload)?;
    let v = vec.into_pyarray(py).into_py(py);
    let rows_vec: Vec<Vec<f64>> = data.chunks(cols as usize).map(|c| c.to_vec()).collect();
    let mat = PyArray2::from_vec2(py, &rows_vec)
        .map_err(|e| RustError::Decode(format!("reshape failed: {e}")))?;
    Ok((v, mat.into_py(py)))
}
