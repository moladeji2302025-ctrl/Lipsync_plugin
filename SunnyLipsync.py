"""SunnyLipsync Maya 2027 Plugin.

Installation
------------
1. Copy ``SunnyLipsync.py`` into Maya's plug-ins directory.
2. Load it with Plug-in Manager, or run:
   ``import maya.cmds as cmds; cmds.loadPlugin('SunnyLipsync.py')``

Required Python packages (install into Maya Python)
----------------------------------------------------
``mayapy -m pip install openai-whisper pronouncing vosk``

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

from dataclasses import dataclass
from pathlib import Path
import json
import math
import re
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
        "LF_Mouth_01_LipSew_Ctrl": {"translateY": 0.5},
        "RT_Mouth_01_LipSew_Ctrl": {"translateY": 0.5},
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


@dataclass(frozen=True)
class PhonemeSegment:
    """Time span and target viseme."""

    start: float
    end: float
    viseme: str


class PhonemeDetector:
    """Phoneme detector using Whisper+CMU with Vosk fallback."""

    def __init__(self, audio_path: str, fps: float) -> None:
        self.audio_path = audio_path
        self.fps = fps

    def detect(self) -> list[tuple[float, float, str]]:
        """Return a timeline of (start_time_sec, end_time_sec, viseme_label)."""
        words = self._detect_words_whisper()
        if words is None:
            words = self._detect_words_vosk()
        if words is None:
            raise MayaPluginError(
                "No speech backend available. Install with: mayapy -m pip install openai-whisper pronouncing vosk"
            )

        timeline: list[PhonemeSegment] = []
        for start, end, word in words:
            timeline.extend(self._word_to_visemes(start, end, word))
        if not timeline:
            timeline.append(PhonemeSegment(0.0, 0.1, "REST"))
        return [(seg.start, seg.end, seg.viseme) for seg in timeline]

    def _detect_words_whisper(self) -> list[tuple[float, float, str]] | None:
        try:
            import whisper  # type: ignore[import-not-found]
        except Exception:
            return None

        try:
            model = whisper.load_model("base")
            result = model.transcribe(self.audio_path, word_timestamps=True, verbose=False)
            words: list[tuple[float, float, str]] = []
            for segment in result.get("segments", []):
                for word_data in segment.get("words", []):
                    token = str(word_data.get("word", "")).strip()
                    if not token:
                        continue
                    words.append((float(word_data["start"]), float(word_data["end"]), token))
            return words
        except Exception as exc:
            raise MayaPluginError(f"Whisper failed: {exc}") from exc

    def _detect_words_vosk(self) -> list[tuple[float, float, str]] | None:
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore[import-not-found]
        except Exception:
            return None

        model_path = Path.home() / ".cache" / "vosk" / "vosk-model-small-en-us-0.15"
        if not model_path.exists():
            raise MayaPluginError(
                f"Vosk is installed but no model found at {model_path}. Download a small English model and place it there."
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

    def _word_to_visemes(self, start: float, end: float, word: str) -> list[PhonemeSegment]:
        try:
            import pronouncing  # type: ignore[import-not-found]
        except Exception as exc:
            raise MayaPluginError("pronouncing package is required for ARPABET mapping.") from exc

        cleaned = re.sub(r"[^A-Za-z']", "", word).lower()
        duration = max(end - start, 1e-3)
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
    ) -> None:
        self.char_namespace = char_namespace.strip(":")
        self.fps = fps
        self.start_frame = start_frame
        self.smoothing = max(1, int(smoothing))
        self.overshoot = overshoot
        self.jaw_bias = jaw_bias
        self.expr_intensity = expr_intensity
        self._keyed_attrs: set[str] = set()

    @property
    def all_controls(self) -> list[str]:
        """Return all controls referenced in viseme poses."""
        controls = {ctrl for pose in VISEME_POSES.values() for ctrl in pose.keys()}
        return sorted(controls)

    def write(self, phoneme_timeline: list[tuple[float, float, str]]) -> None:
        """Convert phoneme timeline to Maya keyframes on Sunny controls."""
        if not MAYA_AVAILABLE:
            raise MayaPluginError("Maya APIs unavailable: write() must run in Maya.")
        if not phoneme_timeline:
            cmds.warning("No phonemes detected; nothing to key.")
            return

        sorted_timeline = sorted(phoneme_timeline, key=lambda item: item[0])
        start = self._to_frame(sorted_timeline[0][0])
        end = self._to_frame(sorted_timeline[-1][1])

        cmds.undoInfo(openChunk=True, chunkName="SunnyLipsyncWrite")
        try:
            self.clear_keys(start, end)
            for index, (seg_start, seg_end, viseme) in enumerate(sorted_timeline):
                start_frame = self._to_frame(seg_start)
                end_frame = max(start_frame, self._to_frame(seg_end))
                peak_frame = int((start_frame + end_frame) * 0.5)
                anticipation_frame = max(self.start_frame, start_frame - 1)

                self._key_pose(viseme, anticipation_frame, self.overshoot, "fast")
                self._key_pose(viseme, peak_frame, 1.0, "flat")
                self._key_release(viseme, end_frame, "slow")

                if index + 1 < len(sorted_timeline):
                    next_start = self._to_frame(sorted_timeline[index + 1][0])
                    if next_start - end_frame > 1:
                        self._key_pose("REST", end_frame + 1, 1.0, "auto")

            self._smooth_keys(start, end)
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
                    cmds.cutKey(target, time=(frame_start, frame_end), clear=True)

    def clear_all_keys(self) -> None:
        """Delete all keys on supported controls across the timeline."""
        if not MAYA_AVAILABLE:
            return
        min_time = int(cmds.playbackOptions(q=True, minTime=True))
        max_time = int(cmds.playbackOptions(q=True, maxTime=True))
        self.clear_keys(min_time, max_time)

    def _to_frame(self, time_seconds: float) -> int:
        return int(round(self.start_frame + (time_seconds * self.fps)))

    def _node_name(self, control: str) -> str:
        return f"{self.char_namespace}:{control}" if self.char_namespace else control

    def _scaled_value(self, control: str, attr: str, value: float, blend: float) -> float:
        scaled = value * self.expr_intensity * blend
        if control == "MD_Mouth_01_Jaw_Ctrl" and attr == "rotateX":
            scaled *= self.jaw_bias
        return scaled

    def _iter_pose(self, viseme: str, blend: float) -> Iterable[tuple[str, str, float]]:
        pose = VISEME_POSES.get(viseme, VISEME_POSES["REST"])
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
            cmds.setKeyframe(plug, time=frame, value=value)
            cmds.keyTangent(plug, time=(frame, frame), inTangentType=tangent, outTangentType=tangent)
            self._keyed_attrs.add(plug)

    def _key_release(self, viseme: str, frame: int, tangent: str) -> None:
        target_pose = VISEME_POSES.get(viseme, VISEME_POSES["REST"])
        rest_pose = VISEME_POSES["REST"]
        for control, attrs in target_pose.items():
            node = self._node_name(control)
            if not cmds.objExists(node):
                cmds.warning(f"SunnyLipsync: missing controller '{node}', skipping.")
                continue
            for attr, target_value in attrs.items():
                rest_value = rest_pose.get(control, {}).get(attr, 0.0)
                release_value = (target_value * 0.6) + (rest_value * 0.4)
                plug = f"{node}.{attr}"
                if not cmds.objExists(plug):
                    cmds.warning(f"SunnyLipsync: missing attribute '{plug}', skipping.")
                    continue
                scaled = self._scaled_value(control, attr, release_value, 1.0)
                cmds.setKeyframe(plug, time=frame, value=scaled)
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
            for t, value in smoothed:
                cmds.keyframe(plug, edit=True, time=(t, t), valueChange=value)


def audio_to_maya_scene(audio_path: str, start_frame: int, fps: float = 24.0) -> str:
    """Import audio into Maya timeline and return sound node name."""
    if not MAYA_AVAILABLE:
        raise MayaPluginError("Maya APIs unavailable: audio import must run in Maya.")
    try:
        file_path = Path(audio_path)
        if not file_path.exists():
            raise MayaPluginError(f"Audio file not found: {audio_path}")

        sound_node = cmds.sound(file=audio_path, offset=start_frame)
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
                raise RuntimeError(f"SunnyLipsyncNode compute failed: {exc}")

        @staticmethod
        def creator() -> om.MPxNode:
            return SunnyLipsyncNode()

        @staticmethod
        def initialize() -> None:
            typed_attr = om.MFnTypedAttribute()
            num_attr = om.MFnNumericAttribute()
            string_data = om.MFnStringData().create("")

            SunnyLipsyncNode.audioFilePath = typed_attr.create("audioFilePath", "afp", om.MFnData.kString, string_data)
            typed_attr.writable = True
            typed_attr.storable = True

            SunnyLipsyncNode.startFrame = num_attr.create("startFrame", "sf", om.MFnNumericData.kInt, 1)
            SunnyLipsyncNode.fps = num_attr.create("fps", "fps", om.MFnNumericData.kFloat, 24.0)
            SunnyLipsyncNode.smoothingWindow = num_attr.create("smoothingWindow", "sw", om.MFnNumericData.kInt, 3)
            SunnyLipsyncNode.blendOvershoot = num_attr.create("blendOvershoot", "bo", om.MFnNumericData.kFloat, 1.05)
            SunnyLipsyncNode.jawScaleBias = num_attr.create("jawScaleBias", "jb", om.MFnNumericData.kFloat, 1.0)
            SunnyLipsyncNode.expressionIntensity = num_attr.create("expressionIntensity", "ei", om.MFnNumericData.kFloat, 1.0)
            num_attr.setMin(0.0)
            num_attr.setMax(2.0)

            SunnyLipsyncNode.outputStatus = typed_attr.create("outputStatus", "os", om.MFnData.kString, string_data)
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
            syntax.addFlag("-f", "-file", om.MSyntax.kString)
            syntax.addFlag("-ns", "-namespace", om.MSyntax.kString)
            syntax.addFlag("-sf", "-startFrame", om.MSyntax.kLong)
            syntax.addFlag("-fps", "-fps", om.MSyntax.kDouble)
            syntax.addFlag("-sm", "-smoothing", om.MSyntax.kLong)
            syntax.addFlag("-os", "-overshoot", om.MSyntax.kDouble)
            syntax.addFlag("-jb", "-jawBias", om.MSyntax.kDouble)
            syntax.addFlag("-ei", "-exprInt", om.MSyntax.kDouble)
            syntax.addFlag("-p", "-preview", om.MSyntax.kBoolean)
            syntax.addFlag("-c", "-clear", om.MSyntax.kBoolean)
            return syntax

        def isUndoable(self) -> bool:
            return True

        def doIt(self, args: om.MArgList) -> None:
            try:
                arg_db = om.MArgDatabase(self.syntax(), args)
                clear = arg_db.flagArgumentBool("-c", 0) if arg_db.isFlagSet("-c") else False
                preview = arg_db.flagArgumentBool("-p", 0) if arg_db.isFlagSet("-p") else False
                file_path = arg_db.flagArgumentString("-f", 0) if arg_db.isFlagSet("-f") else ""
                namespace = arg_db.flagArgumentString("-ns", 0) if arg_db.isFlagSet("-ns") else ""
                start_frame = arg_db.flagArgumentInt("-sf", 0) if arg_db.isFlagSet("-sf") else 1
                fps = float(arg_db.flagArgumentDouble("-fps", 0) if arg_db.isFlagSet("-fps") else 24.0)
                smoothing = arg_db.flagArgumentInt("-sm", 0) if arg_db.isFlagSet("-sm") else 3
                overshoot = float(arg_db.flagArgumentDouble("-os", 0) if arg_db.isFlagSet("-os") else 1.05)
                jaw_bias = float(arg_db.flagArgumentDouble("-jb", 0) if arg_db.isFlagSet("-jb") else 1.0)
                expr_int = float(arg_db.flagArgumentDouble("-ei", 0) if arg_db.isFlagSet("-ei") else 1.0)

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

                detector = PhonemeDetector(file_path, fps)
                timeline = detector.detect()
                if preview:
                    for segment in timeline:
                        om.MGlobal.displayInfo(f"{segment}")
                    om.MGlobal.displayInfo(f"SunnyLipsync preview: {len(timeline)} segments")
                    return

                audio_to_maya_scene(file_path, start_frame, fps)
                writer.write(timeline)
                self._did_change_scene = True

                frame_start = writer._to_frame(timeline[0][0])
                frame_end = writer._to_frame(timeline[-1][1])
                duration = max(0.0, timeline[-1][1] - timeline[0][0])
                om.MGlobal.displayInfo(
                    f"SunnyLipsync wrote {len(timeline)} segments, frames {frame_start}-{frame_end}, duration {duration:.2f}s"
                )
            except Exception as exc:
                om.MGlobal.displayError(f"SunnyLipsync failed: {exc}")
                om.MGlobal.displayError(traceback.format_exc())
                raise

        def undoIt(self) -> None:
            if self._did_change_scene:
                cmds.undo()

        def redoIt(self) -> None:
            if self._did_change_scene:
                cmds.redo()

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


class SunnyLipsyncDock(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """Dockable PySide6 UI for Sunny lipsync generation."""

    WINDOW_OBJECT = "SunnyLipsyncWorkspaceControl"

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("SunnyLipsyncUI")
        self.setWindowTitle("Sunny Lipsync")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

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
        self.start_frame.setRange(-100000, 100000)
        self.start_frame.setValue(1)

        self.fps_combo = QtWidgets.QComboBox()
        for fps in (12, 24, 25, 30, 48, 60):
            self.fps_combo.addItem(str(fps), fps)
        self.fps_combo.setCurrentText("24")

        self.smoothing = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.smoothing.setRange(1, 10)
        self.smoothing.setValue(3)
        self.jaw_bias = self._make_float_slider(50, 200, 100)
        self.expr_int = self._make_float_slider(0, 200, 100)
        self.overshoot = self._make_float_slider(100, 130, 105)

        form = QtWidgets.QFormLayout()
        form.addRow("Namespace", self.namespace)
        form.addRow("Start Frame", self.start_frame)
        form.addRow("FPS", self.fps_combo)
        form.addRow("Smoothing", self.smoothing)
        form.addRow("Jaw Bias", self.jaw_bias)
        form.addRow("Expression Intensity", self.expr_int)
        form.addRow("Overshoot", self.overshoot)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        preview_btn = QtWidgets.QPushButton("Preview Phonemes")
        generate_btn = QtWidgets.QPushButton("Generate Lipsync")
        clear_btn = QtWidgets.QPushButton("Clear Lipsync Keys")
        preview_btn.clicked.connect(lambda: self._run(preview=True, clear=False))
        generate_btn.clicked.connect(lambda: self._run(preview=False, clear=False))
        clear_btn.clicked.connect(lambda: self._run(preview=False, clear=True))
        button_row.addWidget(preview_btn)
        button_row.addWidget(generate_btn)
        button_row.addWidget(clear_btn)
        layout.addLayout(button_row)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status = QtWidgets.QLabel("Idle")
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

    def _make_float_slider(self, min_i: int, max_i: int, value_i: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(min_i, max_i)
        slider.setValue(value_i)
        return slider

    def _browse(self) -> None:
        audio_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Audio", "", "Audio Files (*.wav *.mp3)")
        if audio_path:
            self.file_path.setText(audio_path)

    def _run(self, preview: bool, clear: bool) -> None:
        self.progress.setRange(0, 0)
        QtWidgets.QApplication.processEvents()
        try:
            kwargs: dict[str, Any] = {
                "namespace": self.namespace.text().strip(),
                "startFrame": int(self.start_frame.value()),
                "fps": float(self.fps_combo.currentData()),
                "smoothing": int(self.smoothing.value()),
                "jawBias": float(self.jaw_bias.value()) / 100.0,
                "exprInt": float(self.expr_int.value()) / 100.0,
                "overshoot": float(self.overshoot.value()) / 100.0,
                "preview": bool(preview),
                "clear": bool(clear),
            }
            if not clear:
                kwargs["file"] = self.file_path.text().strip()

            if MAYA_AVAILABLE:
                cmds.sunnyLipsync(**kwargs)
            else:
                raise MayaPluginError("UI actions require Maya runtime.")
            self.status.setText("Success")
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")
        finally:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)


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
    painter.setPen(QtGui.QPen(QtGui.QColor("#10243a"), 3))
    painter.setBrush(QtGui.QColor("#2aa4ff"))
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
    try:
        plugin.registerNode(
            SunnyLipsyncNode.kNodeName,
            SunnyLipsyncNode.kNodeId,
            SunnyLipsyncNode.creator,
            SunnyLipsyncNode.initialize,
        )
        plugin.registerCommand(
            SunnyLipsyncCommand.kCommandName,
            SunnyLipsyncCommand.creator,
            SunnyLipsyncCommand.create_syntax,
        )
    except Exception:
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
