"""Master loopback audio capture and tactical audio cue perception.

Implements WASAPI loopback audio stream acquisition via sounddevice,
calculating real-time RMS energy levels, peak decibel metrics, and
log-mel spectrograms for multimodal game state introspection.
"""

from __future__ import annotations

import contextlib
import logging
import platform
import sys
import threading
from collections import deque
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"


class WASAPIAudioCapturer:
    """WASAPI master loopback audio capturer capturing output sounds from games."""

    def __init__(
        self,
        sample_rate: int = 44100,
        channels: int = 2,
        buffer_duration_sec: float = 10.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_duration_sec = buffer_duration_sec

        self._lock = threading.Lock()
        self._max_samples = int(sample_rate * buffer_duration_sec)
        self._ring_buffer: deque[npt.NDArray[np.float32]] = deque()
        self._total_buffered_samples = 0

        self._stream: Any = None
        self._is_running = False
        self._device_index: int | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the audio capture stream is currently active."""
        return self._is_running

    @property
    def is_recording(self) -> bool:
        """Return True if the audio capture stream is currently active (alias for is_running)."""
        return self._is_running

    def _find_wasapi_loopback_device(self) -> int | None:
        """Find the default WASAPI output device for loopback capture."""
        try:
            import sounddevice as sd  # type: ignore[import-untyped]

            devices = sd.query_devices()
            hostapis = sd.query_hostapis()

            # Look for Windows WASAPI host API
            wasapi_api_indices = {
                idx for idx, api in enumerate(hostapis) if "WASAPI" in api["name"]
            }

            # Check default output device first
            default_out = sd.default.device[1]
            if default_out is not None and default_out >= 0:
                dev = devices[default_out]
                if dev.get("hostapi") in wasapi_api_indices:
                    return int(default_out)

            # Search for first WASAPI output device with >0 output channels
            for idx, dev in enumerate(devices):
                has_channels = dev.get("max_output_channels", 0) > 0
                if dev.get("hostapi") in wasapi_api_indices and has_channels:
                    return idx

            return None
        except Exception as exc:
            logger.warning("Error querying audio devices: %s", exc)
            return None

    def start(self) -> bool:
        """Start non-blocking loopback audio stream capture."""
        if self._is_running:
            return True

        try:
            import sounddevice as sd
        except ImportError:
            logger.warning("sounddevice is not installed. Audio capture disabled.")
            return False

        self._device_index = self._find_wasapi_loopback_device()
        if self._device_index is None:
            logger.warning("No WASAPI loopback device detected. Audio capture disabled.")
            return False

        def audio_callback(
            indata: npt.NDArray[np.float32],
            frames: int,
            time_info: Any,
            status: Any,
        ) -> None:
            if status:
                logger.debug("Audio stream status flag: %s", status)
            with self._lock:
                chunk = indata.copy()
                self._ring_buffer.append(chunk)
                self._total_buffered_samples += frames

                # Trim buffer if exceeding maximum duration
                while self._total_buffered_samples > self._max_samples and self._ring_buffer:
                    popped = self._ring_buffer.popleft()
                    self._total_buffered_samples -= len(popped)

        try:
            extra_settings = None
            if IS_WINDOWS:
                with contextlib.suppress(Exception):
                    extra_settings = sd.WasapiSettings(loopback=True)

            self._stream = sd.InputStream(
                device=self._device_index,
                channels=self.channels,
                samplerate=self.sample_rate,
                dtype="float32",
                callback=audio_callback,
                extra_settings=extra_settings,
            )
            self._stream.start()
            self._is_running = True
            logger.info("WASAPI loopback audio stream started on device %d", self._device_index)
            return True
        except Exception as exc:
            logger.warning("Failed starting audio stream: %s", exc)
            self._is_running = False
            self._stream = None
            return False

    def stop(self) -> None:
        """Stop audio stream capture."""
        if not self._is_running:
            return
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._is_running = False
        logger.info("WASAPI loopback audio stream stopped")

    def get_recent_audio(self, duration_sec: float = 1.0) -> npt.NDArray[np.float32]:
        """Retrieve recent audio samples as a float32 numpy array.

        Returns:
            Numpy array of shape (samples, channels) with values normalized to [-1.0, 1.0].
        """
        required_samples = int(self.sample_rate * duration_sec)
        with self._lock:
            if not self._ring_buffer:
                return np.zeros((required_samples, self.channels), dtype=np.float32)

            stacked = np.concatenate(list(self._ring_buffer), axis=0)

        if len(stacked) >= required_samples:
            return stacked[-required_samples:].copy()

        # Zero pad if insufficient history
        pad_size = required_samples - len(stacked)
        padding = np.zeros((pad_size, self.channels), dtype=np.float32)
        return np.concatenate([padding, stacked], axis=0)

    def get_audio_energy(self, duration_sec: float = 0.5) -> float:
        """Calculate Root Mean Square (RMS) energy of recent audio."""
        samples = self.get_recent_audio(duration_sec=duration_sec)
        rms = float(np.sqrt(np.mean(samples**2)))
        return rms

    def get_peak_db(self, duration_sec: float = 0.5) -> float:
        """Calculate peak decibel level relative to full scale (dBFS)."""
        samples = self.get_recent_audio(duration_sec=duration_sec)
        peak = float(np.max(np.abs(samples)))
        if peak <= 1e-7:
            return -100.0
        return float(20.0 * np.log10(peak))

    def detect_tactical_cue(
        self,
        threshold_db: float = -30.0,
        duration_sec: float = 0.5,
    ) -> bool:
        """Detect whether sound levels exceed a given decibel threshold."""
        peak_db = self.get_peak_db(duration_sec=duration_sec)
        return peak_db >= threshold_db

    def compute_spectrogram(
        self,
        duration_sec: float = 1.0,
        n_fft: int = 1024,
        hop_length: int = 512,
    ) -> npt.NDArray[np.float32]:
        """Compute short-time Fourier transform (STFT) magnitude spectrogram."""
        try:
            from scipy import signal  # type: ignore[import-untyped]
        except ImportError:
            return np.zeros((n_fft // 2 + 1, 10), dtype=np.float32)

        samples = self.get_recent_audio(duration_sec=duration_sec)
        mono = np.mean(samples, axis=1)

        _f, _t, zxx = signal.stft(
            mono,
            fs=self.sample_rate,
            nperseg=n_fft,
            noverlap=n_fft - hop_length,
        )
        result: npt.NDArray[np.float32] = np.asarray(np.abs(zxx), dtype=np.float32)
        return result

    def get_recent_events(self) -> list[dict[str, Any]]:
        """Retrieve recent tactical audio events and threshold cue telemetry."""
        if not self._is_running:
            return []
        events: list[dict[str, Any]] = []
        try:
            energy = self.get_audio_energy(duration_sec=0.5)
            peak_db = self.get_peak_db(duration_sec=0.5)
            if peak_db > -35.0:
                events.append(
                    {
                        "event": "tactical_sound_cue",
                        "peak_db": round(peak_db, 2),
                        "energy_rms": round(energy, 4),
                    }
                )
        except Exception as exc:
            logger.debug("Failed analyzing recent audio events: %s", exc)
        return events

    def close(self) -> None:
        """Release audio stream and clear memory."""
        self.stop()
        with self._lock:
            self._ring_buffer.clear()
            self._total_buffered_samples = 0
