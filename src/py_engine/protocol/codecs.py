from __future__ import annotations

import numpy as np
import struct

# ==========
# Binary layout (LE)
# ==========
# VecF64 : u32 n + f64[n]
# MatF64 : u32 rows + u32 cols + f64[rows*cols] (row-major)
# CloseStep:
#   u32 n
#   i32 flags[n]
#   i32 actions[n]
#   f64 ratios[n]
# ==========

_U32 = struct.Struct("<I")

# 明示的にLEのfloat64（ホストエンディアン差事故防止）
_F64_LE = np.dtype("<f8")


# ----------------
# VecF64
# ----------------
def encode_vec_f64(arr: np.ndarray) -> bytes:
    """
    arr: np.ndarray, dtype=float64, shape=(n,)
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError("encode_vec_f64 expects numpy.ndarray")
    arr = np.asarray(arr, dtype=_F64_LE, order="C")

    n = arr.size
    return _U32.pack(n) + arr.tobytes(order="C")


def decode_vec_f64(payload: bytes) -> np.ndarray:
    if len(payload) < 4:
        raise ValueError("VecF64 payload too short")

    n = _U32.unpack_from(payload, 0)[0]
    expected = 4 + 8 * n

    # 厳密：余計な末尾バイトも不正（プロトコル破損検知）
    if len(payload) != expected:
        raise ValueError(f"VecF64 length mismatch: expected {expected}, got {len(payload)}")

    # frombuffer は view（ゼロコピー）
    return np.frombuffer(payload, dtype=_F64_LE, offset=4, count=n)


# ----------------
# MatF64
# ----------------
def encode_mat_f64(mat: np.ndarray) -> bytes:
    """
    mat: np.ndarray, dtype=float64, shape=(rows, cols), row-major
    """
    if not isinstance(mat, np.ndarray):
        raise TypeError("encode_mat_f64 expects numpy.ndarray")
    mat = np.asarray(mat, dtype=_F64_LE, order="C")

    if mat.ndim != 2:
        raise ValueError("MatF64 must be 2D array")

    rows, cols = mat.shape
    header = _U32.pack(rows) + _U32.pack(cols)
    return header + mat.ravel(order="C").tobytes(order="C")


def decode_mat_f64(payload: bytes) -> np.ndarray:
    """
    Returns:
      np.ndarray shape=(rows, cols), dtype=float64 (LE), row-major

    NOTE:
      - 返り値仕様を固定して、上位層（EngineAPI）が迷わないようにする。
      - frombufferベースでゼロコピー（payloadが生存する間はview）。
    """
    if len(payload) < 8:
        raise ValueError("MatF64 payload too short")

    rows = _U32.unpack_from(payload, 0)[0]
    cols = _U32.unpack_from(payload, 4)[0]

    n = rows * cols
    expected = 8 + 8 * n

    if len(payload) != expected:
        raise ValueError(f"MatF64 length mismatch: expected {expected}, got {len(payload)}")

    data = np.frombuffer(payload, dtype=_F64_LE, offset=8, count=n)
    return data.reshape((rows, cols))


# ----------------
# CloseStep
# ----------------
def encode_close_step(
    flags: np.ndarray,
    actions: np.ndarray,
    ratios: np.ndarray,
) -> bytes:
    """
    flags   : np.ndarray[int32], shape=(n,)
    actions : np.ndarray[int32], shape=(n,)
    ratios  : np.ndarray[float64], shape=(n,)
    """
    if not all(isinstance(x, np.ndarray) for x in (flags, actions, ratios)):
        raise TypeError("encode_close_step expects numpy.ndarray inputs")

    flags = np.asarray(flags, dtype=np.int32, order="C")
    actions = np.asarray(actions, dtype=np.int32, order="C")
    ratios = np.asarray(ratios, dtype=_F64_LE, order="C")

    if not (flags.shape == actions.shape == ratios.shape):
        raise ValueError("flags/actions/ratios shape mismatch")

    n = flags.size
    return _U32.pack(n) + flags.tobytes(order="C") + actions.tobytes(order="C") + ratios.tobytes(order="C")


# ----------------
# VecF64 + MatF64
# ----------------
def decode_vec_mat_f64(payload: bytes) -> tuple[np.ndarray, np.ndarray]:
    """
    payload:
      u32 n
      f64[n]
      u32 rows
      u32 cols
      f64[rows*cols]
    """
    if len(payload) < 4:
        raise ValueError("VecMatF64 payload too short")

    n = _U32.unpack_from(payload, 0)[0]
    vec_off = 4
    vec_bytes = 8 * n
    mat_hdr_off = vec_off + vec_bytes

    if len(payload) < mat_hdr_off + 8:
        raise ValueError("VecMatF64 payload missing matrix header")

    rows = _U32.unpack_from(payload, mat_hdr_off)[0]
    cols = _U32.unpack_from(payload, mat_hdr_off + 4)[0]
    mat_data_off = mat_hdr_off + 8

    total = mat_data_off + 8 * rows * cols
    if len(payload) != total:
        raise ValueError(f"VecMatF64 length mismatch: expected {total}, got {len(payload)}")

    vec = np.frombuffer(payload, dtype=_F64_LE, offset=vec_off, count=n)
    mat = np.frombuffer(payload, dtype=_F64_LE, offset=mat_data_off, count=rows * cols)
    return vec, mat.reshape((rows, cols))
