"""Unit and mock tests for WASAPI loopback audio capturer."""

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from gaming_mcp.io.audio import WASAPIAudioCapturer


def test_audio_capturer_initialization() -> None:
    """WASAPIAudioCapturer must initialize with default audio parameters."""
    capturer = WASAPIAudioCapturer(sample_rate=44100, channels=2, buffer_duration_sec=2.0)
    assert not capturer.is_running
    assert capturer.sample_rate == 44100
    assert capturer.channels == 2


def test_audio_buffer_and_metrics() -> None:
    """Audio buffer metrics (RMS, peak dB, tactical cue) must calculate correctly."""
    capturer = WASAPIAudioCapturer(sample_rate=1000, channels=1, buffer_duration_sec=2.0)

    # Inject a 1-second sine wave at 440 Hz with amplitude 0.5
    t = np.linspace(0, 1.0, 1000, endpoint=False, dtype=np.float32)
    sine_wave = (0.5 * np.sin(2 * np.pi * 10 * t)).reshape(-1, 1).astype(np.float32)

    with capturer._lock:
        capturer._ring_buffer.append(sine_wave)
        capturer._total_buffered_samples = 1000

    recent = capturer.get_recent_audio(duration_sec=0.5)
    assert recent.shape == (500, 1)

    # RMS of a sine wave with amplitude A is A / sqrt(2) ~= 0.5 / 1.414 ~= 0.353
    rms = capturer.get_audio_energy(duration_sec=1.0)
    assert 0.3 < rms < 0.4

    # Peak dB for amplitude 0.5 is 20 * log10(0.5) ~= -6.02 dB
    peak_db = capturer.get_peak_db(duration_sec=1.0)
    assert -7.0 < peak_db < -5.0

    # Tactical cue detection
    assert capturer.detect_tactical_cue(threshold_db=-10.0, duration_sec=1.0)
    assert not capturer.detect_tactical_cue(threshold_db=0.0, duration_sec=1.0)

    # Spectrogram computation
    spec = capturer.compute_spectrogram(duration_sec=1.0, n_fft=128, hop_length=64)
    assert isinstance(spec, np.ndarray)
    assert spec.ndim == 2
    assert spec.shape[0] == 65  # n_fft // 2 + 1

    capturer.close()
    assert capturer._total_buffered_samples == 0


def test_audio_capturer_silence_defaults() -> None:
    """Empty buffer must return silent zero arrays and low decibel floor."""
    capturer = WASAPIAudioCapturer(sample_rate=1000, channels=2)
    recent = capturer.get_recent_audio(duration_sec=0.2)
    assert recent.shape == (200, 2)
    assert np.all(recent == 0.0)

    rms = capturer.get_audio_energy(duration_sec=0.2)
    assert rms == 0.0

    peak_db = capturer.get_peak_db(duration_sec=0.2)
    assert peak_db == -100.0

    capturer.close()


def test_audio_stream_start_stop_mock() -> None:
    """Capturer start, callback ingestion, buffer trimming, and stop lifecycle."""
    capturer = WASAPIAudioCapturer(sample_rate=1000, channels=2, buffer_duration_sec=0.5)
    # buffer duration 0.5s = 500 samples max

    mock_stream = MagicMock()
    callback_holder = []

    def mock_input_stream(**kwargs: Any) -> MagicMock:
        callback_holder.append(kwargs["callback"])
        return mock_stream

    with (
        patch.object(capturer, "_find_wasapi_loopback_device", return_value=1),
        patch("sounddevice.InputStream", side_effect=mock_input_stream),
    ):
        assert capturer.start()
        assert capturer.is_running
        # Calling start again while running returns True immediately
        assert capturer.start()

        # Ingest two chunks via the captured callback
        cb = callback_holder[0]
        chunk1 = np.ones((400, 2), dtype=np.float32) * 0.2
        chunk2 = np.ones((300, 2), dtype=np.float32) * 0.4
        cb(chunk1, 400, None, None)
        cb(chunk2, 300, None, "overflow")

        # Total samples 700 exceeds max_samples 500, ring buffer must have trimmed chunk1
        assert capturer._total_buffered_samples <= 500

        capturer.stop()
        assert not capturer.is_running
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()


def test_find_wasapi_loopback_device_mock() -> None:
    """Device discovery must prioritize WASAPI devices with output channels."""
    capturer = WASAPIAudioCapturer()

    mock_devices = [
        {"name": "Dummy In", "hostapi": 0, "max_output_channels": 0},
        {"name": "Speakers", "hostapi": 1, "max_output_channels": 2},
    ]
    mock_hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]

    with (
        patch("sounddevice.query_devices", return_value=mock_devices),
        patch("sounddevice.query_hostapis", return_value=mock_hostapis),
        patch("sounddevice.default.device", [0, 1]),
    ):
        dev_idx = capturer._find_wasapi_loopback_device()
        assert dev_idx == 1
