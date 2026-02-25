use crate::errors::RustError;

pub const PROTOCOL_VERSION: u8 = 1;
pub const HEADER_SIZE: usize = 16;

pub const MSG_RUN: u8 = 1;
pub const MSG_RESULT: u8 = 2;
pub const MSG_ERROR: u8 = 3;
pub const MSG_PING: u8 = 4;
pub const MSG_PONG: u8 = 5;

// fn IDs (EngineAPI)
pub const FN_INIT: u16 = 100;
pub const FN_RESET_EPISODE: u16 = 101;  // RL: Reset to specific episode by index
pub const FN_GET_RL_CONFIG: u16 = 102;  // RL: Get RL config (seed, etc.) from UI
pub const FN_STEP_NEXT: u16 = 2;
pub const FN_STEP_NEXT_AFFECT_STATICS: u16 = 130;
pub const FN_GET_STATICS: u16 = 12;
pub const FN_GET_TICKET_LIST: u16 = 10;
pub const FN_AFFECT: u16 = 30;
pub const FN_GAME_END: u16 = 40;
pub const FN_CLOSE_STEP: u16 = 31;
pub const FN_STEP_MAKE_TOKEN: u16 = 20;
pub const FN_STEP_MAKE_TICKET: u16 = 21;
pub const FN_GET_GATE_POLICY: u16 = 120;

pub const ACTION_REDUCE: i32 = 2;

#[derive(Debug, Clone)]
pub struct Message {
    pub version: u8,
    pub msg_type: u8,
    pub flags: u16,
    pub seq: u32,
    pub fn_id: u16,
    pub payload: Vec<u8>,
}

#[inline(always)]
pub fn pack_message(msg_type: u8, seq: u32, fn_id: u16, payload: &[u8], flags: u16) -> Vec<u8> {
    let payload_len = payload.len() as u32;
    let mut out = Vec::with_capacity(HEADER_SIZE + payload.len());
    out.push(PROTOCOL_VERSION);
    out.push(msg_type);
    out.extend_from_slice(&flags.to_le_bytes());
    out.extend_from_slice(&seq.to_le_bytes());
    out.extend_from_slice(&fn_id.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes()); // reserved
    out.extend_from_slice(&payload_len.to_le_bytes());
    out.extend_from_slice(payload);
    out
}

#[inline(always)]
pub fn pack_run(seq: u32, fn_id: u16, payload: &[u8]) -> Vec<u8> {
    pack_message(MSG_RUN, seq, fn_id, payload, 0)
}

#[inline(always)]
pub fn pack_pong(seq: u32, fn_id: u16, payload: &[u8]) -> Vec<u8> {
    pack_message(MSG_PONG, seq, fn_id, payload, 0)
}

#[inline(always)]
pub fn unpack_message(frame: &[u8]) -> Result<Message, RustError> {
    if frame.len() < HEADER_SIZE {
        return Err(RustError::Length(format!(
            "frame too short: {} < {}",
            frame.len(),
            HEADER_SIZE
        )));
    }

    let version = frame[0];
    let msg_type = frame[1];
    let flags = u16::from_le_bytes([frame[2], frame[3]]);
    let seq = u32::from_le_bytes([frame[4], frame[5], frame[6], frame[7]]);
    let fn_id = u16::from_le_bytes([frame[8], frame[9]]);
    let _reserved = u16::from_le_bytes([frame[10], frame[11]]);
    let payload_len = u32::from_le_bytes([frame[12], frame[13], frame[14], frame[15]]) as usize;

    let expected = HEADER_SIZE + payload_len;
    if frame.len() != expected {
        return Err(RustError::Length(format!(
            "payload length mismatch: expected {}, got {}",
            expected,
            frame.len()
        )));
    }

    let payload = frame[HEADER_SIZE..expected].to_vec();

    Ok(Message {
        version,
        msg_type,
        flags,
        seq,
        fn_id,
        payload,
    })
}

/// ERROR payload: u16 errCode, u16 subCode, u32 msgLen, bytes msg (utf-8)
#[inline(always)]
pub fn decode_error_payload(payload: &[u8]) -> (u16, u16, String) {
    if payload.len() < 8 {
        return (0, 0, String::new());
    }
    let err_code = u16::from_le_bytes([payload[0], payload[1]]);
    let sub_code = u16::from_le_bytes([payload[2], payload[3]]);
    let msg_len = u32::from_le_bytes([payload[4], payload[5], payload[6], payload[7]]) as usize;
    let msg_bytes = payload.get(8..8 + msg_len).unwrap_or(&[]);
    let msg = String::from_utf8_lossy(msg_bytes).to_string();
    (err_code, sub_code, msg)
}
