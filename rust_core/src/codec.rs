use crate::errors::RustError;

#[inline(always)]
fn ensure_payload_len(actual: usize, expected: usize, label: &str) -> Result<(), RustError> {
    if actual != expected {
        return Err(RustError::Length(format!(
            "{} length mismatch: expected {}, got {}",
            label, expected, actual
        )));
    }
    Ok(())
}

#[inline(always)]
pub fn encode_vec_f64(data: &[f64]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + data.len() * 8);
    out.extend_from_slice(&(data.len() as u32).to_le_bytes());
    for &v in data {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

#[inline(always)]
pub fn decode_vec_f64(payload: &[u8]) -> Result<Vec<f64>, RustError> {
    if payload.len() < 4 {
        return Err(RustError::Length("VecF64 payload too short".to_string()));
    }
    let n = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]) as usize;
    let expected = 4 + n * 8;
    ensure_payload_len(payload.len(), expected, "VecF64")?;

    let mut out = Vec::with_capacity(n);
    let mut idx = 4;
    for _ in 0..n {
        let mut buf = [0u8; 8];
        buf.copy_from_slice(&payload[idx..idx + 8]);
        out.push(f64::from_le_bytes(buf));
        idx += 8;
    }
    Ok(out)
}

#[inline(always)]
pub fn encode_mat_f64(rows: usize, cols: usize, data: &[f64]) -> Result<Vec<u8>, RustError> {
    let expected_len = rows
        .checked_mul(cols)
        .ok_or_else(|| RustError::Length("rows*cols overflow".to_string()))?;
    if data.len() != expected_len {
        return Err(RustError::Length(format!(
            "MatF64 data length mismatch: expected {}, got {}",
            expected_len,
            data.len()
        )));
    }
    let mut out = Vec::with_capacity(8 + expected_len * 8);
    out.extend_from_slice(&(rows as u32).to_le_bytes());
    out.extend_from_slice(&(cols as u32).to_le_bytes());
    for &v in data {
        out.extend_from_slice(&v.to_le_bytes());
    }
    Ok(out)
}

#[inline(always)]
pub fn decode_mat_f64(payload: &[u8]) -> Result<(u32, u32, Vec<f64>), RustError> {
    if payload.len() < 8 {
        return Err(RustError::Length("MatF64 payload too short".to_string()));
    }
    let rows = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]);
    let cols = u32::from_le_bytes([payload[4], payload[5], payload[6], payload[7]]);
    let n = rows as usize
        * cols as usize;
    let expected = 8 + n * 8;
    ensure_payload_len(payload.len(), expected, "MatF64")?;

    let mut out = Vec::with_capacity(n);
    let mut idx = 8;
    for _ in 0..n {
        let mut buf = [0u8; 8];
        buf.copy_from_slice(&payload[idx..idx + 8]);
        out.push(f64::from_le_bytes(buf));
        idx += 8;
    }
    Ok((rows, cols, out))
}

#[inline(always)]
pub fn decode_close_step(payload: &[u8]) -> Result<(Vec<i32>, Vec<i32>, Vec<f64>), RustError> {
    if payload.len() < 4 {
        return Err(RustError::Length("CloseStep payload too short".to_string()));
    }
    let n = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]) as usize;
    let need = 4 + n * (4 + 4 + 8);
    ensure_payload_len(payload.len(), need, "CloseStep")?;

    let mut flags = Vec::with_capacity(n);
    let mut actions = Vec::with_capacity(n);
    let mut ratios = Vec::with_capacity(n);

    let mut off = 4;
    for _ in 0..n {
        let mut b = [0u8; 4];
        b.copy_from_slice(&payload[off..off + 4]);
        flags.push(i32::from_le_bytes(b));
        off += 4;
    }
    for _ in 0..n {
        let mut b = [0u8; 4];
        b.copy_from_slice(&payload[off..off + 4]);
        actions.push(i32::from_le_bytes(b));
        off += 4;
    }
    for _ in 0..n {
        let mut b = [0u8; 8];
        b.copy_from_slice(&payload[off..off + 8]);
        ratios.push(f64::from_le_bytes(b));
        off += 8;
    }

    Ok((flags, actions, ratios))
}
#[inline(always)]
pub fn encode_close_step(flags: &[i32], actions: &[i32], ratios: &[f64]) -> Result<Vec<u8>, RustError> {
    if !(flags.len() == actions.len() && actions.len() == ratios.len()) {
        return Err(RustError::Length(format!(
            "close_step shape mismatch: flags={}, actions={}, ratios={}",
            flags.len(),
            actions.len(),
            ratios.len()
        )));
    }
    let n = flags.len();
    let mut out = Vec::with_capacity(4 + n * (4 + 4 + 8));
    out.extend_from_slice(&(n as u32).to_le_bytes());
    for &v in flags {
        out.extend_from_slice(&v.to_le_bytes());
    }
    for &v in actions {
        out.extend_from_slice(&v.to_le_bytes());
    }
    for &v in ratios {
        out.extend_from_slice(&v.to_le_bytes());
    }
    Ok(out)
}

#[inline(always)]
pub fn decode_vec_mat_f64(payload: &[u8]) -> Result<(Vec<f64>, u32, u32, Vec<f64>), RustError> {
    if payload.len() < 4 {
        return Err(RustError::Length("VecMatF64 payload too short".to_string()));
    }
    let n = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]) as usize;
    let vec_off = 4;
    let vec_bytes = vec_off + n * 8;
    if payload.len() < vec_bytes + 8 {
        return Err(RustError::Length("VecMatF64 missing matrix header".to_string()));
    }
    let rows = u32::from_le_bytes([
        payload[vec_bytes],
        payload[vec_bytes + 1],
        payload[vec_bytes + 2],
        payload[vec_bytes + 3],
    ]);
    let cols = u32::from_le_bytes([
        payload[vec_bytes + 4],
        payload[vec_bytes + 5],
        payload[vec_bytes + 6],
        payload[vec_bytes + 7],
    ]);
    let mat_len = rows as usize * cols as usize;
    let expected = vec_bytes + 8 + mat_len * 8;
    ensure_payload_len(payload.len(), expected, "VecMatF64")?;

    let mut vec = Vec::with_capacity(n);
    let mut idx = vec_off;
    for _ in 0..n {
        let mut buf = [0u8; 8];
        buf.copy_from_slice(&payload[idx..idx + 8]);
        vec.push(f64::from_le_bytes(buf));
        idx += 8;
    }

    let mut data = Vec::with_capacity(mat_len);
    idx = vec_bytes + 8;
    for _ in 0..mat_len {
        let mut buf = [0u8; 8];
        buf.copy_from_slice(&payload[idx..idx + 8]);
        data.push(f64::from_le_bytes(buf));
        idx += 8;
    }
    Ok((vec, rows, cols, data))
}
