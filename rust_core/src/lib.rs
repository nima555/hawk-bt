use pyo3::{prelude::*, wrap_pyfunction};

mod codec;
mod decode;
mod engine;
mod errors;
mod wire;
mod ws;
mod encode;

/// PyO3 module entrypoint.
#[pymodule]
fn py_engine_rust(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_class::<engine::RustEngineAsync>()?;
    m.add_function(wrap_pyfunction!(decode::decode_vec_f64_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode::decode_mat_f64_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode::decode_close_step_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode::decode_vec_mat_f64_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode::encode_vec_f64_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode::encode_mat_f64_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode::encode_close_step_py, m)?)?;
    Ok(())
}
