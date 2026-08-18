"""Lightweight TShark executable resolution and runtime preflight."""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from core.config import TSHARK_EXECUTABLE


TSHARK_VERSION_TIMEOUT_SECONDS = 5
_RUNTIME_CHECKS: Dict[str, Dict[str, object]] = {}


def _configured_executable(executable: Optional[str]) -> str:
    value = TSHARK_EXECUTABLE if executable is None else executable
    return str(value).strip()


def _resolve_uncached(configured: str) -> str:
    if not configured:
        raise FileNotFoundError("TShark executable not found: not configured")

    candidate = Path(configured)
    if candidate.is_absolute():
        if not candidate.is_file():
            raise FileNotFoundError(f"TShark executable not found: {configured}")
        return str(candidate)

    resolved = shutil.which(configured)
    if not resolved:
        raise FileNotFoundError(f"TShark executable not found: {configured}")
    return resolved


def resolve_tshark_executable(executable: Optional[str] = None) -> str:
    """Resolve one configured TShark executable without starting a query."""
    configured = _configured_executable(executable)
    cached = _RUNTIME_CHECKS.get(configured)
    if cached is not None and cached.get("status") == "ERROR":
        raise RuntimeError(str(cached["message"]))
    return _resolve_uncached(configured)


def check_tshark_runtime(executable: Optional[str] = None) -> Dict[str, object]:
    """Resolve TShark and run a bounded ``--version`` preflight."""
    configured = _configured_executable(executable)
    try:
        resolved = _resolve_uncached(configured)
    except (FileNotFoundError, OSError) as exc:
        result = {
            "status": "ERROR",
            "configured": configured,
            "resolved": None,
            "message": str(exc),
        }
        _RUNTIME_CHECKS[configured] = result
        return result

    try:
        completed = subprocess.run(
            [resolved, "--version"],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TSHARK_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        result = {
            "status": "ERROR",
            "configured": configured,
            "resolved": resolved,
            "message": f"TShark executable not found: {configured}",
        }
    except subprocess.TimeoutExpired:
        result = {
            "status": "ERROR",
            "configured": configured,
            "resolved": resolved,
            "message": (
                "TShark version check timed out after "
                f"{TSHARK_VERSION_TIMEOUT_SECONDS} seconds"
            ),
        }
    except OSError as exc:
        result = {
            "status": "ERROR",
            "configured": configured,
            "resolved": resolved,
            "message": f"TShark version check failed: {exc}",
        }
    else:
        if completed.returncode == 0:
            result = {
                "status": "OK",
                "configured": configured,
                "resolved": resolved,
                "message": "",
            }
        else:
            stderr = str(completed.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            result = {
                "status": "ERROR",
                "configured": configured,
                "resolved": resolved,
                "message": (
                    "TShark version check failed with exit code "
                    f"{completed.returncode}{detail}"
                ),
            }

    _RUNTIME_CHECKS[configured] = result
    return result


def cached_tshark_runtime_error(executable: Optional[str] = None) -> Optional[str]:
    """Return a prior preflight error, if startup already found one."""
    configured = _configured_executable(executable)
    cached = _RUNTIME_CHECKS.get(configured)
    if cached is None or cached.get("status") != "ERROR":
        return None
    return str(cached["message"])
