"""SunnyLipsync Maya 2027 Plugin.

Installation
------------
1. Copy ``SunnyLipsync.py`` into Maya's plug-ins directory.
2. Load it with Plug-in Manager, or run:
   ``import maya.cmds as cmds; cmds.loadPlugin('SunnyLipsync.py')``

Required Python packages (install into Maya Python)
----------------------------------------------------
``mayapy -m pip install openai-whisper pronouncing vosk``
If using Vosk fallback, download the latest small English model from the
Vosk model repository into ``~/.cache/vosk/`` (default lookup prefers
``vosk-model-small-en-us-0.15`` when present).

Usage examples
--------------
Python:
``cmds.sunnyLipsync(file='C:/audio/line.wav', namespace='Sunny', startFrame=101)``

MEL:
``sunnyLipsync -file "C:/audio/line.wav" -namespace "Sunny" -startFrame 101;``

Flag reference
--------------
-file/-f (string, required unless -clear)
-namespace/-ns (string, default "")
-startFrame/-sf (int, default 1)
-fps/-fps (float, default 24.0)
-smoothing/-sm (int, default 3)
-overshoot/-os (float, default 1.05)
-jawBias/-jb (float, default 1.0)
-exprInt/-ei (float, default 1.0)
-preview/-p (bool, default False)
-clear/-c (bool, default False)
"""

from __future__ import annotations

# This declaration tells Maya to use the OpenMaya 2.0 API when invoking
# initializePlugin / uninitializePlugin.  Without it Maya passes an OM1
# MObject which is incompatible with om.MFnPlugin and raises a TypeError.
maya_useNewAPI = True

from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import re
import threading
import traceback
import wave
from typing import Any, Iterable

try:
    import maya.api.OpenMaya as om
    import maya.OpenMayaUI as omui
    import maya.cmds as cmds
    import maya.mel as mel
    from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

    MAYA_AVAILABLE = True
except Exception:  # pragma: no cover - import guard for non-Maya environments
    om = None  # type: ignore[assignment]
    omui = None  # type: ignore[assignment]
    cmds = None  # type: ignore[assignment]
    mel = None  # type: ignore[assignment]

    class MayaQWidgetDockableMixin:  # type: ignore[no-redef]
        """Fallback dockable mixin for non-Maya runtime."""

    MAYA_AVAILABLE = False

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:  # pragma: no cover
    shiboken6 = None  # type: ignore[assignment]


class MayaPluginError(RuntimeError):
    """Raised for plugin runtime failures with actionable user-facing messages."""


# Preston Blair viseme library in Sunny rig controller space.
VISEME_POSES: dict[str, dict[str, dict[str, float]]] = {
    "REST": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": 0.0},
        "Up_Mouth_01_Ctrl": {"translateY": 0.0},
        "Low_Mouth_01_Ctrl": {"translateY": 0.0},
        "LF_Mouth_01_Ctrl": {"translateX": 0.0, "translateY": 0.0, "translateZ": 0.0},
        "RT_Mouth_01_Ctrl": {"translateX": 0.0, "translateY": 0.0, "translateZ": 0.0},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.0},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.0},
        "MD_Mouth_01_Master_Ctrl": {"translateY": 0.0},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 0.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 0.0},
    },
    "MBP": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": 0.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.15},
        "Low_Mouth_01_Ctrl": {"translateY": 0.15},
        "LF_Mouth_01_Ctrl": {"translateX": 0.0, "translateY": 0.0, "translateZ": -0.02},
        "RT_Mouth_01_Ctrl": {"translateX": 0.0, "translateY": 0.0, "translateZ": -0.02},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 1.0},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 1.0},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.03},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 0.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 0.0},
    },
    "FV": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -4.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.25},
        "Low_Mouth_01_Ctrl": {"translateY": 0.35},
        "LF_Mouth_01_Ctrl": {"translateX": 0.08, "translateY": -0.03, "translateZ": 0.06},
        "RT_Mouth_01_Ctrl": {"translateX": -0.08, "translateY": -0.03, "translateZ": 0.06},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.35},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.35},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.05},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 1.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 0.5},
    },
    "TH": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -6.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.1},
        "Low_Mouth_01_Ctrl": {"translateY": 0.45},
        "LF_Mouth_01_Ctrl": {"translateX": 0.12, "translateY": 0.02, "translateZ": 0.1},
        "RT_Mouth_01_Ctrl": {"translateX": -0.12, "translateY": 0.02, "translateZ": 0.1},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.2},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.2},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.06},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 10.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 16.0},
    },
    "DD": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -5.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.08},
        "Low_Mouth_01_Ctrl": {"translateY": 0.3},
        "LF_Mouth_01_Ctrl": {"translateX": 0.06, "translateY": 0.02, "translateZ": 0.03},
        "RT_Mouth_01_Ctrl": {"translateX": -0.06, "translateY": 0.02, "translateZ": 0.03},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.42},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.42},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.04},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 8.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 12.0},
    },
    "KG": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -7.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.02},
        "Low_Mouth_01_Ctrl": {"translateY": 0.4},
        "LF_Mouth_01_Ctrl": {"translateX": 0.03, "translateY": 0.0, "translateZ": 0.04},
        "RT_Mouth_01_Ctrl": {"translateX": -0.03, "translateY": 0.0, "translateZ": 0.04},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.3},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.3},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.05},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": -8.0, "rotateY": 4.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": -5.0},
    },
    "CH_SH_ZH": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -8.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.05},
        "Low_Mouth_01_Ctrl": {"translateY": 0.42},
        "LF_Mouth_01_Ctrl": {"translateX": -0.06, "translateY": 0.02, "translateZ": 0.2},
        "RT_Mouth_01_Ctrl": {"translateX": 0.06, "translateY": 0.02, "translateZ": 0.2},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.25},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.25},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.02},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 2.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 4.0},
    },
    "EE": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -2.5},
        "Up_Mouth_01_Ctrl": {"translateY": 0.12},
        "Low_Mouth_01_Ctrl": {"translateY": 0.08},
        "LF_Mouth_01_Ctrl": {"translateX": 0.35, "translateY": 0.08, "translateZ": -0.06},
        "RT_Mouth_01_Ctrl": {"translateX": -0.35, "translateY": 0.08, "translateZ": -0.06},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.3},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.3},
        "MD_Mouth_01_Master_Ctrl": {"translateY": 0.03},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 1.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 2.0},
    },
    "IH": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -3.5},
        "Up_Mouth_01_Ctrl": {"translateY": 0.06},
        "Low_Mouth_01_Ctrl": {"translateY": 0.16},
        "LF_Mouth_01_Ctrl": {"translateX": 0.2, "translateY": 0.04, "translateZ": -0.03},
        "RT_Mouth_01_Ctrl": {"translateX": -0.2, "translateY": 0.04, "translateZ": -0.03},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.28},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.28},
        "MD_Mouth_01_Master_Ctrl": {"translateY": 0.02},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 1.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 2.0},
    },
    "OOH_W": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -6.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.1},
        "Low_Mouth_01_Ctrl": {"translateY": 0.35},
        "LF_Mouth_01_Ctrl": {"translateX": -0.12, "translateY": -0.03, "translateZ": 0.3},
        "RT_Mouth_01_Ctrl": {"translateX": 0.12, "translateY": -0.03, "translateZ": 0.3},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.22},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.22},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.04},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": -2.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": -1.0},
    },
    "OH": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -14.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.2},
        "Low_Mouth_01_Ctrl": {"translateY": 0.65},
        "LF_Mouth_01_Ctrl": {"translateX": -0.07, "translateY": -0.02, "translateZ": 0.24},
        "RT_Mouth_01_Ctrl": {"translateX": 0.07, "translateY": -0.02, "translateZ": 0.24},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.16},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.16},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.1},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": -1.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 0.0},
    },
    "AH": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -18.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.18},
        "Low_Mouth_01_Ctrl": {"translateY": 0.82},
        "LF_Mouth_01_Ctrl": {"translateX": 0.03, "translateY": -0.05, "translateZ": 0.1},
        "RT_Mouth_01_Ctrl": {"translateX": -0.03, "translateY": -0.05, "translateZ": 0.1},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.08},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.08},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.14},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": -4.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": -2.0},
    },
    "AA": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -20.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.22},
        "Low_Mouth_01_Ctrl": {"translateY": 0.95},
        "LF_Mouth_01_Ctrl": {"translateX": 0.08, "translateY": -0.05, "translateZ": 0.05},
        "RT_Mouth_01_Ctrl": {"translateX": -0.08, "translateY": -0.05, "translateZ": 0.05},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.05},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.05},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.16},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": -6.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": -4.0},
    },
    "L": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -7.0},
        "Up_Mouth_01_Ctrl": {"translateY": -0.04},
        "Low_Mouth_01_Ctrl": {"translateY": 0.36},
        "LF_Mouth_01_Ctrl": {"translateX": 0.07, "translateY": 0.01, "translateZ": 0.08},
        "RT_Mouth_01_Ctrl": {"translateX": -0.07, "translateY": 0.01, "translateZ": 0.08},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.25},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.25},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.03},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 12.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 20.0},
    },
    "NN": {
        "MD_Mouth_01_Jaw_Ctrl": {"rotateX": -2.0},
        "Up_Mouth_01_Ctrl": {"translateY": 0.0},
        "Low_Mouth_01_Ctrl": {"translateY": 0.12},
        "LF_Mouth_01_Ctrl": {"translateX": 0.03, "translateY": 0.02, "translateZ": -0.01},
        "RT_Mouth_01_Ctrl": {"translateX": -0.03, "translateY": 0.02, "translateZ": -0.01},
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.6},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.6},
        "MD_Mouth_01_Master_Ctrl": {"translateY": -0.01},
        "MD_Tongue_01_01_FK_Ctrl": {"rotateX": 10.0, "rotateY": 0.0},
        "MD_Tongue_01_05_FK_Ctrl": {"rotateX": 14.0},
    },
}

ARPABET_TO_VISEME: dict[str, str] = {
    "P": "MBP",
    "B": "MBP",
    "M": "MBP",
    "F": "FV",
    "V": "FV",
    "TH": "TH",
    "DH": "TH",
    "T": "DD",
    "D": "DD",
    "K": "KG",
    "G": "KG",
    "CH": "CH_SH_ZH",
    "SH": "CH_SH_ZH",
    "ZH": "CH_SH_ZH",
    "JH": "CH_SH_ZH",
    "IY": "EE",
    "IH": "IH",
    "W": "OOH_W",
    "UW": "OOH_W",
    "UH": "OOH_W",
    "OW": "OH",
    "AH": "AH",
    "AX": "AH",
    "AE": "AA",
    "EH": "AA",
    "L": "L",
    "N": "NN",
    "NG": "NN",
}

MIN_PHONEME_DURATION = 1e-3
# One-frame look-behind for anticipatory mouth motion at segment boundaries.
ANTICIPATION_FRAME_OFFSET = 1
# One-frame insertion for explicit REST transition when phonemes are non-adjacent.
REST_INSERT_FRAME_OFFSET = 1
# Release blend toward REST to soften exits (60% target, 40% rest).
RELEASE_TARGET_WEIGHT = 0.6
RELEASE_REST_WEIGHT = 0.4
DEFAULT_VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
UI_START_FRAME_MIN = -100000
UI_START_FRAME_MAX = 100000
ICON_BORDER_COLOR = "#10243a"
ICON_FILL_COLOR = "#2aa4ff"

# Name of the pose library JSON file written next to the plugin.
_POSE_LIBRARY_FILENAME = "SunnyLipsync_poses.json"


def _resolve_pose_library_path() -> Path:
    """Return the default path for SunnyLipsync_poses.json.

    When running inside Maya the plugin's registered file path is retrieved
    via ``om.MFnPlugin`` so the JSON lands next to the .py file regardless of
    the current working directory.  ``__file__`` is intentionally avoided
    because Maya's plugin loader does not set it, which causes a
    ``NameError`` at import time.

    Outside Maya (unit tests, standalone scripts) the file is placed next to
    this module in sys.modules, or in the current working directory as a
    last resort.
    """
    # --- Maya path (preferred) -------------------------------------------
    if MAYA_AVAILABLE:
        try:
            # MFnPlugin.findPlugin returns the MObject for the named plugin.
            # pluginPath() then gives the absolute path to the .py file.
            plugin_obj = om.MFnPlugin.findPlugin("SunnyLipsync")
            if not plugin_obj.isNull():
                plugin_path = Path(om.MFnPlugin(plugin_obj).pluginPath())
                return plugin_path.parent / _POSE_LIBRARY_FILENAME
        except Exception:
            pass  # Fall through to non-Maya resolution below.

    # --- Non-Maya / test path --------------------------------------------
    # inspect.getfile() works when the module is properly imported.
    try:
        import inspect
        return Path(inspect.getfile(_resolve_pose_library_path)).parent / _POSE_LIBRARY_FILENAME
    except (TypeError, OSError):
        pass

    # Absolute last resort: current working directory.
    return Path.cwd() / _POSE_LIBRARY_FILENAME


# ---------------------------------------------------------------------------
# Pose library — persists user-defined viseme poses to/from disk
# ---------------------------------------------------------------------------

class VisemePoseLibrary:
    """Manages a mutable, user-editable copy of the viseme pose table.

    On first use it is seeded with the built-in ``VISEME_POSES`` defaults.
    Artists can then capture their own poses from the rig and save them to a
    JSON file on disk.  The library is loaded automatically when the plugin
    starts, and re-saved every time a pose is captured or reset.

    The file format is identical to ``VISEME_POSES``:
        { "REST": { "MD_Mouth_01_Jaw_Ctrl": { "rotateX": 0.0 }, ... }, ... }

    Usage
    -----
    Call ``pose_library.get_poses()`` wherever ``VISEME_POSES`` was used
    before.  The writer and UI both go through this object so that any
    captured poses are reflected immediately in the next generate run.
    """

    def __init__(self, path: Path | None = None) -> None:
        # Resolve the path lazily here rather than at the default-argument
        # level.  Default argument expressions are evaluated at import time,
        # so any path that calls __file__ or Maya APIs would crash before
        # initializePlugin() has even been called.
        self._path: Path = path if path is not None else _resolve_pose_library_path()
        self._poses: dict[str, dict[str, dict[str, float]]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_poses(self) -> dict[str, dict[str, dict[str, float]]]:
        """Return the current pose table (live reference, not a copy)."""
        return self._poses

    def get_pose(self, viseme: str) -> dict[str, dict[str, float]]:
        """Return a single viseme pose, falling back to REST if unknown."""
        return self._poses.get(viseme, self._poses.get("REST", {}))

    def set_pose(
        self,
        viseme: str,
        pose: dict[str, dict[str, float]],
        save: bool = True,
    ) -> None:
        """Store *pose* for *viseme* and optionally persist to disk."""
        if viseme not in VISEME_POSES:
            raise MayaPluginError(
                f"Unknown viseme '{viseme}'. "
                f"Valid names: {', '.join(sorted(VISEME_POSES))}"
            )
        self._poses[viseme] = pose
        if save:
            self._save()

    def reset_pose(self, viseme: str, save: bool = True) -> None:
        """Restore a single viseme to the built-in default."""
        if viseme not in VISEME_POSES:
            raise MayaPluginError(f"Unknown viseme '{viseme}'.")
        self._poses[viseme] = {
            ctrl: dict(attrs)
            for ctrl, attrs in VISEME_POSES[viseme].items()
        }
        if save:
            self._save()

    def reset_all(self, save: bool = True) -> None:
        """Restore every viseme to the built-in defaults."""
        self._poses = {
            viseme: {ctrl: dict(attrs) for ctrl, attrs in pose.items()}
            for viseme, pose in VISEME_POSES.items()
        }
        if save:
            self._save()

    def is_customised(self, viseme: str) -> bool:
        """Return True if *viseme* differs from the built-in default."""
        default = VISEME_POSES.get(viseme, {})
        current = self._poses.get(viseme, {})
        return current != default

    @property
    def save_path(self) -> Path:
        return self._path

    @save_path.setter
    def save_path(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load from disk if the file exists, otherwise seed from defaults."""
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Merge: keep any visemes from defaults that are missing in
                # the saved file (e.g. after a plugin update adds new visemes).
                merged: dict[str, dict[str, dict[str, float]]] = {
                    viseme: {ctrl: dict(attrs) for ctrl, attrs in pose.items()}
                    for viseme, pose in VISEME_POSES.items()
                }
                for viseme, pose in data.items():
                    if viseme in merged:
                        merged[viseme] = pose
                self._poses = merged
                return
            except Exception:
                # Corrupted file — fall back to defaults silently.
                pass
        # No file yet: seed from built-in defaults (do not write yet so that
        # the file is only created when the user deliberately saves a pose).
        self._poses = {
            viseme: {ctrl: dict(attrs) for ctrl, attrs in pose.items()}
            for viseme, pose in VISEME_POSES.items()
        }

    def _save(self) -> None:
        """Write the current pose table to disk as JSON."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                json.dump(self._poses, fh, indent=2)
        except Exception as exc:
            raise MayaPluginError(
                f"Could not save pose library to '{self._path}': {exc}"
            ) from exc


# Module-level singleton — shared by the writer and the UI.
pose_library = VisemePoseLibrary()


# ---------------------------------------------------------------------------
# Pose capture helper
# ---------------------------------------------------------------------------

# Ordered list of every controller + attribute the plugin tracks.
# This is derived from VISEME_POSES["REST"] so it always stays in sync.
_TRACKED_PLUGS: list[tuple[str, str]] = [
    (ctrl, attr)
    for ctrl, attrs in VISEME_POSES["REST"].items()
    for attr in attrs
]


def capture_current_pose(namespace: str = "") -> dict[str, dict[str, float]]:
    """Read the current values of all tracked rig controllers from Maya.

    Parameters
    ----------
    namespace:
        Rig namespace prefix (e.g. ``"Sunny"``).  Pass an empty string if
        the rig is not referenced under a namespace.

    Returns
    -------
    A pose dict in the same format as a single entry in ``VISEME_POSES``:
    ``{ "MD_Mouth_01_Jaw_Ctrl": { "rotateX": -18.0 }, ... }``

    Raises
    ------
    MayaPluginError
        If Maya is not available or none of the tracked controllers exist.
    """
    if not MAYA_AVAILABLE:
        raise MayaPluginError(
            "capture_current_pose() must be called inside Maya."
        )

    ns_prefix = f"{namespace.strip(':')}:" if namespace.strip(":") else ""
    pose: dict[str, dict[str, float]] = {}
    missing: list[str] = []

    for ctrl, attr in _TRACKED_PLUGS:
        node = f"{ns_prefix}{ctrl}"
        plug = f"{node}.{attr}"
        if not cmds.objExists(plug):
            missing.append(plug)
            continue
        value = cmds.getAttr(plug)
        pose.setdefault(ctrl, {})[attr] = float(value)

    if not pose:
        raise MayaPluginError(
            "No tracked controllers found in the scene. "
            "Make sure the Sunny rig is loaded and the namespace is correct.\n"
            f"Expected controllers like: {ns_prefix}MD_Mouth_01_Jaw_Ctrl"
        )
    if missing:
        # Partial capture is still useful — warn but do not raise.
        if MAYA_AVAILABLE:
            cmds.warning(
                f"SunnyLipsync capture: {len(missing)} plug(s) not found and "
                f"skipped: {', '.join(missing[:5])}"
                + (" …" if len(missing) > 5 else "")
            )

    return pose


@dataclass(frozen=True)
class PhonemeSegment:
    """Time span and target viseme."""

    start: float
    end: float
    viseme: str


class PhonemeDetector:
    """Phoneme detector using Whisper+CMU with Vosk fallback.

    When *script_text* is supplied the detector operates in **guided mode**:
    the user's typed text is used as the word list and Whisper is asked to
    perform forced alignment — matching the known words to the audio rather
    than guessing what was said.  This gives more accurate per-word timings,
    especially for proper nouns, accents, and fast speech that Whisper would
    otherwise mis-transcribe.

    Without *script_text* the detector operates in **audio-only mode**,
    transcribing freely and deriving words from whatever Whisper/Vosk detects.
    """

    #: Valid Whisper model sizes in ascending speed/accuracy order.
    WHISPER_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium")

    def __init__(
        self,
        audio_path: str,
        fps: float,
        ffmpeg_path: str = "",
        script_text: str = "",
        whisper_model: str = "base",
        min_confidence: float = 0.0,
    ) -> None:
        self.audio_path  = audio_path
        self.fps         = fps
        self.ffmpeg_path = ffmpeg_path.strip('"').strip()
        # Normalise script text: collapse whitespace, strip punctuation that
        # would confuse the CMU dictionary lookup.
        self.script_text = " ".join(script_text.split()) if script_text.strip() else ""
        # Whisper model size — larger models are slower but more accurate.
        self.whisper_model = (
            whisper_model if whisper_model in self.WHISPER_MODELS else "base"
        )
        # Segments whose Whisper no_speech_prob exceeds (1 - min_confidence)
        # are replaced with REST instead of being passed to the phoneme mapper.
        self.min_confidence: float = max(0.0, min(1.0, min_confidence))

    def detect(self) -> list[tuple[float, float, str]]:
        """Return a timeline of (start_time_sec, end_time_sec, viseme_label).

        If script_text was provided, guided forced-alignment is attempted
        first.  If it fails or is not available, falls back transparently to
        audio-only detection so generation always completes.

        Whisper segments flagged as low-confidence (no_speech_prob > 1 -
        min_confidence) are replaced with REST instead of being mapped to
        phonemes, preventing garbled visemes on low-quality audio.
        """
        if self.script_text:
            words = self._detect_words_guided()
            if words is not None:
                timeline: list[PhonemeSegment] = []
                for entry in words:
                    start, end, word = entry[0], entry[1], entry[2]
                    low_conf = entry[3] if len(entry) > 3 else False
                    if low_conf:
                        timeline.append(PhonemeSegment(start, end, "REST"))
                    else:
                        timeline.extend(self._word_to_visemes(start, end, word))
                if timeline:
                    return [(seg.start, seg.end, seg.viseme) for seg in timeline]
                # Guided produced zero segments — fall through to audio-only
                cmds.warning(
                    "SunnyLipsync: guided alignment produced no segments; "
                    "falling back to audio-only detection."
                ) if MAYA_AVAILABLE else None

        # Audio-only path (original behaviour)
        words = self._detect_words_whisper()
        if words is None:
            words = self._detect_words_vosk()
        if words is None:
            raise MayaPluginError(
                "No speech backend available. Install with:\n"
                "  mayapy -m pip install openai-whisper pronouncing vosk"
            )

        timeline = []
        for entry in words:
            start, end, word = entry[0], entry[1], entry[2]
            low_conf = entry[3] if len(entry) > 3 else False
            if low_conf:
                timeline.append(PhonemeSegment(start, end, "REST"))
            else:
                timeline.extend(self._word_to_visemes(start, end, word))
        if not timeline:
            timeline.append(PhonemeSegment(0.0, 0.1, "REST"))
        return [(seg.start, seg.end, seg.viseme) for seg in timeline]

    # ------------------------------------------------------------------
    # Guided detection (audio + script)
    # ------------------------------------------------------------------

    def _detect_words_guided(self) -> list[tuple[float, float, str]] | None:
        """Align the script words to the audio using Whisper forced alignment.

        Strategy
        --------
        Whisper is instructed to transcribe with ``initial_prompt`` set to
        the user's script.  This strongly biases the model toward the known
        words and gives more accurate word-level timestamps than free
        transcription, particularly for names, accents, and fast speech.

        After Whisper returns word timestamps, its recognised words are
        replaced one-for-one with the user's script words (in order), keeping
        Whisper's timings but using the correct spellings.  Any extra Whisper
        words are dropped; any extra script words are distributed evenly into
        the remaining duration.

        This runs in the same mayapy subprocess as audio-only Whisper to
        avoid the PyTorch/Maya DLL conflict.

        Returns None if Whisper is not installed, so the caller can fall back.
        """
        import subprocess
        import sys

        mayapy = Path(sys.executable).with_name("mayapy.exe")
        if not mayapy.exists():
            mayapy = Path(sys.executable).with_name("mayapy")
        if not mayapy.exists():
            return None

        audio_json  = json.dumps(self.audio_path)
        ffmpeg_json = json.dumps(self.ffmpeg_path) if self.ffmpeg_path else '""'
        script_json = json.dumps(self.script_text)
        model_name  = self.whisper_model
        min_conf    = self.min_confidence

        script = (
            "import sys, json, os, re\n"
            "try:\n"
            "    import whisper\n"
            "except ImportError:\n"
            "    print(json.dumps({'error': 'no_whisper'}))\n"
            "    sys.exit(0)\n"
            f"audio   = json.loads({repr(audio_json)})\n"
            f"ffmpeg  = json.loads({repr(ffmpeg_json)})\n"
            f"script  = json.loads({repr(script_json)})\n"
            f"model_name   = {repr(model_name)}\n"
            f"min_conf     = {min_conf!r}\n"
            # Add ffmpeg directory to PATH if provided
            "if ffmpeg:\n"
            "    os.environ['PATH'] = os.path.dirname(ffmpeg) + os.pathsep + os.environ.get('PATH', '')\n"
            # Clean script into a word list
            "script_words = re.sub(r\"[^A-Za-z'\\s]\", '', script).split()\n"
            "try:\n"
            "    model  = whisper.load_model(model_name)\n"
            # Pass script as initial_prompt to bias Whisper toward the known words
            "    result = model.transcribe(\n"
            "        audio,\n"
            "        word_timestamps=True,\n"
            "        verbose=False,\n"
            "        initial_prompt=script,\n"
            "    )\n"
            # Collect Whisper word entries with timings, respecting confidence filter.
            # Whisper returns no_speech_prob per segment; words in a low-confidence
            # segment are flagged so the caller can replace them with REST.
            "    whisper_words = []\n"
            "    for seg in result.get('segments', []):\n"
            "        no_speech = float(seg.get('no_speech_prob', 0.0))\n"
            "        seg_conf  = 1.0 - no_speech\n"
            "        low_conf  = seg_conf < min_conf\n"
            "        for w in seg.get('words', []):\n"
            "            tok = str(w.get('word', '')).strip()\n"
            "            if tok:\n"
            "                whisper_words.append([float(w['start']), float(w['end']), tok, low_conf])\n"
            # If no word timestamps available (dtw not installed), fall back to
            # segment-level timing distributed across script words.
            "    if not whisper_words:\n"
            "        segs = result.get('segments', [])\n"
            "        if segs and script_words:\n"
            "            total_start = float(segs[0]['start'])\n"
            "            total_end   = float(segs[-1]['end'])\n"
            "            step = (total_end - total_start) / len(script_words)\n"
            "            whisper_words = [\n"
            "                [total_start + i*step, total_start + (i+1)*step, w, False]\n"
            "                for i, w in enumerate(script_words)\n"
            "            ]\n"
            # Replace Whisper words with script words, keeping Whisper timings.
            # If script has more words than Whisper detected, distribute the
            # extras evenly into the tail of the audio.
            "    aligned = []\n"
            "    n_whisper = len(whisper_words)\n"
            "    n_script  = len(script_words)\n"
            "    for i, sw in enumerate(script_words):\n"
            "        if i < n_whisper:\n"
            "            aligned.append([whisper_words[i][0], whisper_words[i][1], sw, whisper_words[i][3]])\n"
            "        else:\n"
            # Extra script words: extend from end of last Whisper word
            "            prev_end   = aligned[-1][1] if aligned else 0.0\n"
            "            extra_dur  = 0.25  # estimate 250 ms per unmatched word\n"
            "            aligned.append([prev_end, prev_end + extra_dur, sw, False])\n"
            "    print(json.dumps({'words': aligned, 'mode': 'guided'}))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'error': str(e)}))\n"
        )

        try:
            proc = subprocess.run(
                [str(mayapy), "-c", script],
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            raise MayaPluginError("Whisper guided alignment timed out (> 1 hour).")
        except Exception as exc:
            raise MayaPluginError(f"Failed to launch Whisper subprocess: {exc}") from exc

        json_line = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                json_line = line

        if json_line is None:
            stderr_snippet = proc.stderr[-500:] if proc.stderr else ""
            if stderr_snippet:
                raise MayaPluginError(f"Whisper subprocess failed:\n{stderr_snippet}")
            return None

        try:
            payload = json.loads(json_line)
        except json.JSONDecodeError as exc:
            raise MayaPluginError(f"Whisper subprocess returned invalid JSON: {exc}") from exc

        if "error" in payload:
            err = payload["error"]
            if err == "no_whisper":
                return None
            raise MayaPluginError(f"Whisper guided alignment error: {err}")

        return [
            (float(s), float(e), str(w), bool(low) if len(entry) > 3 else False)
            for entry in payload.get("words", [])
            for s, e, w, *rest in [entry]
            for low in [rest[0] if rest else False]
        ]

    def _detect_words_whisper(self) -> list[tuple[float, float, str]] | None:
        """Run Whisper in a subprocess to avoid PyTorch/Maya DLL conflicts.

        PyTorch's shm.dll clashes with Maya's bundled runtime DLLs when loaded
        inside Maya's process (WinError 127).  Spawning a fresh mayapy process
        sidesteps the conflict entirely — the subprocess has a clean DLL
        environment and writes JSON results to stdout for us to parse.
        """
        import subprocess
        import sys

        # Find mayapy next to the running Python executable.
        mayapy = Path(sys.executable).with_name("mayapy.exe")
        if not mayapy.exists():
            # Fallback: same directory without .exe (Linux/macOS)
            mayapy = Path(sys.executable).with_name("mayapy")
        if not mayapy.exists():
            return None

        # Embed paths as JSON strings — safe quoting for spaces/backslashes.
        audio_json = json.dumps(self.audio_path)
        ffmpeg_json = json.dumps(self.ffmpeg_path) if self.ffmpeg_path else '""'
        model_name  = self.whisper_model
        min_conf    = self.min_confidence
        script = (
            "import sys, json, os\n"
            "try:\n"
            "    import whisper\n"
            "except ImportError:\n"
            "    print(json.dumps({'error': 'no_whisper'}))\n"
            "    sys.exit(0)\n"
            f"audio = json.loads({repr(audio_json)})\n"
            f"ffmpeg = json.loads({repr(ffmpeg_json)})\n"
            f"model_name = {repr(model_name)}\n"
            f"min_conf   = {min_conf!r}\n"
            # If an explicit ffmpeg path was provided, add its directory to PATH
            # so Whisper's subprocess can find it without a system-level PATH entry.
            "if ffmpeg:\n"
            "    ffmpeg_dir = os.path.dirname(ffmpeg)\n"
            "    os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')\n"
            "try:\n"
            "    model = whisper.load_model(model_name)\n"
            "    result = model.transcribe(audio, word_timestamps=True, verbose=False)\n"
            "    words = []\n"
            "    for seg in result.get('segments', []):\n"
            "        no_speech = float(seg.get('no_speech_prob', 0.0))\n"
            "        seg_conf  = 1.0 - no_speech\n"
            "        low_conf  = seg_conf < min_conf\n"
            "        entries = seg.get('words', [])\n"
            "        if entries:\n"
            "            for w in entries:\n"
            "                tok = str(w.get('word', '')).strip()\n"
            "                if tok:\n"
            "                    words.append([float(w['start']), float(w['end']), tok, low_conf])\n"
            "        else:\n"
            "            tok = str(seg.get('text', '')).strip()\n"
            "            if tok:\n"
            "                words.append([float(seg['start']), float(seg['end']), tok, low_conf])\n"
            "    print(json.dumps({'words': words}))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'error': str(e)}))\n"
        )

        try:
            proc = subprocess.run(
                [str(mayapy), "-c", script],
                capture_output=True,
                text=True,
                timeout=3600,  # 1-hour timeout for long audio files
            )
        except subprocess.TimeoutExpired:
            raise MayaPluginError("Whisper transcription timed out (> 1 hour).")
        except Exception as exc:
            raise MayaPluginError(f"Failed to launch Whisper subprocess: {exc}") from exc

        # The subprocess may print warnings/progress before our JSON line.
        # Find the last line that looks like JSON.
        json_line = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                json_line = line

        if json_line is None:
            # No JSON output at all — Whisper probably not installed or crashed.
            stderr_snippet = proc.stderr[-500:] if proc.stderr else ""
            if stderr_snippet:
                raise MayaPluginError(f"Whisper subprocess failed:\n{stderr_snippet}")
            return None

        try:
            payload = json.loads(json_line)
        except json.JSONDecodeError as exc:
            raise MayaPluginError(f"Whisper subprocess returned invalid JSON: {exc}") from exc

        if "error" in payload:
            err = payload["error"]
            if err == "no_whisper":
                return None  # Not installed — fall through to Vosk
            raise MayaPluginError(f"Whisper transcription error: {err}")

        return [
            (float(s), float(e), str(w), bool(lc) if len(entry) > 3 else False)
            for entry in payload.get("words", [])
            for s, e, w, *rest in [entry]
            for lc in [rest[0] if rest else False]
        ]

    def _detect_words_vosk(self) -> list[tuple[float, float, str]] | None:
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore[import-not-found]
        except Exception:
            return None

        model_path = self._resolve_vosk_model_path()
        if model_path is None:
            raise MayaPluginError(
                "Vosk is installed but no model was found. Set SUNNY_LIPSYNC_VOSK_MODEL "
                "to a model folder, or place a small English model in ~/.cache/vosk/."
            )

        audio_file = Path(self.audio_path)
        if audio_file.suffix.lower() != ".wav":
            raise MayaPluginError("Vosk fallback currently expects a WAV file.")

        try:
            model = Model(str(model_path))
            words: list[tuple[float, float, str]] = []
            with wave.open(self.audio_path, "rb") as wav:
                recognizer = KaldiRecognizer(model, wav.getframerate())
                recognizer.SetWords(True)
                while True:
                    data = wav.readframes(4000)
                    if not data:
                        break
                    if recognizer.AcceptWaveform(data):
                        payload = json.loads(recognizer.Result())
                        for entry in payload.get("result", []):
                            words.append((float(entry["start"]), float(entry["end"]), str(entry["word"])))
                payload = json.loads(recognizer.FinalResult())
                for entry in payload.get("result", []):
                    words.append((float(entry["start"]), float(entry["end"]), str(entry["word"])))
            return words
        except Exception as exc:
            raise MayaPluginError(f"Vosk failed: {exc}") from exc

    def _resolve_vosk_model_path(self) -> Path | None:
        """Resolve Vosk model path from env var, default folder, or any cached model."""
        env_model = os.environ.get("SUNNY_LIPSYNC_VOSK_MODEL", "").strip()
        if env_model:
            candidate = Path(env_model).expanduser()
            if candidate.exists():
                return candidate

        cache_root = Path.home() / ".cache" / "vosk"
        preferred = cache_root / DEFAULT_VOSK_MODEL_NAME
        if preferred.exists():
            return preferred

        if cache_root.exists():
            for folder in sorted(cache_root.iterdir()):
                if folder.is_dir() and folder.name.startswith("vosk-model"):
                    return folder
        return None

    def _word_to_visemes(self, start: float, end: float, word: str) -> list[PhonemeSegment]:
        try:
            import pronouncing  # type: ignore[import-not-found]
        except Exception as exc:
            raise MayaPluginError("pronouncing package is required for ARPABET mapping.") from exc

        cleaned = re.sub(r"[^A-Za-z']", "", word).lower()
        duration = max(end - start, MIN_PHONEME_DURATION)
        if not cleaned:
            return [PhonemeSegment(start, end, "REST")]

        phones_list = pronouncing.phones_for_word(cleaned)
        if not phones_list:
            return [PhonemeSegment(start, end, "REST")]

        arpabet = [re.sub(r"\d", "", token) for token in phones_list[0].split()]
        step = duration / max(len(arpabet), 1)
        segments: list[PhonemeSegment] = []
        for index, token in enumerate(arpabet):
            seg_start = start + (index * step)
            seg_end = min(end, seg_start + step)
            viseme = ARPABET_TO_VISEME.get(token, "REST")
            segments.append(PhonemeSegment(seg_start, seg_end, viseme))
        return segments


class LipsyncAnimWriter:
    """Writes keyed lipsync animation directly on Sunny rig controllers."""

    def __init__(
        self,
        char_namespace: str = "",
        fps: float = 24.0,
        start_frame: int = 1,
        smoothing: int = 3,
        overshoot: float = 1.05,
        jaw_bias: float = 1.0,
        expr_intensity: float = 1.0,
        jaw_scale: float = 1.0,
        upper_lip_scale: float = 1.0,
        lower_lip_scale: float = 1.0,
        corner_scale: float = 1.0,
    ) -> None:
        self.char_namespace = char_namespace.strip(":")
        self.fps = fps
        self.start_frame = start_frame
        self.smoothing = max(1, int(smoothing))
        self.overshoot = overshoot
        self.jaw_bias = jaw_bias
        self.expr_intensity = expr_intensity
        # Per-controller independent scale multipliers.
        # jaw_scale   → MD_Mouth_01_Jaw_Ctrl
        # upper_lip_scale → Up_Mouth_01_Ctrl
        # lower_lip_scale → Low_Mouth_01_Ctrl
        # corner_scale    → LF/RT_Mouth_01_Ctrl
        self.jaw_scale        = jaw_scale
        self.upper_lip_scale  = upper_lip_scale
        self.lower_lip_scale  = lower_lip_scale
        self.corner_scale     = corner_scale
        self._keyed_attrs: set[str] = set()

    @property
    def all_controls(self) -> list[str]:
        """Return all controls referenced in viseme poses."""
        controls = {ctrl for pose in VISEME_POSES.values() for ctrl in pose.keys()}
        return sorted(controls)

    def write(self, phoneme_timeline: list[tuple[float, float, str]]) -> None:
        """Convert phoneme timeline to Maya keyframes on Sunny controls.

        Key reduction strategy
        ----------------------
        Raw phoneme timelines from Whisper/Vosk contain many very short
        segments.  Naively keying anticipation + peak + release for every one
        produces hundreds of keys packed 1-2 frames apart, which reads as
        jitter even after smoothing.  This method reduces keys to the minimum
        needed to express the performance:

        1. Consecutive identical visemes are merged into one longer segment.
        2. Very short segments sandwiched between two identical visemes are
           absorbed into the surrounding viseme.
        3. The anticipation key is only written when there is room before the
           peak (MIN_KEY_SPACING frames of separation).
        4. The release key is only written when peak and end are distinct.
        5. REST gap keys are only inserted when silence is long enough to
           matter visually (REST_GAP_MIN_FRAMES).
        6. When two segments map to the same frame, the first wins.
        7. All keys are stamped flat after smoothing to eliminate S-curve
           jitter from Maya's auto-tangent recalculation.
        """
        if not MAYA_AVAILABLE:
            raise MayaPluginError("Maya APIs unavailable: write() must run in Maya.")
        if not phoneme_timeline:
            cmds.warning("No phonemes detected; nothing to key.")
            return

        self._keyed_attrs.clear()

        sorted_timeline = sorted(phoneme_timeline, key=lambda item: item[0])

        # Step 1: merge consecutive identical visemes
        merged: list[tuple[float, float, str]] = []
        for seg_start, seg_end, viseme in sorted_timeline:
            if merged and merged[-1][2] == viseme:
                merged[-1] = (merged[-1][0], seg_end, viseme)
            else:
                merged.append((seg_start, seg_end, viseme))

        # Step 2: absorb very short sandwiched segments
        MIN_SEGMENT_FRAMES = 3
        absorbing = True
        while absorbing and len(merged) > 2:
            absorbing = False
            result: list[tuple[float, float, str]] = [merged[0]]
            i = 1
            while i < len(merged) - 1:
                prev_viseme = result[-1][2]
                seg_start, seg_end, viseme = merged[i]
                next_viseme = merged[i + 1][2]
                seg_frames = self.to_frame(seg_end) - self.to_frame(seg_start)
                if seg_frames < MIN_SEGMENT_FRAMES and prev_viseme == next_viseme:
                    result[-1] = (result[-1][0], seg_end, prev_viseme)
                    absorbing = True
                else:
                    result.append(merged[i])
                i += 1
            result.append(merged[-1])
            merged = result

        # Step 3: write keys
        start_frame_range = self.to_frame(merged[0][0])
        end_frame_range   = self.to_frame(merged[-1][1])

        MIN_KEY_SPACING    = 2
        REST_GAP_MIN_FRAMES = 4
        keyed_frames: set[int] = set()

        cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncWrite")
        try:
            self.clear_keys(start_frame_range, end_frame_range)

            for index, (seg_start, seg_end, viseme) in enumerate(merged):
                f_start = self.to_frame(seg_start)
                f_end   = max(f_start, self.to_frame(seg_end))
                f_peak  = (f_start + f_end) // 2

                f_anticipate = max(self.start_frame, f_start - ANTICIPATION_FRAME_OFFSET)
                if (f_peak - f_anticipate >= MIN_KEY_SPACING
                        and f_anticipate not in keyed_frames):
                    self._key_pose(viseme, f_anticipate, self.overshoot, "flat")
                    keyed_frames.add(f_anticipate)

                if f_peak not in keyed_frames:
                    self._key_pose(viseme, f_peak, 1.0, "flat")
                    keyed_frames.add(f_peak)

                if (f_end - f_peak >= MIN_KEY_SPACING
                        and f_end not in keyed_frames):
                    self._key_release(viseme, f_end, "flat")
                    keyed_frames.add(f_end)

                if index + 1 < len(merged):
                    next_f_start = self.to_frame(merged[index + 1][0])
                    gap = next_f_start - f_end
                    if gap >= REST_GAP_MIN_FRAMES:
                        rest_frame = f_end + REST_INSERT_FRAME_OFFSET
                        if rest_frame not in keyed_frames:
                            self._key_pose("REST", rest_frame, 1.0, "flat")
                            keyed_frames.add(rest_frame)

            self._smooth_keys(start_frame_range, end_frame_range)
            self._flatten_tangents(start_frame_range, end_frame_range)
        except Exception as exc:
            raise MayaPluginError(f"Failed writing keyframes: {exc}") from exc
        finally:
            cmds.undoInfo(closeChunk=True)

    def clear_keys(self, frame_start: int, frame_end: int) -> None:
        """Delete keys for all supported controls in a frame range."""
        if not MAYA_AVAILABLE:
            return
        for control in self.all_controls:
            node = self._node_name(control)
            if not cmds.objExists(node):
                continue
            attrs = VISEME_POSES["REST"].get(control, {})
            for attr in attrs:
                target = f"{node}.{attr}"
                if cmds.objExists(target):
                    # cutKey expects the node as first arg and attr via -attribute.
                    # Passing a full "node.attr" plug path can silently no-op on
                    # some Maya versions.
                    cmds.cutKey(node, attribute=attr, time=(frame_start, frame_end), clear=True)

    def clear_all_keys(self) -> None:
        """Delete all keys on supported controls across the timeline."""
        if not MAYA_AVAILABLE:
            return
        min_time = int(cmds.playbackOptions(q=True, minTime=True))
        max_time = int(cmds.playbackOptions(q=True, maxTime=True))
        self.clear_keys(min_time, max_time)

    def to_frame(self, time_seconds: float) -> int:
        """Convert seconds on the audio timeline to scene frame number."""
        return int(round(self.start_frame + (time_seconds * self.fps)))

    def _node_name(self, control: str) -> str:
        return f"{self.char_namespace}:{control}" if self.char_namespace else control

    def _scaled_value(self, control: str, attr: str, value: float, blend: float) -> float:
        scaled = value * self.expr_intensity * blend
        if control == "MD_Mouth_01_Jaw_Ctrl" and attr == "rotateX":
            scaled *= self.jaw_bias
        # Per-controller independent scale multipliers (applied after jaw_bias so
        # jaw_scale lets artists squash the jaw without re-tuning jaw_bias).
        if control == "MD_Mouth_01_Jaw_Ctrl":
            scaled *= self.jaw_scale
        elif control == "Up_Mouth_01_Ctrl":
            scaled *= self.upper_lip_scale
        elif control == "Low_Mouth_01_Ctrl":
            scaled *= self.lower_lip_scale
        elif control in ("LF_Mouth_01_Ctrl", "RT_Mouth_01_Ctrl"):
            scaled *= self.corner_scale
        return scaled

    def _iter_pose(self, viseme: str, blend: float) -> Iterable[tuple[str, str, float]]:
        pose = pose_library.get_pose(viseme)
        for control, attrs in pose.items():
            for attr, value in attrs.items():
                yield control, attr, self._scaled_value(control, attr, value, blend)

    def _key_pose(self, viseme: str, frame: int, blend: float, tangent: str) -> None:
        for control, attr, value in self._iter_pose(viseme, blend):
            node = self._node_name(control)
            if not cmds.objExists(node):
                cmds.warning(f"SunnyLipsync: missing controller '{node}', skipping.")
                continue
            plug = f"{node}.{attr}"
            if not cmds.objExists(plug):
                cmds.warning(f"SunnyLipsync: missing attribute '{plug}', skipping.")
                continue
            # Pass tangent type directly into setKeyframe so the key is created
            # with the correct tangent from the start, regardless of the scene's
            # global default tangent setting.  The separate keyTangent call
            # confirms the override; without the setKeyframe flags the scene
            # default (often "auto", an S-curve) gets baked in first.
            cmds.setKeyframe(plug, time=frame, value=value,
                             inTangentType=tangent, outTangentType=tangent)
            cmds.keyTangent(plug, time=(frame, frame), inTangentType=tangent, outTangentType=tangent)
            self._keyed_attrs.add(plug)

    def _key_release(self, viseme: str, frame: int, tangent: str) -> None:
        target_pose = pose_library.get_pose(viseme)
        rest_pose   = pose_library.get_pose("REST")
        for control, attrs in target_pose.items():
            node = self._node_name(control)
            if not cmds.objExists(node):
                cmds.warning(f"SunnyLipsync: missing controller '{node}', skipping.")
                continue
            for attr, target_value in attrs.items():
                rest_value = rest_pose.get(control, {}).get(attr, 0.0)
                release_value = (target_value * RELEASE_TARGET_WEIGHT) + (rest_value * RELEASE_REST_WEIGHT)
                plug = f"{node}.{attr}"
                if not cmds.objExists(plug):
                    cmds.warning(f"SunnyLipsync: missing attribute '{plug}', skipping.")
                    continue
                scaled = self._scaled_value(control, attr, release_value, 1.0)
                # Pass tangent directly into setKeyframe so the key is never
                # created with the scene's global default (S-curve) first.
                cmds.setKeyframe(plug, time=frame, value=scaled,
                                 inTangentType=tangent, outTangentType=tangent)
                cmds.keyTangent(plug, time=(frame, frame), inTangentType=tangent, outTangentType=tangent)
                self._keyed_attrs.add(plug)

    def _smooth_keys(self, frame_start: int, frame_end: int) -> None:
        if self.smoothing <= 1:
            return
        window = float(self.smoothing)
        for plug in sorted(self._keyed_attrs):
            times = cmds.keyframe(plug, q=True, time=(frame_start, frame_end), timeChange=True) or []
            values = cmds.keyframe(plug, q=True, time=(frame_start, frame_end), valueChange=True) or []
            if not times or not values or len(times) != len(values):
                continue
            smoothed: list[tuple[float, float]] = []
            for idx, t in enumerate(times):
                near = [
                    float(values[j])
                    for j, t2 in enumerate(times)
                    if abs(float(t2) - float(t)) <= window
                ]
                if near:
                    smoothed.append((float(t), sum(near) / len(near)))
                else:
                    smoothed.append((float(t), float(values[idx])))
            for idx, (t, value) in enumerate(smoothed):
                # Use index-based edit to avoid floating-point precision misses
                # that can occur when (t, t) range lookup doesn't hit the exact
                # stored key time.
                cmds.keyframe(plug, edit=True, index=(idx, idx), valueChange=value)

    def _flatten_tangents(self, frame_start: int, frame_end: int) -> None:
        """Stamp every lipsync key in the range to flat in/out tangents.

        This runs as the final pass in write(), after both keying and smoothing
        are complete.  It is necessary because _smooth_keys edits key values
        without touching tangents, so Maya re-evaluates the curve shape using
        the scene's default tangent preference (usually ``auto`` or
        ``clamped``).  Those algorithms angle the tangent handles to create
        smooth S-curves between keys, which causes visible jitter when keys
        are densely packed.  Flat tangents hold each value cleanly until the
        next key with no overshoot.
        """
        if not self._keyed_attrs:
            return
        for plug in self._keyed_attrs:
            cmds.keyTangent(
                plug,
                time=(frame_start, frame_end),
                inTangentType="flat",
                outTangentType="flat",
            )


def audio_to_maya_scene(audio_path: str, start_frame: int, fps: float = 24.0) -> str:
    """Import audio into Maya timeline and return sound node name."""
    if not MAYA_AVAILABLE:
        raise MayaPluginError("Maya APIs unavailable: audio import must run in Maya.")
    try:
        file_path = Path(audio_path)
        if not file_path.exists():
            raise MayaPluginError(f"Audio file not found: {audio_path}")

        # cmds.sound(offset=...) expects seconds, not frame numbers.
        offset_seconds = (start_frame - 1) / fps
        sound_node = cmds.sound(file=audio_path, offset=offset_seconds)
        playback_slider = mel.eval("$tmp=$gPlayBackSlider")
        cmds.timeControl(playback_slider, edit=True, sound=sound_node, displaySound=True)

        duration = _audio_duration_seconds(audio_path)
        if duration <= 0.0:
            duration = float(cmds.sound(sound_node, q=True, length=True) or 1.0)

        end_frame = int(math.ceil(start_frame + (duration * fps)))
        cmds.playbackOptions(minTime=start_frame, maxTime=end_frame, animationStartTime=start_frame, animationEndTime=end_frame)
        return str(sound_node)
    except Exception as exc:
        raise MayaPluginError(f"Failed to import audio: {exc}") from exc


def _audio_duration_seconds(audio_path: str) -> float:
    """Best-effort duration helper."""
    try:
        if Path(audio_path).suffix.lower() == ".wav":
            with wave.open(audio_path, "rb") as wav:
                return wav.getnframes() / float(wav.getframerate())
    except Exception:
        return 0.0
    return 0.0


if MAYA_AVAILABLE:

    class SunnyLipsyncNode(om.MPxNode):
        """Dependency node carrying Sunny lipsync configuration attributes."""

        kNodeName = "SunnyLipsyncNode"
        # User-defined node type ID reserved for SunnyLipsync in local pipeline range.
        kNodeId = om.MTypeId(0x00127850)

        audioFilePath = om.MObject()
        startFrame = om.MObject()
        fps = om.MObject()
        smoothingWindow = om.MObject()
        blendOvershoot = om.MObject()
        jawScaleBias = om.MObject()
        expressionIntensity = om.MObject()
        outputStatus = om.MObject()

        def __init__(self) -> None:
            super().__init__()

        def compute(self, plug: om.MPlug, data_block: om.MDataBlock) -> None:
            """Generate node status text for UI/graph feedback."""
            if plug != SunnyLipsyncNode.outputStatus:
                return
            try:
                path = data_block.inputValue(SunnyLipsyncNode.audioFilePath).asString()
                status = "Ready" if path else "Missing audio file path"
                out_handle = data_block.outputValue(SunnyLipsyncNode.outputStatus)
                out_handle.setString(status)
                data_block.setClean(plug)
            except Exception as exc:
                raise RuntimeError(
                    f"SunnyLipsyncNode compute failed for plug '{plug.partialName()}': {exc}. "
                    "Check node connections and attribute values."
                )

        @staticmethod
        def creator() -> om.MPxNode:
            return SunnyLipsyncNode()

        @staticmethod
        def initialize() -> None:
            typed_attr = om.MFnTypedAttribute()
            num_attr = om.MFnNumericAttribute()
            # Each attribute must have its own default MObject; sharing one
            # MObject between two typed attributes can corrupt both defaults.
            audio_path_default = om.MFnStringData().create("")
            output_status_default = om.MFnStringData().create("")

            SunnyLipsyncNode.audioFilePath = typed_attr.create("audioFilePath", "afp", om.MFnData.kString, audio_path_default)
            typed_attr.writable = True
            typed_attr.storable = True

            SunnyLipsyncNode.startFrame = num_attr.create("startFrame", "sf", om.MFnNumericData.kInt, 1)
            SunnyLipsyncNode.fps = num_attr.create("fps", "fps", om.MFnNumericData.kFloat, 24.0)
            SunnyLipsyncNode.smoothingWindow = num_attr.create("smoothingWindow", "sw", om.MFnNumericData.kInt, 3)
            SunnyLipsyncNode.blendOvershoot = num_attr.create("blendOvershoot", "bo", om.MFnNumericData.kFloat, 1.05)
            SunnyLipsyncNode.jawScaleBias = num_attr.create("jawScaleBias", "jb", om.MFnNumericData.kFloat, 1.0)
            SunnyLipsyncNode.expressionIntensity = num_attr.create("expressionIntensity", "ei", om.MFnNumericData.kFloat, 1.0)
            # setMin/setMax must be called on the same MFnNumericAttribute
            # instance immediately after create(), not on a rewrapped object
            # which may target the wrong attribute.
            num_attr.setMin(0.0)
            num_attr.setMax(2.0)

            SunnyLipsyncNode.outputStatus = typed_attr.create("outputStatus", "os", om.MFnData.kString, output_status_default)
            typed_attr.writable = False
            typed_attr.storable = False

            for attr in (
                SunnyLipsyncNode.audioFilePath,
                SunnyLipsyncNode.startFrame,
                SunnyLipsyncNode.fps,
                SunnyLipsyncNode.smoothingWindow,
                SunnyLipsyncNode.blendOvershoot,
                SunnyLipsyncNode.jawScaleBias,
                SunnyLipsyncNode.expressionIntensity,
                SunnyLipsyncNode.outputStatus,
            ):
                SunnyLipsyncNode.addAttribute(attr)

            for input_attr in (
                SunnyLipsyncNode.audioFilePath,
                SunnyLipsyncNode.startFrame,
                SunnyLipsyncNode.fps,
                SunnyLipsyncNode.smoothingWindow,
                SunnyLipsyncNode.blendOvershoot,
                SunnyLipsyncNode.jawScaleBias,
                SunnyLipsyncNode.expressionIntensity,
            ):
                SunnyLipsyncNode.attributeAffects(input_attr, SunnyLipsyncNode.outputStatus)


    class SunnyLipsyncCommand(om.MPxCommand):
        """Command entry-point for generating Sunny lipsync animation."""

        kCommandName = "sunnyLipsync"

        def __init__(self) -> None:
            super().__init__()
            self._did_change_scene = False

        @staticmethod
        def creator() -> om.MPxCommand:
            return SunnyLipsyncCommand()

        @staticmethod
        def create_syntax() -> om.MSyntax:
            syntax = om.MSyntax()
            syntax.addFlag("-f",  "-file",       om.MSyntax.kString)
            syntax.addFlag("-ns", "-namespace",  om.MSyntax.kString)
            syntax.addFlag("-sf", "-startFrame", om.MSyntax.kLong)
            syntax.addFlag("-fps","-fps",        om.MSyntax.kDouble)
            syntax.addFlag("-sm", "-smoothing",  om.MSyntax.kLong)
            syntax.addFlag("-os", "-overshoot",  om.MSyntax.kDouble)
            syntax.addFlag("-jb", "-jawBias",    om.MSyntax.kDouble)
            syntax.addFlag("-ei", "-exprInt",    om.MSyntax.kDouble)
            syntax.addFlag("-p",  "-preview",    om.MSyntax.kBoolean)
            syntax.addFlag("-c",  "-clear",      om.MSyntax.kBoolean)
            # Optional typed script for guided forced alignment.
            # When supplied, Whisper aligns the audio to these exact words
            # rather than freely transcribing, giving more accurate timings.
            syntax.addFlag("-sc", "-script",     om.MSyntax.kString)
            return syntax

        def isUndoable(self) -> bool:
            # write() and clear_all_keys() self-manage named undo chunks via
            # cmds.undoInfo(openChunk/closeChunk), so Maya handles undo
            # automatically.  Returning True here and delegating to cmds.undo()
            # inside undoIt() would trigger infinite recursion.
            return False

        def doIt(self, args: om.MArgList) -> None:
            try:
                arg_db = om.MArgDatabase(self.syntax(), args)
                clear       = arg_db.flagArgumentBool("-c",   0) if arg_db.isFlagSet("-c")   else False
                preview     = arg_db.flagArgumentBool("-p",   0) if arg_db.isFlagSet("-p")   else False
                file_path   = arg_db.flagArgumentString("-f", 0) if arg_db.isFlagSet("-f")   else ""
                namespace   = arg_db.flagArgumentString("-ns",0) if arg_db.isFlagSet("-ns")  else ""
                start_frame = arg_db.flagArgumentInt("-sf",   0) if arg_db.isFlagSet("-sf")  else 1
                fps         = float(arg_db.flagArgumentDouble("-fps",0) if arg_db.isFlagSet("-fps") else 24.0)
                smoothing   = arg_db.flagArgumentInt("-sm",   0) if arg_db.isFlagSet("-sm")  else 3
                overshoot   = float(arg_db.flagArgumentDouble("-os", 0) if arg_db.isFlagSet("-os")  else 1.05)
                jaw_bias    = float(arg_db.flagArgumentDouble("-jb", 0) if arg_db.isFlagSet("-jb")  else 1.0)
                expr_int    = float(arg_db.flagArgumentDouble("-ei", 0) if arg_db.isFlagSet("-ei")  else 1.0)
                script_text = arg_db.flagArgumentString("-sc",0) if arg_db.isFlagSet("-sc")  else ""

                writer = LipsyncAnimWriter(
                    char_namespace=namespace,
                    fps=fps,
                    start_frame=start_frame,
                    smoothing=smoothing,
                    overshoot=overshoot,
                    jaw_bias=jaw_bias,
                    expr_intensity=expr_int,
                )

                if clear:
                    cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncClear")
                    try:
                        writer.clear_all_keys()
                        self._did_change_scene = True
                    finally:
                        cmds.undoInfo(closeChunk=True)
                    om.MGlobal.displayInfo("SunnyLipsync: cleared lipsync keys.")
                    return

                if not file_path:
                    raise MayaPluginError("-file/-f is required unless -clear is used.")

                detector = PhonemeDetector(file_path, fps, script_text=script_text)
                timeline = detector.detect()
                if preview:
                    for segment in timeline:
                        om.MGlobal.displayInfo(f"{segment}")
                    om.MGlobal.displayInfo(f"SunnyLipsync preview: {len(timeline)} segments")
                    return

                # Import audio only after detecting phonemes succeeds.
                # write() opens its own undo chunk internally, so wrap both
                # operations together so audio import is also undoable.
                cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncFull")
                try:
                    audio_to_maya_scene(file_path, start_frame, fps)
                    writer.write(timeline)
                    self._did_change_scene = True
                except Exception:
                    cmds.undoInfo(closeChunk=True)
                    raise
                cmds.undoInfo(closeChunk=True)

                frame_start = writer.to_frame(timeline[0][0])
                frame_end = writer.to_frame(timeline[-1][1])
                duration = max(0.0, timeline[-1][1] - timeline[0][0])
                om.MGlobal.displayInfo(
                    f"SunnyLipsync wrote {len(timeline)} segments, frames {frame_start}-{frame_end}, duration {duration:.2f}s"
                )
            except Exception as exc:
                om.MGlobal.displayError(f"SunnyLipsync failed: {exc}")
                om.MGlobal.displayError(traceback.format_exc())
                raise

else:

    class SunnyLipsyncNode:  # pragma: no cover - placeholder outside Maya
        """Placeholder class in non-Maya environments."""


    class SunnyLipsyncCommand:  # pragma: no cover - placeholder outside Maya
        """Placeholder class in non-Maya environments."""


def _maya_main_window() -> QtWidgets.QWidget | None:
    """Return Maya main window as QWidget."""
    if not MAYA_AVAILABLE or not omui or not shiboken6:
        return None
    ptr = omui.MQtUtil.mainWindow()
    return shiboken6.wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None


# Colour palette for each viseme — used by the timeline canvas.
_VISEME_COLORS: dict[str, str] = {
    "REST":      "#444444",
    "MBP":       "#e05555",
    "FV":        "#e07a35",
    "TH":        "#d4b800",
    "DD":        "#7ab800",
    "KG":        "#2daa55",
    "CH_SH_ZH":  "#2aaab0",
    "EE":        "#2a80e0",
    "IH":        "#5555e0",
    "OOH_W":     "#9955dd",
    "OH":        "#dd55aa",
    "AH":        "#dd2266",
    "AA":        "#cc4455",
    "L":         "#b07030",
    "NN":        "#808080",
}


class PhonemeTimelineCanvas(QtWidgets.QWidget):
    """Interactive phoneme timeline display and editor.

    Displays detected viseme segments as coloured blocks on a horizontal
    timeline.  Supports:
    - Click a block → reassign its viseme via a context menu
    - Drag left/right edge → adjust start/end time
    - Right-click → delete block
    - All edits are applied in-place to the shared ``_segments`` list so
      ``SunnyLipsyncDock`` can read the result at Apply time.

    Usage
    -----
    ``canvas.load(timeline)`` where *timeline* is
    ``list[tuple[float, float, str]]`` (start, end, viseme).
    """

    # Minimum drag handle width in pixels.
    _HANDLE_PX = 8
    # Row height inside the canvas.
    _ROW_H     = 60
    # Pixel padding above/below the row.
    _PAD_Y     = 20
    # Pixels per second of audio — zoom factor.
    _PX_PER_SEC = 120

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        # Each segment: [start_sec, end_sec, viseme]
        self._segments: list[list] = []
        # Drag state
        self._drag_seg_idx:  int | None = None
        self._drag_mode:     str | None = None  # "left", "right", "body"
        self._drag_origin_x: int        = 0
        self._drag_orig_start: float    = 0.0
        self._drag_orig_end:   float    = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, timeline: list[tuple[float, float, str]]) -> None:
        """Populate from a detector timeline and repaint."""
        self._segments = [[s, e, v] for s, e, v in timeline]
        self._update_canvas_width()
        self.update()

    def get_timeline(self) -> list[tuple[float, float, str]]:
        """Return the current (possibly edited) timeline."""
        return [(seg[0], seg[1], seg[2]) for seg in self._segments]

    def clear(self) -> None:
        self._segments.clear()
        self.setMinimumWidth(0)
        self.update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_canvas_width(self) -> None:
        if not self._segments:
            self.setMinimumWidth(0)
            return
        total_sec = max(seg[1] for seg in self._segments)
        self.setMinimumWidth(int(total_sec * self._PX_PER_SEC) + 40)

    def _sec_to_x(self, sec: float) -> int:
        return int(sec * self._PX_PER_SEC) + 20

    def _x_to_sec(self, x: int) -> float:
        return max(0.0, (x - 20) / self._PX_PER_SEC)

    def _seg_rect(self, seg: list) -> QtCore.QRect:
        x1 = self._sec_to_x(seg[0])
        x2 = self._sec_to_x(seg[1])
        y  = self._PAD_Y
        return QtCore.QRect(x1, y, max(x2 - x1, 4), self._ROW_H)

    def _hit_test(self, pos: QtCore.QPoint) -> tuple[int, str] | None:
        """Return (seg_index, mode) where mode is 'left', 'right', or 'body'."""
        for i, seg in enumerate(self._segments):
            r = self._seg_rect(seg)
            if not r.contains(pos):
                continue
            if abs(pos.x() - r.left()) <= self._HANDLE_PX:
                return i, "left"
            if abs(pos.x() - r.right()) <= self._HANDLE_PX:
                return i, "right"
            return i, "body"
        return None

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        # Background
        painter.fillRect(self.rect(), QtGui.QColor("#1e1e1e"))

        if not self._segments:
            painter.setPen(QtGui.QColor("#888"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No timeline data")
            return

        # Tick marks every second
        total_sec = max(seg[1] for seg in self._segments)
        painter.setPen(QtGui.QColor("#444"))
        for s in range(int(total_sec) + 2):
            x = self._sec_to_x(float(s))
            painter.drawLine(x, 0, x, self.height())
            painter.setPen(QtGui.QColor("#666"))
            painter.drawText(x + 2, self._PAD_Y - 4, f"{s}s")
            painter.setPen(QtGui.QColor("#444"))

        # Segments
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        for i, seg in enumerate(self._segments):
            r = self._seg_rect(seg)
            viseme = seg[2]
            color_hex = _VISEME_COLORS.get(viseme, "#555555")
            color = QtGui.QColor(color_hex)

            # Fill
            painter.fillRect(r, color)

            # Border (slightly darker)
            border = color.darker(140)
            painter.setPen(QtGui.QPen(border, 1))
            painter.drawRect(r)

            # Drag handles (lighter vertical strip)
            handle_color = color.lighter(160)
            painter.fillRect(QtCore.QRect(r.left(), r.top(), self._HANDLE_PX, r.height()), handle_color)
            painter.fillRect(QtCore.QRect(r.right() - self._HANDLE_PX, r.top(), self._HANDLE_PX, r.height()), handle_color)

            # Label — clip to block width
            painter.setPen(QtGui.QColor("white"))
            text_rect = r.adjusted(self._HANDLE_PX + 2, 4, -self._HANDLE_PX - 2, -4)
            painter.drawText(text_rect, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, viseme)

        painter.end()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(600, self._ROW_H + self._PAD_Y * 2)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        hit = self._hit_test(event.pos())
        if event.button() == QtCore.Qt.RightButton:
            if hit is not None:
                self._context_menu(hit[0], event.globalPos())
            return
        if hit is None:
            return
        idx, mode = hit
        self._drag_seg_idx    = idx
        self._drag_mode       = mode
        self._drag_origin_x   = event.pos().x()
        self._drag_orig_start = self._segments[idx][0]
        self._drag_orig_end   = self._segments[idx][1]

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        # Update cursor shape based on hover
        hit = self._hit_test(event.pos())
        if hit and hit[1] in ("left", "right"):
            self.setCursor(QtCore.Qt.SizeHorCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)

        if self._drag_seg_idx is None:
            return
        dx  = event.pos().x() - self._drag_origin_x
        dt  = dx / self._PX_PER_SEC
        seg = self._segments[self._drag_seg_idx]
        MIN_DUR = 1.0 / 24.0  # one frame minimum

        if self._drag_mode == "left":
            new_start = max(0.0, self._drag_orig_start + dt)
            if self._drag_orig_end - new_start >= MIN_DUR:
                seg[0] = round(new_start, 4)
        elif self._drag_mode == "right":
            new_end = max(self._drag_orig_start + MIN_DUR, self._drag_orig_end + dt)
            seg[1] = round(new_end, 4)
        # "body" drag is intentionally not implemented — moving a block would
        # create overlapping segments and confuse the writer.  Users can
        # adjust start/end independently with the handles.
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        self._drag_seg_idx = None
        self._drag_mode    = None
        self._update_canvas_width()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        """Double-click a block to reassign its viseme via a combo-box dialog."""
        hit = self._hit_test(event.pos())
        if hit is None:
            return
        self._reassign_viseme(hit[0], event.globalPos())

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _context_menu(self, seg_idx: int, global_pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        reassign_action = menu.addAction("Reassign viseme…")
        menu.addSeparator()
        delete_action   = menu.addAction("Delete segment")
        chosen = menu.exec(global_pos)
        if chosen == reassign_action:
            self._reassign_viseme(seg_idx, global_pos)
        elif chosen == delete_action:
            del self._segments[seg_idx]
            self._update_canvas_width()
            self.update()

    def _reassign_viseme(self, seg_idx: int, global_pos: QtCore.QPoint) -> None:
        """Show an inline combo picker and reassign the segment's viseme."""
        current = self._segments[seg_idx][2]
        all_visemes = sorted(VISEME_POSES.keys())

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Reassign Viseme")
        dialog.setWindowFlags(
            dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        dlg_layout = QtWidgets.QVBoxLayout(dialog)
        dlg_layout.addWidget(QtWidgets.QLabel("Choose replacement viseme:"))
        combo = QtWidgets.QComboBox()
        for v in all_visemes:
            combo.addItem(v)
        combo.setCurrentText(current)
        dlg_layout.addWidget(combo)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btns)

        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._segments[seg_idx][2] = combo.currentText()
            self.update()


class SunnyLipsyncDock(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """Dockable PySide6 UI for Sunny lipsync generation."""

    WINDOW_OBJECT = "SunnyLipsyncWorkspaceControl"

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("SunnyLipsyncUI")
        self.setWindowTitle("Sunny Lipsync")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        tabs = QtWidgets.QTabWidget()
        root.addWidget(tabs)

        # ------------------------------------------------------------------
        # Tab 1 — Generate (all existing functionality, unchanged)
        # ------------------------------------------------------------------
        gen_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(gen_widget)
        tabs.addTab(gen_widget, "Generate")

        file_row = QtWidgets.QHBoxLayout()
        self.file_path = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse)
        file_row.addWidget(QtWidgets.QLabel("Audio File"))
        file_row.addWidget(self.file_path, 1)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        self.namespace = QtWidgets.QLineEdit()
        self.start_frame = QtWidgets.QSpinBox()
        self.start_frame.setRange(UI_START_FRAME_MIN, UI_START_FRAME_MAX)
        self.start_frame.setValue(1)

        self.fps_combo = QtWidgets.QComboBox()
        for fps in (12, 24, 25, 30, 48, 60):
            self.fps_combo.addItem(str(fps), fps)
        self.fps_combo.setCurrentText("24")

        self.smoothing = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.smoothing.setRange(1, 10)
        self.smoothing.setValue(3)
        self.jaw_bias  = self._make_float_slider(50,  200, 100)
        self.expr_int  = self._make_float_slider(0,   200, 100)
        self.overshoot = self._make_float_slider(100, 130, 105)

        form = QtWidgets.QFormLayout()
        form.addRow("Namespace",            self.namespace)
        form.addRow("Start Frame",          self.start_frame)
        form.addRow("FPS",                  self.fps_combo)
        form.addRow("Smoothing",            self.smoothing)
        form.addRow("Jaw Bias",             self.jaw_bias)
        form.addRow("Expression Intensity", self.expr_int)
        form.addRow("Overshoot",            self.overshoot)
        layout.addLayout(form)

        # ffmpeg path row — needed on Windows where PATH may not include ffmpeg.
        ffmpeg_row = QtWidgets.QHBoxLayout()
        self.ffmpeg_path = QtWidgets.QLineEdit()
        self.ffmpeg_path.setPlaceholderText("Path to ffmpeg.exe (required on Windows)")
        self.ffmpeg_path.setText(r"C:\ffmpeg-2026-05-11-git-17bc88e67f-essentials_build\bin\ffmpeg.exe")
        ffmpeg_browse = QtWidgets.QPushButton("Browse")
        ffmpeg_browse.clicked.connect(self._browse_ffmpeg)
        ffmpeg_row.addWidget(QtWidgets.QLabel("ffmpeg"))
        ffmpeg_row.addWidget(self.ffmpeg_path, 1)
        ffmpeg_row.addWidget(ffmpeg_browse)
        layout.addLayout(ffmpeg_row)

        # ------------------------------------------------------------------
        # Detection Settings — Whisper model size and confidence threshold
        # ------------------------------------------------------------------
        layout.addWidget(_HSeparator())
        layout.addWidget(QtWidgets.QLabel("<b>Detection Settings</b>"))

        det_form = QtWidgets.QFormLayout()

        self.whisper_model_combo = QtWidgets.QComboBox()
        for m in PhonemeDetector.WHISPER_MODELS:
            self.whisper_model_combo.addItem(m, m)
        self.whisper_model_combo.setCurrentText("base")
        self.whisper_model_combo.setToolTip(
            "Whisper model to use for speech recognition.\n"
            "Larger models are slower but noticeably more accurate,\n"
            "especially for accented speech."
        )
        det_form.addRow("Whisper Model", self.whisper_model_combo)

        self.min_confidence_spin = QtWidgets.QDoubleSpinBox()
        self.min_confidence_spin.setRange(0.0, 1.0)
        self.min_confidence_spin.setSingleStep(0.05)
        self.min_confidence_spin.setDecimals(2)
        self.min_confidence_spin.setValue(0.0)
        self.min_confidence_spin.setToolTip(
            "Minimum Whisper segment confidence (0 = keep everything).\n"
            "Segments below this threshold are replaced with REST instead\n"
            "of producing garbled visemes."
        )
        det_form.addRow("Min Confidence", self.min_confidence_spin)

        layout.addLayout(det_form)

        # ------------------------------------------------------------------
        # Per-Controller Scale — independent multipliers for each mouth region
        # ------------------------------------------------------------------
        layout.addWidget(_HSeparator())
        layout.addWidget(QtWidgets.QLabel("<b>Per-Controller Scale</b>"))

        ctrl_form = QtWidgets.QFormLayout()

        self.jaw_scale         = self._make_float_slider(0, 200, 100)
        self.upper_lip_scale   = self._make_float_slider(0, 200, 100)
        self.lower_lip_scale   = self._make_float_slider(0, 200, 100)
        self.corner_scale      = self._make_float_slider(0, 200, 100)

        self.jaw_scale.setToolTip("Scale MD_Mouth_01_Jaw_Ctrl independently.")
        self.upper_lip_scale.setToolTip("Scale Up_Mouth_01_Ctrl independently.")
        self.lower_lip_scale.setToolTip("Scale Low_Mouth_01_Ctrl independently.")
        self.corner_scale.setToolTip("Scale LF/RT_Mouth_01_Ctrl independently.")

        ctrl_form.addRow("Jaw Scale",        self.jaw_scale)
        ctrl_form.addRow("Upper Lip Scale",  self.upper_lip_scale)
        ctrl_form.addRow("Lower Lip Scale",  self.lower_lip_scale)
        ctrl_form.addRow("Corner Scale",     self.corner_scale)

        layout.addLayout(ctrl_form)

        button_row = QtWidgets.QHBoxLayout()
        preview_btn  = QtWidgets.QPushButton("Preview Phonemes")
        generate_btn = QtWidgets.QPushButton("Generate Lipsync")
        clear_btn    = QtWidgets.QPushButton("Clear Lipsync Keys")
        preview_btn.clicked.connect( lambda: self._run(preview=True,  clear=False))
        generate_btn.clicked.connect(lambda: self._run(preview=False, clear=False))
        clear_btn.clicked.connect(   lambda: self._run(preview=False, clear=True))
        button_row.addWidget(preview_btn)
        button_row.addWidget(generate_btn)
        button_row.addWidget(clear_btn)
        layout.addLayout(button_row)

        layout.addWidget(_HSeparator())

        # ------------------------------------------------------------------
        # Script-guided mode
        # A radio toggle lets the user choose between audio-only detection
        # and guided detection where their typed text anchors Whisper's
        # forced alignment, giving more accurate per-phoneme timing.
        # ------------------------------------------------------------------
        mode_row = QtWidgets.QHBoxLayout()
        self._mode_audio_only   = QtWidgets.QRadioButton("Audio Only")
        self._mode_audio_script = QtWidgets.QRadioButton("Audio + Script  (more accurate)")
        self._mode_audio_only.setChecked(True)
        self._mode_audio_only.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(QtWidgets.QLabel("Detection Mode:"))
        mode_row.addWidget(self._mode_audio_only)
        mode_row.addWidget(self._mode_audio_script)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Script widgets — hidden until Audio + Script mode is selected
        self._script_label = QtWidgets.QLabel(
            "Type or paste the dialogue exactly as spoken in the audio.\n"
            "Whisper will align its timestamps to your text rather than freely\n"
            "transcribing, giving more accurate phoneme timing."
        )
        self._script_label.setWordWrap(True)

        self._script_edit = QtWidgets.QPlainTextEdit()
        self._script_edit.setPlaceholderText(
            "e.g.  Hello, my name is Sunny and I am ready to talk."
        )
        self._script_edit.setFixedHeight(90)
        self._script_edit.textChanged.connect(self._on_script_changed)

        self._script_char_count = QtWidgets.QLabel("0 words")
        self._script_char_count.setAlignment(QtCore.Qt.AlignRight)

        # Start hidden
        self._script_label.hide()
        self._script_edit.hide()
        self._script_char_count.hide()

        layout.addWidget(self._script_label)
        layout.addWidget(self._script_edit)
        layout.addWidget(self._script_char_count)

        layout.addWidget(_HSeparator())

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status = QtWidgets.QLabel("Idle")
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        # ------------------------------------------------------------------
        # Tab 2 — Pose Library
        # ------------------------------------------------------------------
        pose_widget = QtWidgets.QWidget()
        pose_layout = QtWidgets.QVBoxLayout(pose_widget)
        tabs.addTab(pose_widget, "Pose Library")

        # Explanation label
        info = QtWidgets.QLabel(
            "Pose the Sunny rig in the viewport, then select a viseme below\n"
            "and click  Capture from Rig  to record it as that viseme's pose.\n"
            "Poses are saved automatically to SunnyLipsync_poses.json."
        )
        info.setWordWrap(True)
        pose_layout.addWidget(info)

        pose_layout.addWidget(_HSeparator())

        # Viseme selector list
        pose_layout.addWidget(QtWidgets.QLabel("Visemes:"))
        self._pose_list = QtWidgets.QListWidget()
        self._pose_list.setFixedHeight(220)
        self._pose_list.setAlternatingRowColors(True)
        for viseme in sorted(VISEME_POSES.keys()):
            self._pose_list.addItem(viseme)
        # Pre-select REST
        matches = self._pose_list.findItems("REST", QtCore.Qt.MatchExactly)
        if matches:
            self._pose_list.setCurrentItem(matches[0])
        self._pose_list.currentItemChanged.connect(self._on_viseme_selected)
        pose_layout.addWidget(self._pose_list)

        # Customised indicator
        self._pose_status_label = QtWidgets.QLabel("")
        self._pose_status_label.setAlignment(QtCore.Qt.AlignCenter)
        pose_layout.addWidget(self._pose_status_label)

        pose_layout.addWidget(_HSeparator())

        # Capture / Reset buttons
        cap_row = QtWidgets.QHBoxLayout()
        self._capture_btn = QtWidgets.QPushButton("Capture from Rig")
        self._capture_btn.setToolTip(
            "Read the current position of every tracked controller from the\n"
            "scene and store it as the pose for the selected viseme."
        )
        self._capture_btn.clicked.connect(self._on_capture_pose)
        self._reset_btn = QtWidgets.QPushButton("Reset to Default")
        self._reset_btn.setToolTip(
            "Restore the selected viseme to the built-in default pose."
        )
        self._reset_btn.clicked.connect(self._on_reset_pose)
        cap_row.addWidget(self._capture_btn)
        cap_row.addWidget(self._reset_btn)
        pose_layout.addLayout(cap_row)

        reset_all_btn = QtWidgets.QPushButton("Reset ALL Visemes to Defaults")
        reset_all_btn.setToolTip(
            "Discard all custom poses and restore the full built-in library."
        )
        reset_all_btn.clicked.connect(self._on_reset_all_poses)
        pose_layout.addWidget(reset_all_btn)

        pose_layout.addWidget(_HSeparator())

        # Save-path row — lets the user redirect the JSON file if needed
        save_path_row = QtWidgets.QHBoxLayout()
        self._save_path_edit = QtWidgets.QLineEdit(str(pose_library.save_path))
        self._save_path_edit.setToolTip(
            "Path where SunnyLipsync_poses.json is read from and written to."
        )
        save_path_browse = QtWidgets.QPushButton("…")
        save_path_browse.setFixedWidth(28)
        save_path_browse.clicked.connect(self._on_browse_save_path)
        save_path_row.addWidget(QtWidgets.QLabel("Library file:"))
        save_path_row.addWidget(self._save_path_edit, 1)
        save_path_row.addWidget(save_path_browse)
        pose_layout.addLayout(save_path_row)

        self._pose_msg_label = QtWidgets.QLabel("")
        self._pose_msg_label.setAlignment(QtCore.Qt.AlignCenter)
        pose_layout.addWidget(self._pose_msg_label)

        pose_layout.addStretch()

        # Initial indicator refresh
        self._refresh_pose_indicator()

        # ------------------------------------------------------------------
        # Tab 3 — Phoneme Timeline Editor
        # ------------------------------------------------------------------
        timeline_widget = QtWidgets.QWidget()
        timeline_layout = QtWidgets.QVBoxLayout(timeline_widget)
        tabs.addTab(timeline_widget, "Timeline Editor")

        tl_info = QtWidgets.QLabel(
            "After running Preview or Generate, the detected phoneme timeline\n"
            "appears below.  Click a block to reassign its viseme, drag its\n"
            "left/right edge to adjust timing, or right-click to delete it.\n"
            "Press  Apply  to re-key the edited timeline on the rig."
        )
        tl_info.setWordWrap(True)
        timeline_layout.addWidget(tl_info)

        timeline_layout.addWidget(_HSeparator())

        # Canvas
        self._timeline_canvas = PhonemeTimelineCanvas()
        self._timeline_canvas.setMinimumHeight(110)
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self._timeline_canvas)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        timeline_layout.addWidget(scroll_area, 1)

        tl_btn_row = QtWidgets.QHBoxLayout()
        self._tl_apply_btn  = QtWidgets.QPushButton("Apply Timeline to Rig")
        self._tl_apply_btn.setToolTip(
            "Re-key the rig using the edited timeline (respects all Generate tab settings)."
        )
        self._tl_apply_btn.clicked.connect(self._on_timeline_apply)
        self._tl_clear_btn  = QtWidgets.QPushButton("Clear Timeline")
        self._tl_clear_btn.setToolTip("Discard the current timeline display.")
        self._tl_clear_btn.clicked.connect(self._on_timeline_clear)
        tl_btn_row.addWidget(self._tl_apply_btn)
        tl_btn_row.addWidget(self._tl_clear_btn)
        timeline_layout.addLayout(tl_btn_row)

        self._tl_status = QtWidgets.QLabel("No timeline loaded.  Run Preview or Generate first.")
        self._tl_status.setAlignment(QtCore.Qt.AlignCenter)
        timeline_layout.addWidget(self._tl_status)

        # Internal timeline data — list of [start_sec, end_sec, viseme_str]
        # (mutable so the canvas edits propagate back here).
        self._timeline_data: list[list] = []

    def _make_float_slider(self, min_i: int, max_i: int, value_i: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(min_i, max_i)
        slider.setValue(value_i)
        return slider

    def _on_mode_changed(self) -> None:
        """Show or hide the script panel depending on the selected mode."""
        guided = self._mode_audio_script.isChecked()
        self._script_label.setVisible(guided)
        self._script_edit.setVisible(guided)
        self._script_char_count.setVisible(guided)

    def _on_script_changed(self) -> None:
        """Update the word count label as the user types."""
        text  = self._script_edit.toPlainText()
        count = len(text.split()) if text.strip() else 0
        self._script_char_count.setText(f"{count} word{'s' if count != 1 else ''}")

    def _browse(self) -> None:
        audio_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Audio", "", "Audio Files (*.wav *.mp3)")
        if audio_path:
            self.file_path.setText(audio_path)

    def _browse_ffmpeg(self) -> None:
        ffmpeg_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select ffmpeg.exe", "", "Executable (*.exe)")
        if ffmpeg_path:
            self.ffmpeg_path.setText(ffmpeg_path)

    def _run(self, preview: bool, clear: bool) -> None:
        # Disable buttons for the duration of the operation.
        self._set_buttons_enabled(False)
        self.progress.setRange(0, 0)
        self.status.setText("Working…")
        QtWidgets.QApplication.processEvents()

        file_path   = self.file_path.text().strip()
        namespace   = self.namespace.text().strip()
        start_frame = int(self.start_frame.value())
        fps         = float(self.fps_combo.currentData())
        smoothing   = int(self.smoothing.value())
        jaw_bias    = float(self.jaw_bias.value()) / 100.0
        expr_int    = float(self.expr_int.value()) / 100.0
        overshoot   = float(self.overshoot.value()) / 100.0
        ffmpeg_path = self.ffmpeg_path.text().strip('"').strip()
        # Detection settings
        whisper_model  = self.whisper_model_combo.currentData()
        min_confidence = float(self.min_confidence_spin.value())
        # Per-controller scales
        jaw_scale        = float(self.jaw_scale.value())        / 100.0
        upper_lip_scale  = float(self.upper_lip_scale.value())  / 100.0
        lower_lip_scale  = float(self.lower_lip_scale.value())  / 100.0
        corner_scale     = float(self.corner_scale.value())     / 100.0
        # Collect script text only when guided mode is active
        script_text = (
            self._script_edit.toPlainText().strip()
            if self._mode_audio_script.isChecked()
            else ""
        )

        def worker() -> None:
            """Run speech detection off the main thread to avoid crashing Maya.

            PyTorch / Whisper initialise large native libraries that conflict
            with Maya's memory management when loaded on the UI thread.  We do
            the heavy lifting here, then hand the resulting timeline back to
            the main thread via a queued signal so that all Maya API / cmds
            calls happen on the correct thread.
            """
            try:
                if clear:
                    # clear_all_keys only touches Maya cmds — safe to dispatch
                    # back to main thread immediately.
                    QtCore.QMetaObject.invokeMethod(
                        self, "_finish_clear",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, namespace),
                        QtCore.Q_ARG(float, fps),
                        QtCore.Q_ARG(int, start_frame),
                    )
                    return

                if not file_path:
                    QtCore.QMetaObject.invokeMethod(
                        self, "_finish_error",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, "No audio file selected."),
                    )
                    return

                if preview:
                    # Detection only — no Maya writes needed.
                    detector = PhonemeDetector(
                        file_path, fps, ffmpeg_path, script_text,
                        whisper_model=whisper_model,
                        min_confidence=min_confidence,
                    )
                    timeline = detector.detect()
                    mode_tag = " (guided)" if script_text else " (audio-only)"
                    msg = f"Preview: {len(timeline)} segments detected{mode_tag}."
                    timeline_json = json.dumps(timeline)
                    QtCore.QMetaObject.invokeMethod(
                        self, "_finish_preview",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, msg),
                        QtCore.Q_ARG(str, timeline_json),
                    )
                    return

                # Full detection — the expensive part that must stay off-thread.
                detector = PhonemeDetector(
                    file_path, fps, ffmpeg_path, script_text,
                    whisper_model=whisper_model,
                    min_confidence=min_confidence,
                )
                timeline = detector.detect()

                # Serialise both the writer params and the timeline into JSON
                # strings.  PySide6's QMetaObject.invokeMethod has a hard limit
                # on the number of Q_ARG arguments it accepts; packing
                # everything into two strings avoids that limit entirely.
                params_json = json.dumps({
                    "file_path":       file_path,
                    "namespace":       namespace,
                    "start_frame":     start_frame,
                    "fps":             fps,
                    "smoothing":       smoothing,
                    "overshoot":       overshoot,
                    "jaw_bias":        jaw_bias,
                    "expr_int":        expr_int,
                    "jaw_scale":       jaw_scale,
                    "upper_lip_scale": upper_lip_scale,
                    "lower_lip_scale": lower_lip_scale,
                    "corner_scale":    corner_scale,
                })
                timeline_json = json.dumps(timeline)

                # Hand results back to the main thread for all Maya API work.
                QtCore.QMetaObject.invokeMethod(
                    self, "_finish_write",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, params_json),
                    QtCore.Q_ARG(str, timeline_json),
                )
            except Exception as exc:
                QtCore.QMetaObject.invokeMethod(
                    self, "_finish_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, str(exc)),
                )

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    @QtCore.Slot(str, float, int)
    def _finish_clear(self, namespace: str, fps: float, start_frame: int) -> None:
        try:
            writer = LipsyncAnimWriter(char_namespace=namespace, fps=fps, start_frame=start_frame)
            cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncClear")
            try:
                writer.clear_all_keys()
            finally:
                cmds.undoInfo(closeChunk=True)
            self.status.setText("Lipsync keys cleared.")
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")
        finally:
            self._set_buttons_enabled(True)
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    @QtCore.Slot(str, str)
    def _finish_write(self, params_json: str, timeline_json: str) -> None:
        try:
            p        = json.loads(params_json)
            timeline = [tuple(item) for item in json.loads(timeline_json)]
            writer = LipsyncAnimWriter(
                char_namespace   = p["namespace"],
                fps              = float(p["fps"]),
                start_frame      = int(p["start_frame"]),
                smoothing        = int(p["smoothing"]),
                overshoot        = float(p["overshoot"]),
                jaw_bias         = float(p["jaw_bias"]),
                expr_intensity   = float(p["expr_int"]),
                jaw_scale        = float(p["jaw_scale"]),
                upper_lip_scale  = float(p["upper_lip_scale"]),
                lower_lip_scale  = float(p["lower_lip_scale"]),
                corner_scale     = float(p["corner_scale"]),
            )
            cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncFull")
            try:
                audio_to_maya_scene(p["file_path"], int(p["start_frame"]), float(p["fps"]))
                writer.write(timeline)
            except Exception:
                cmds.undoInfo(closeChunk=True)
                raise
            cmds.undoInfo(closeChunk=True)
            # Populate Timeline Editor with the generated timeline.
            self._load_timeline_into_editor(timeline)
            self.status.setText(f"Done — {len(timeline)} segments keyed.")
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")
        finally:
            self._set_buttons_enabled(True)
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    @QtCore.Slot(str)
    def _finish_ok(self, msg: str) -> None:
        self.status.setText(msg)
        self._set_buttons_enabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    @QtCore.Slot(str, str)
    def _finish_preview(self, msg: str, timeline_json: str) -> None:
        """Preview complete — show message and populate the timeline editor."""
        self.status.setText(msg)
        try:
            tl = [tuple(item) for item in json.loads(timeline_json)]
            self._load_timeline_into_editor(tl)
        except Exception:
            pass
        self._set_buttons_enabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    @QtCore.Slot(str)
    def _finish_error(self, msg: str) -> None:
        self.status.setText(f"Failed: {msg}")
        self._set_buttons_enabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for btn in self.findChildren(QtWidgets.QPushButton):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Timeline Editor slots
    # ------------------------------------------------------------------

    def _load_timeline_into_editor(self, timeline: list[tuple[float, float, str]]) -> None:
        """Populate the Timeline Editor tab from a freshly detected timeline."""
        self._timeline_data = [[s, e, v] for s, e, v in timeline]
        self._timeline_canvas.load(timeline)
        self._tl_status.setText(f"{len(timeline)} segments loaded.  Edit then press Apply.")

    def _on_timeline_clear(self) -> None:
        self._timeline_data.clear()
        self._timeline_canvas.clear()
        self._tl_status.setText("Timeline cleared.")

    def _on_timeline_apply(self) -> None:
        """Re-key the rig using the timeline currently shown in the editor."""
        if not self._timeline_canvas.get_timeline():
            self._tl_status.setText("Nothing to apply — timeline is empty.")
            return

        timeline = self._timeline_canvas.get_timeline()
        file_path   = self.file_path.text().strip()
        namespace   = self.namespace.text().strip()
        start_frame = int(self.start_frame.value())
        fps         = float(self.fps_combo.currentData())
        smoothing   = int(self.smoothing.value())
        jaw_bias    = float(self.jaw_bias.value()) / 100.0
        expr_int    = float(self.expr_int.value()) / 100.0
        overshoot   = float(self.overshoot.value()) / 100.0
        jaw_scale        = float(self.jaw_scale.value())        / 100.0
        upper_lip_scale  = float(self.upper_lip_scale.value())  / 100.0
        lower_lip_scale  = float(self.lower_lip_scale.value())  / 100.0
        corner_scale     = float(self.corner_scale.value())     / 100.0

        if not MAYA_AVAILABLE:
            self._tl_status.setText("Apply requires Maya runtime.")
            return

        self._set_buttons_enabled(False)
        self._tl_status.setText("Applying…")
        QtWidgets.QApplication.processEvents()

        try:
            writer = LipsyncAnimWriter(
                char_namespace=namespace,
                fps=fps,
                start_frame=start_frame,
                smoothing=smoothing,
                overshoot=overshoot,
                jaw_bias=jaw_bias,
                expr_intensity=expr_int,
                jaw_scale=jaw_scale,
                upper_lip_scale=upper_lip_scale,
                lower_lip_scale=lower_lip_scale,
                corner_scale=corner_scale,
            )
            cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncTimelineApply")
            try:
                if file_path:
                    audio_to_maya_scene(file_path, start_frame, fps)
                writer.write(timeline)
            except Exception:
                cmds.undoInfo(closeChunk=True)
                raise
            cmds.undoInfo(closeChunk=True)
            self._tl_status.setText(f"Applied — {len(timeline)} segments keyed.")
        except Exception as exc:
            self._tl_status.setText(f"Failed: {exc}")
        finally:
            self._set_buttons_enabled(True)

    # ------------------------------------------------------------------
    # Pose Library slots
    # ------------------------------------------------------------------

    def _on_viseme_selected(
        self,
        current: QtWidgets.QListWidgetItem | None,
        _previous: QtWidgets.QListWidgetItem | None,
    ) -> None:
        """Refresh the customised indicator when the selected viseme changes."""
        self._refresh_pose_indicator()

    def _refresh_pose_indicator(self) -> None:
        """Update the status label to show whether the current viseme has a
        custom pose or is still using the built-in default."""
        item = self._pose_list.currentItem()
        if item is None:
            self._pose_status_label.setText("")
            return
        viseme = item.text()
        if pose_library.is_customised(viseme):
            self._pose_status_label.setText(
                f"✦  {viseme}  —  custom pose saved"
            )
            self._pose_status_label.setStyleSheet("color: #2aa4ff; font-weight: bold;")
        else:
            self._pose_status_label.setText(
                f"{viseme}  —  using built-in default"
            )
            self._pose_status_label.setStyleSheet("color: grey;")

    def _on_capture_pose(self) -> None:
        """Capture the current rig pose and store it for the selected viseme."""
        item = self._pose_list.currentItem()
        if item is None:
            self._pose_msg_label.setText("Select a viseme first.")
            return
        viseme    = item.text()
        namespace = self.namespace.text().strip()
        try:
            pose = capture_current_pose(namespace)
            pose_library.set_pose(viseme, pose, save=True)
            self._pose_msg_label.setText(
                f"✔  Captured and saved pose for  {viseme}"
            )
            self._pose_msg_label.setStyleSheet("color: #5cb85c;")
            self._refresh_pose_indicator()
        except MayaPluginError as exc:
            self._pose_msg_label.setText(f"✘  {exc}")
            self._pose_msg_label.setStyleSheet("color: #d9534f;")

    def _on_reset_pose(self) -> None:
        """Reset the selected viseme to its built-in default pose."""
        item = self._pose_list.currentItem()
        if item is None:
            self._pose_msg_label.setText("Select a viseme first.")
            return
        viseme = item.text()
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Pose",
            f"Reset  '{viseme}'  to the built-in default?\n"
            "This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            pose_library.reset_pose(viseme)
            self._pose_msg_label.setText(f"✔  Reset  {viseme}  to default.")
            self._pose_msg_label.setStyleSheet("color: #5cb85c;")
            self._refresh_pose_indicator()
        except MayaPluginError as exc:
            self._pose_msg_label.setText(f"✘  {exc}")
            self._pose_msg_label.setStyleSheet("color: #d9534f;")

    def _on_reset_all_poses(self) -> None:
        """Reset every viseme to the built-in defaults after confirmation."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset All Poses",
            "Reset ALL visemes to their built-in defaults?\n"
            "All captured poses will be permanently lost.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            pose_library.reset_all()
            self._pose_msg_label.setText("✔  All visemes reset to defaults.")
            self._pose_msg_label.setStyleSheet("color: #5cb85c;")
            self._refresh_pose_indicator()
        except MayaPluginError as exc:
            self._pose_msg_label.setText(f"✘  {exc}")
            self._pose_msg_label.setStyleSheet("color: #d9534f;")

    def _on_browse_save_path(self) -> None:
        """Let the user choose a different location for the pose library JSON."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Choose Pose Library Location",
            str(pose_library.save_path),
            "JSON Files (*.json)",
        )
        if path:
            new_path = Path(path)
            pose_library.save_path = new_path
            self._save_path_edit.setText(str(new_path))
            self._pose_msg_label.setText(f"Library path set to: {new_path.name}")
            self._pose_msg_label.setStyleSheet("color: grey;")


# ---------------------------------------------------------------------------
# Utility widget
# ---------------------------------------------------------------------------

class _HSeparator(QtWidgets.QFrame):
    """Thin horizontal rule used to visually divide UI sections."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)


def createLipsyncUI() -> SunnyLipsyncDock:
    """Create/show dockable Sunny lipsync UI."""
    if MAYA_AVAILABLE and cmds.workspaceControl(SunnyLipsyncDock.WINDOW_OBJECT, exists=True):
        cmds.deleteUI(SunnyLipsyncDock.WINDOW_OBJECT)

    widget = SunnyLipsyncDock(parent=_maya_main_window())
    if MAYA_AVAILABLE:
        widget.show(dockable=True, floating=True, area="right", retain=False)
    else:
        widget.show()
    return widget


def _create_default_icon(icon_path: Path) -> None:
    """Draw a simple speech-bubble icon for shelf installation."""
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = QtGui.QPixmap(64, 64)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor(ICON_BORDER_COLOR), 3))
    painter.setBrush(QtGui.QColor(ICON_FILL_COLOR))
    painter.drawRoundedRect(QtCore.QRectF(8, 10, 48, 36), 10, 10)
    triangle = QtGui.QPolygonF(
        [QtCore.QPointF(24, 44), QtCore.QPointF(30, 56), QtCore.QPointF(36, 44)]
    )
    painter.drawPolygon(triangle)
    painter.setPen(QtGui.QPen(QtGui.QColor("white"), 3))
    painter.drawLine(18, 24, 46, 24)
    painter.drawLine(18, 32, 38, 32)
    painter.end()
    pixmap.save(str(icon_path))


def install_shelf_button() -> None:
    """Install Sunny lipsync UI launcher on current shelf."""
    if not MAYA_AVAILABLE:
        raise MayaPluginError("Shelf installation requires Maya runtime.")
    try:
        shelf_top = mel.eval("$tmp=$gShelfTopLevel")
        current_shelf = cmds.tabLayout(shelf_top, q=True, selectTab=True)

        icon_path = Path(cmds.internalVar(userAppDir=True)) / "prefs" / "icons" / "sunny_lipsync.png"
        if not icon_path.exists():
            _create_default_icon(icon_path)

        command = (
            "import importlib\n"
            "import SunnyLipsync\n"
            "importlib.reload(SunnyLipsync)\n"
            "SunnyLipsync.createLipsyncUI()"
        )
        cmds.shelfButton(
            parent=current_shelf,
            label="Sunny Lipsync",
            annotation="Open Sunny Lipsync UI",
            command=command,
            image=str(icon_path),
            sourceType="python",
        )
        om.MGlobal.displayInfo("SunnyLipsync shelf button installed.")
    except Exception as exc:
        raise MayaPluginError(f"Failed to install shelf button: {exc}") from exc


def initializePlugin(plugin_obj: Any) -> None:
    """Maya plugin entry point."""
    if not MAYA_AVAILABLE:
        raise RuntimeError("Cannot initialize plugin outside Maya.")
    plugin = om.MFnPlugin(plugin_obj, "SunnyLipsync", "1.0.0", "Any")
    node_registered = False
    try:
        plugin.registerNode(
            SunnyLipsyncNode.kNodeName,
            SunnyLipsyncNode.kNodeId,
            SunnyLipsyncNode.creator,
            SunnyLipsyncNode.initialize,
            om.MPxNode.kDependNode,  # required 5th arg; omitting causes TypeError
        )
        node_registered = True
        plugin.registerCommand(
            SunnyLipsyncCommand.kCommandName,
            SunnyLipsyncCommand.creator,
            SunnyLipsyncCommand.create_syntax,
        )
    except Exception:
        if node_registered:
            plugin.deregisterNode(SunnyLipsyncNode.kNodeId)
        raise


def uninitializePlugin(plugin_obj: Any) -> None:
    """Maya plugin exit point."""
    if not MAYA_AVAILABLE:
        return
    plugin = om.MFnPlugin(plugin_obj)
    try:
        plugin.deregisterCommand(SunnyLipsyncCommand.kCommandName)
    finally:
        plugin.deregisterNode(SunnyLipsyncNode.kNodeId)


if __name__ == "__main__":
    createLipsyncUI()
