"""Compatibility package for the SENTINEL source tree.

The project modules currently live at the repository root (`bot/`, `brain/`,
`state/`, etc.) while imports use the `sentinel.*` package name. Extending this
package path keeps those imports stable without a broad file move.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
__path__ = [str(_PROJECT_ROOT)]

