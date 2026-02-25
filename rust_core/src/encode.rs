use numpy::{PyReadonlyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

use crate::codec;

#[inline(always)]
#[pyfunction]
pub fn encode_vec_f64_py(_py: Python<'_>, arr: PyReadonlyArray1<f64>) -> PyResult<Vec<u8>> {
    let slice = arr.as_slice()?;
    Ok(codec::encode_vec_f64(slice))
}

#[inline(always)]
#[pyfunction]
pub fn encode_mat_f64_py(_py: Python<'_>, mat: PyReadonlyArray2<f64>) -> PyResult<Vec<u8>> {
    let shape = mat.shape();
    if shape.len() != 2 {
        return Err(pyo3::exceptions::PyValueError::new_err("MatF64 must be 2D"));
    }
    let rows = shape[0];
    let cols = shape[1];
    let slice = mat.as_slice()?;
    Ok(codec::encode_mat_f64(rows, cols, slice)?)
}

#[inline(always)]
#[pyfunction]
pub fn encode_close_step_py(
    _py: Python<'_>,
    flags: PyReadonlyArray1<i32>,
    actions: PyReadonlyArray1<i32>,
    ratios: PyReadonlyArray1<f64>,
) -> PyResult<Vec<u8>> {
    let f = flags.as_slice()?;
    let a = actions.as_slice()?;
    let r = ratios.as_slice()?;
    Ok(codec::encode_close_step(f, a, r)?)
}
