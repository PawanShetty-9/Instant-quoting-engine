"""Untrusted CAD file handling.

Uploaded files are parsed in a *separate process* (forkserver with OCP
preloaded) so that a malicious or pathological file can neither crash nor
starve the API process:

* content sniffing (magic bytes) instead of trusting the file extension
* hard wall-clock timeout (process is killed), address-space and CPU limits
* the file lives in a private temp directory that is removed afterwards
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import resource
import struct
import tempfile
from dataclasses import dataclass
from typing import Literal

from app.cad.brep import CadParseError

CadFormat = Literal["STEP", "IGES", "STL"]
ALLOWED_EXTENSIONS = {".step": "STEP", ".stp": "STEP", ".igs": "IGES", ".iges": "IGES", ".stl": "STL"}

_CTX = mp.get_context("forkserver")
_CTX.set_forkserver_preload(["app.cad.brep", "app.cad.stl"])


class CadTimeoutError(RuntimeError):
    pass


@dataclass
class ParsedCad:
    format: CadFormat
    bounding_box: list[float]
    volume_cm3: float
    surface_area_cm2: float
    features: dict[str, int]
    diagnostics: dict
    preview_stl: bytes | None


def sniff_format(data: bytes, filename: str) -> CadFormat:
    """Identify the file by content; the extension must agree."""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise CadParseError(f"unsupported file type '{ext or filename}' - upload STEP (.step/.stp)")
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"ISO-10303-21"):
        detected: CadFormat = "STEP"
    elif len(data) > 80 and data[72:73] == b"S" and data[73:80].strip().isdigit():
        # IGES: fixed 80-column records, column 73 of the first record is the 'S'tart section.
        detected = "IGES"
    elif len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        detected = "STL"
    elif head[:5].lower() == b"solid" and b"facet" in data[:8192]:
        detected = "STL"
    else:
        raise CadParseError("file content is not a STEP, IGES or STL file")
    if ALLOWED_EXTENSIONS[ext] != detected:
        raise CadParseError(f"file extension '{ext}' does not match its content ({detected})")
    return detected


def _worker(
    conn, path: str, fmt: CadFormat, unit_scale: float, max_triangles: int, mem_limit_mb: int, cpu_limit_s: int
) -> None:
    try:
        # Limit *additional* address space on top of what the preloaded libraries map.
        with open("/proc/self/status") as fh:
            vm_kb = next(int(line.split()[1]) for line in fh if line.startswith("VmSize:"))
        limit = vm_kb * 1024 + mem_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_s, cpu_limit_s + 1))
    except (OSError, ValueError, StopIteration):  # pragma: no cover - non-Linux
        pass
    try:
        if fmt == "STEP":
            from app.cad.brep import analyse_step_file

            result = analyse_step_file(path, max_triangles=max_triangles)
        elif fmt == "IGES":
            from app.cad.brep import analyse_iges_file

            result = analyse_iges_file(path, max_triangles=max_triangles)
        else:
            from app.cad.stl import analyse_stl_bytes

            with open(path, "rb") as fh:
                result = analyse_stl_bytes(fh.read(), unit_scale=unit_scale, max_triangles=max_triangles)
        conn.send(("ok", result))
    except CadParseError as exc:
        conn.send(("invalid", str(exc)))
    except MemoryError:
        conn.send(("invalid", "file too complex (memory limit exceeded)"))
    except Exception as exc:  # noqa: BLE001 - report, never crash the parent
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def parse_cad_bytes(
    data: bytes,
    filename: str,
    *,
    unit_scale: float = 1.0,
    timeout_s: float = 45.0,
    mem_limit_mb: int = 2048,
    max_triangles: int = 150_000,
) -> ParsedCad:
    """Blocking call - run it in a worker thread from async code."""
    fmt = sniff_format(data, filename)
    with tempfile.TemporaryDirectory(prefix="quote-cad-") as tmp:
        path = os.path.join(tmp, "upload" + {"STEP": ".step", "IGES": ".igs", "STL": ".stl"}[fmt])
        with open(path, "wb") as fh:
            fh.write(data)
        os.chmod(path, 0o600)

        recv, send = _CTX.Pipe(duplex=False)
        proc = _CTX.Process(
            target=_worker,
            args=(send, path, fmt, unit_scale, max_triangles, mem_limit_mb, int(timeout_s) + 5),
            daemon=True,
        )
        proc.start()
        send.close()
        try:
            if not recv.poll(timeout_s):
                raise CadTimeoutError(f"CAD analysis exceeded {timeout_s:.0f} s")
            try:
                status, payload = recv.recv()
            except EOFError as exc:
                raise CadParseError("CAD kernel aborted while reading the file") from exc
        finally:
            with contextlib.suppress(Exception):
                recv.close()
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)

    if status == "invalid":
        raise CadParseError(payload)
    if status != "ok":
        raise CadParseError(f"CAD analysis failed ({payload})")
    return ParsedCad(
        format=payload["format"],
        bounding_box=payload["bounding_box"],
        volume_cm3=payload["volume_cm3"],
        surface_area_cm2=payload["surface_area_cm2"],
        features=payload["features"],
        diagnostics=payload["diagnostics"],
        preview_stl=payload.get("preview_stl"),
    )
