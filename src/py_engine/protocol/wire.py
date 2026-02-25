from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Optional, Tuple

PROTOCOL_VERSION = 1
HEADER_SIZE = 16

# msgType (protocol.js互換)
MSG_RUN    = 1
MSG_RESULT = 2
MSG_ERROR  = 3
MSG_PING   = 4
MSG_PONG   = 5
MSG_PUSH   = 6  # Browser → Agent push (Agent Mode)

# Agent Mode: fnId for analysis result push
FN_ANALYSIS_RESULT = 200

# 16B header layout (Little Endian):
# u8 version, u8 msgType, u16 flags, u32 seq, u16 fnId, u16 reserved, u32 len
_HDR = struct.Struct("<BBHIHHI")


@dataclass(frozen=True)
class Message:
    version: int
    msg_type: int
    flags: int
    seq: int
    fn_id: int
    payload: bytes


def pack_message(msg_type: int, seq: int, fn_id: int, payload: bytes = b"", flags: int = 0) -> bytes:
    if payload is None:
        payload = b""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    payload_b = bytes(payload)
    header = _HDR.pack(
        PROTOCOL_VERSION,
        msg_type,
        flags & 0xFFFF,
        seq & 0xFFFFFFFF,
        fn_id & 0xFFFF,
        0,  # reserved
        len(payload_b) & 0xFFFFFFFF,
    )
    return header + payload_b


def pack_run(seq: int, fn_id: int, payload: bytes = b"") -> bytes:
    return pack_message(MSG_RUN, seq, fn_id, payload)


def pack_result(seq: int, fn_id: int, payload: bytes = b"") -> bytes:
    return pack_message(MSG_RESULT, seq, fn_id, payload)


def pack_error(seq: int, fn_id: int, payload: bytes = b"") -> bytes:
    return pack_message(MSG_ERROR, seq, fn_id, payload)


def unpack_message(frame: bytes) -> Message:
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise TypeError("frame must be bytes-like")
    b = bytes(frame)
    if len(b) < HEADER_SIZE:
        raise ValueError(f"frame too short: {len(b)} < {HEADER_SIZE}")

    version, msg_type, flags, seq, fn_id, _reserved, length = _HDR.unpack_from(b, 0)
    if len(b) < HEADER_SIZE + length:
        raise ValueError(f"payload length mismatch: want {length}, have {len(b) - HEADER_SIZE}")

    payload = b[HEADER_SIZE:HEADER_SIZE + length]
    return Message(
        version=version,
        msg_type=msg_type,
        flags=flags,
        seq=seq,
        fn_id=fn_id,
        payload=payload,
    )


def decode_error_payload(payload: bytes) -> Tuple[int, int, str]:
    """
    ERROR payload format (encoder.js互換):
      u16 errCode, u16 subCode, u32 msgLen, bytes[msgLen] (UTF-8)
    """
    if len(payload) < 8:
        # 仕様違反でも落としすぎない
        return (0, 0, "")
    err_code = int.from_bytes(payload[0:2], "little", signed=False)
    sub_code = int.from_bytes(payload[2:4], "little", signed=False)
    msg_len  = int.from_bytes(payload[4:8], "little", signed=False)
    msg_b = payload[8:8 + msg_len]
    try:
        msg = msg_b.decode("utf-8", errors="replace")
    except Exception:
        msg = ""
    return (err_code, sub_code, msg)
