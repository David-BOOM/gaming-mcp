"""Hardware-accelerated screen capture engine for gaming-mcp.

Implements zero-copy DirectX 11 / DXGI Desktop Duplication ctypes wrapper
for Windows 11 with microsecond frame acquisition latency, backed by an
MSS multi-monitor cross-platform fallback capturer, Set-of-Marks coordinate
grid overlays, and 64-bit dHash perceptual delta gating.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import ctypes
import logging
import platform
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Literal

from PIL import Image

from gaming_mcp.core.exceptions import CaptureError, DXGICaptureError
from gaming_mcp.io.vision import PerceptualGater
from gaming_mcp.utils.image import draw_set_of_marks_grid, encode_image, image_to_base64

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"

# COM / Win32 Types and Constants
if IS_WINDOWS:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        """Win32 GUID representation."""

        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_byte * 8),
        ]

        def __init__(self, guid_str: str) -> None:
            super().__init__()
            import uuid

            u = uuid.UUID(guid_str)
            self.Data1 = u.time_low
            self.Data2 = u.time_mid
            self.Data3 = u.time_hi_version
            for i, b in enumerate(u.bytes[8:]):
                self.Data4[i] = b

    class DXGI_SAMPLE_DESC(ctypes.Structure):  # noqa: N801
        _fields_ = [("Count", wintypes.UINT), ("Quality", wintypes.UINT)]

    class D3D11_TEXTURE2D_DESC(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("Width", wintypes.UINT),
            ("Height", wintypes.UINT),
            ("MipLevels", wintypes.UINT),
            ("ArraySize", wintypes.UINT),
            ("Format", ctypes.c_int),
            ("SampleDesc", DXGI_SAMPLE_DESC),
            ("Usage", ctypes.c_int),
            ("BindFlags", wintypes.UINT),
            ("CPUAccessFlags", wintypes.UINT),
            ("MiscFlags", wintypes.UINT),
        ]

    class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("pData", ctypes.c_void_p),
            ("RowPitch", wintypes.UINT),
            ("DepthPitch", wintypes.UINT),
        ]

    class DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("LastPresentTime", wintypes.LARGE_INTEGER),
            ("LastMouseUpdateTime", wintypes.LARGE_INTEGER),
            ("AccumulatedFrames", wintypes.UINT),
            ("RectsCoalesced", wintypes.BOOL),
            ("ProtectedContentMaskedOut", wintypes.BOOL),
            ("PointerPositionValid", wintypes.BOOL),
            ("PointerPosition", wintypes.POINT),
            ("PointerShapeBufferSize", wintypes.UINT),
            ("PointerShapeUpdatedTime", wintypes.LARGE_INTEGER),
        ]

    IID_IDXGIFactory1 = GUID("770aae78-f26f-4dba-a829-253c83d1b387")
    IID_IDXGIOutput1 = GUID("00cddea8-939b-4b83-a340-a685226666cc")
    IID_ID3D11Texture2D = GUID("6f15aaf2-d208-4e89-9ab4-489535d34f9c")

    DXGI_ERROR_ACCESS_LOST = 0x887A0026
    DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
    DXGI_ERROR_INVALID_CALL = 0x887A0001


_thread_local = threading.local()
_screen_executor_instance: concurrent.futures.ThreadPoolExecutor | None = None
_screen_executor_lock = threading.Lock()


def get_screen_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return singleton dedicated worker thread pool for screen capture."""
    global _screen_executor_instance
    with _screen_executor_lock:
        if _screen_executor_instance is None:
            _screen_executor_instance = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="gaming_mcp_screen_worker"
            )
        return _screen_executor_instance


def shutdown_screen_executor() -> None:
    """Shutdown dedicated screen worker thread pool."""
    global _screen_executor_instance
    with _screen_executor_lock:
        if _screen_executor_instance is not None:
            _screen_executor_instance.shutdown(wait=False)
            _screen_executor_instance = None


def attach_thread_to_input_desktop() -> bool:
    """Attach current thread to active input desktop to grant capture permissions."""
    if not IS_WINDOWS:
        return True
    try:
        user32 = ctypes.windll.user32
        if getattr(_thread_local, "attached", False):
            return True
        h_desk = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_desk:
            res = bool(user32.SetThreadDesktop(h_desk))
            if res:
                _thread_local.attached = True
                _thread_local.h_desk = h_desk
            else:
                user32.CloseDesktop(h_desk)
            return res
        return False
    except Exception as exc:
        logger.debug("Failed attaching thread to input desktop: %s", exc)
        return False


class DXGIScreenCapturer:
    """Zero-copy Windows Desktop Duplication capturer via Direct3D 11 and DXGI 1.2."""

    def __init__(self, monitor_index: int = 0) -> None:
        self.monitor_index = monitor_index
        self._available = False
        self._p_device: ctypes.c_void_p | None = None
        self._p_context: ctypes.c_void_p | None = None
        self._p_duplication: ctypes.c_void_p | None = None
        self._p_staging: ctypes.c_void_p | None = None
        self._staging_width = 0
        self._staging_height = 0
        self._last_frame: Image.Image | None = None

        if IS_WINDOWS:
            get_screen_executor().submit(self._initialize).result()

    @property
    def is_available(self) -> bool:
        return self._available and self._p_duplication is not None

    def _initialize(self) -> bool:
        """Initialize Direct3D 11 device and output duplication interface."""
        if not IS_WINDOWS:
            return False

        attach_thread_to_input_desktop()
        self._cleanup()

        try:
            dxgi = ctypes.windll.dxgi
            d3d11 = ctypes.windll.d3d11

            p_factory = ctypes.c_void_p()
            hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(p_factory))
            if hr != 0 or not p_factory.value:
                logger.warning("CreateDXGIFactory1 failed: hr=%s", hex(hr & 0xFFFFFFFF))
                return False

            vtable_factory = ctypes.cast(
                ctypes.cast(p_factory, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            enum_adapters = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
            )(vtable_factory[12])

            p_adapter = ctypes.c_void_p()
            hr = enum_adapters(p_factory, 0, ctypes.byref(p_adapter))
            if hr != 0 or not p_adapter.value:
                return False

            vtable_adapter = ctypes.cast(
                ctypes.cast(p_adapter, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            enum_outputs = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
            )(vtable_adapter[7])

            p_output = ctypes.c_void_p()
            hr = enum_outputs(p_adapter, self.monitor_index, ctypes.byref(p_output))
            if hr != 0 or not p_output.value:
                return False

            p_dev = ctypes.c_void_p()
            p_ctx = ctypes.c_void_p()
            feature_level = ctypes.c_uint()
            hr = d3d11.D3D11CreateDevice(
                p_adapter,
                0,
                None,
                0x20,
                None,
                0,
                7,
                ctypes.byref(p_dev),
                ctypes.byref(feature_level),
                ctypes.byref(p_ctx),
            )
            if hr != 0 or not p_dev.value:
                return False

            vtable_output = ctypes.cast(
                ctypes.cast(p_output, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            qi_out = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )(vtable_output[0])

            p_out1 = ctypes.c_void_p()
            hr = qi_out(p_output, ctypes.byref(IID_IDXGIOutput1), ctypes.byref(p_out1))
            if hr != 0 or not p_out1.value:
                return False

            vtable_out1 = ctypes.cast(
                ctypes.cast(p_out1, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            duplicate_output = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            )(vtable_out1[22])

            p_dupl = ctypes.c_void_p()
            hr = duplicate_output(p_out1, p_dev, ctypes.byref(p_dupl))
            if hr != 0 or not p_dupl.value:
                logger.warning("DuplicateOutput failed: hr=%s", hex(hr & 0xFFFFFFFF))
                return False

            self._p_device = p_dev
            self._p_context = p_ctx
            self._p_duplication = p_dupl
            self._available = True
            logger.info("DXGI Desktop Duplication initialized on monitor %d", self.monitor_index)
            return True
        except Exception as exc:
            logger.warning("DXGI initialization raised exception: %s", exc)
            self._cleanup()
            return False

    def capture(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
        """Capture screen frame via DXGI Desktop Duplication in dedicated worker thread."""
        return get_screen_executor().submit(self._capture_internal, region).result()

    def _capture_internal(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
        attach_thread_to_input_desktop()
        if not self.is_available and not self._initialize():
            raise DXGICaptureError("DXGI Desktop Duplication is unavailable")

        assert self._p_device is not None
        assert self._p_context is not None
        assert self._p_duplication is not None

        vtable_dupl = ctypes.cast(
            ctypes.cast(self._p_duplication, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )
        acquire_next_frame = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(DXGI_OUTDUPL_FRAME_INFO),
            ctypes.POINTER(ctypes.c_void_p),
        )(vtable_dupl[8])
        release_frame = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable_dupl[14])

        frame_info = DXGI_OUTDUPL_FRAME_INFO()
        p_resource = ctypes.c_void_p()

        hr = acquire_next_frame(
            self._p_duplication, 100, ctypes.byref(frame_info), ctypes.byref(p_resource)
        )
        unsigned_hr = hr & 0xFFFFFFFF

        if unsigned_hr == DXGI_ERROR_WAIT_TIMEOUT:
            if self._last_frame is not None:
                if region:
                    x, y, w, h = region
                    return self._last_frame.crop((x, y, x + w, y + h))
                return self._last_frame.copy()
            time.sleep(0.01)
            hr = acquire_next_frame(
                self._p_duplication, 100, ctypes.byref(frame_info), ctypes.byref(p_resource)
            )
            unsigned_hr = hr & 0xFFFFFFFF

        if unsigned_hr in (DXGI_ERROR_ACCESS_LOST, DXGI_ERROR_INVALID_CALL):
            logger.warning("DXGI surface lost (hr=%s), reinitializing...", hex(unsigned_hr))
            if not self._initialize():
                raise DXGICaptureError(f"DXGI surface lost and reinit failed: {hex(unsigned_hr)}")
            return self._capture_internal(region=region)

        if hr != 0 or not p_resource.value:
            raise DXGICaptureError(f"AcquireNextFrame failed with hr={hex(unsigned_hr)}")

        try:
            vtable_res = ctypes.cast(
                ctypes.cast(p_resource, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            qi_res = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )(vtable_res[0])
            p_tex = ctypes.c_void_p()
            hr = qi_res(p_resource, ctypes.byref(IID_ID3D11Texture2D), ctypes.byref(p_tex))
            if hr != 0 or not p_tex.value:
                raise DXGICaptureError("QueryInterface for ID3D11Texture2D failed")

            vtable_tex = ctypes.cast(
                ctypes.cast(p_tex, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_desc = ctypes.WINFUNCTYPE(
                None, ctypes.c_void_p, ctypes.POINTER(D3D11_TEXTURE2D_DESC)
            )(vtable_tex[10])
            desc = D3D11_TEXTURE2D_DESC()
            get_desc(p_tex, ctypes.byref(desc))

            # Maintain reusable staging texture
            if (
                self._p_staging is None
                or self._staging_width != desc.Width
                or self._staging_height != desc.Height
            ):
                staging_desc = D3D11_TEXTURE2D_DESC(
                    Width=desc.Width,
                    Height=desc.Height,
                    MipLevels=1,
                    ArraySize=1,
                    Format=desc.Format,
                    SampleDesc=DXGI_SAMPLE_DESC(Count=1, Quality=0),
                    Usage=3,
                    BindFlags=0,
                    CPUAccessFlags=0x20000,
                    MiscFlags=0,
                )
                vtable_dev = ctypes.cast(
                    ctypes.cast(self._p_device, ctypes.POINTER(ctypes.c_void_p)).contents,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                create_tex = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.POINTER(D3D11_TEXTURE2D_DESC),
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p),
                )(vtable_dev[5])
                p_stg = ctypes.c_void_p()
                hr = create_tex(
                    self._p_device, ctypes.byref(staging_desc), None, ctypes.byref(p_stg)
                )
                if hr != 0 or not p_stg.value:
                    raise DXGICaptureError("Creating staging texture failed")
                self._p_staging = p_stg
                self._staging_width = desc.Width
                self._staging_height = desc.Height

            vtable_ctx = ctypes.cast(
                ctypes.cast(self._p_context, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            copy_resource = ctypes.WINFUNCTYPE(
                None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )(vtable_ctx[47])
            map_fn = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE),
            )(vtable_ctx[14])
            unmap_fn = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)(
                vtable_ctx[15]
            )

            copy_resource(self._p_context, self._p_staging, p_tex)

            mapped = D3D11_MAPPED_SUBRESOURCE()
            hr = map_fn(self._p_context, self._p_staging, 0, 1, 0, ctypes.byref(mapped))
            if hr != 0 or not mapped.pData:
                raise DXGICaptureError("Mapping staging texture failed")

            raw_buffer = ctypes.string_at(mapped.pData, mapped.RowPitch * desc.Height)
            unmap_fn(self._p_context, self._p_staging, 0)

            img = Image.frombytes(
                "RGBA",
                (desc.Width, desc.Height),
                raw_buffer,
                "raw",
                "BGRA",
                mapped.RowPitch,
                1,
            )
            self._last_frame = img

            if region:
                x, y, w, h = region
                img_w, img_h = img.size
                x1 = max(0, min(x, img_w - 1))
                y1 = max(0, min(y, img_h - 1))
                x2 = max(x1 + 1, min(x + w, img_w))
                y2 = max(y1 + 1, min(y + h, img_h))
                return img.crop((x1, y1, x2, y2))

            return img
        finally:
            release_frame(self._p_duplication)

    def _cleanup(self) -> None:
        self._p_duplication = None
        self._p_staging = None
        self._p_device = None
        self._p_context = None
        self._available = False

    def close(self) -> None:
        """Release all allocated DirectX resources and COM pointers."""
        with contextlib.suppress(Exception):
            get_screen_executor().submit(self._cleanup).result(timeout=1.0)
        self._last_frame = None


class MSSScreenCapturer:
    """Cross-platform screen capturer powered by MSS."""

    def __init__(self, monitor_index: int = 1) -> None:
        self.monitor_index = monitor_index
        self._sct: Any = None

    def _get_sct(self) -> Any:
        if self._sct is None:
            import mss

            self._sct = mss.MSS()
        return self._sct

    def capture(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
        """Capture screen or region using MSS in dedicated worker thread."""
        return get_screen_executor().submit(self._capture_internal, region).result()

    def _capture_internal(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
        attach_thread_to_input_desktop()
        sct = self._get_sct()

        monitors = sct.monitors
        idx = min(max(1, self.monitor_index), len(monitors) - 1)
        monitor = monitors[idx]

        if region is not None:
            rx, ry, rw, rh = region
            target_rect = {
                "left": monitor["left"] + rx,
                "top": monitor["top"] + ry,
                "width": rw,
                "height": rh,
            }
        else:
            target_rect = monitor

        try:
            raw = sct.grab(target_rect)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception as exc:
            raise CaptureError(f"MSS capture failed: {exc}") from exc

    def _close_internal(self) -> None:
        if self._sct is not None:
            with contextlib.suppress(Exception):
                self._sct.close()
            self._sct = None

    def close(self) -> None:
        """Close MSS instance and release GDI handles."""
        with contextlib.suppress(Exception):
            get_screen_executor().submit(self._close_internal).result(timeout=1.0)


class CompositeScreenCapturer:
    """Unified capturer combining DXGI zero-copy capture, MSS fallback, and perceptual gating."""

    def __init__(
        self,
        prefer_dxgi: bool = True,
        monitor_index: int = 0,
        dhash_threshold: int = 3,
    ) -> None:
        self.prefer_dxgi = prefer_dxgi and IS_WINDOWS
        self.monitor_index = monitor_index
        self.gater = PerceptualGater(threshold=dhash_threshold)

        self._dxgi: DXGIScreenCapturer | None = None
        self._mss: MSSScreenCapturer | None = None

        if self.prefer_dxgi:
            self._dxgi = DXGIScreenCapturer(monitor_index=monitor_index)
        self._mss = MSSScreenCapturer(monitor_index=max(1, monitor_index + 1))

    @property
    def active_backend(self) -> str:
        """Return the active capture backend identifier ('dxgi' or 'mss')."""
        if self._dxgi is not None and self._dxgi.is_available:
            return "dxgi"
        return "mss"

    def capture(
        self,
        region: tuple[int, int, int, int] | None = None,
        apply_som: bool = False,
        som_spacing: int = 100,
    ) -> Image.Image:
        """Acquire an image from the primary display with optional SoM grid overlay."""
        img: Image.Image | None = None

        if self._dxgi is not None and self._dxgi.is_available:
            try:
                img = self._dxgi.capture(region=region)
            except Exception as exc:
                logger.warning("DXGI capture failed, falling back to MSS: %s", exc)

        if img is None:
            assert self._mss is not None
            img = self._mss.capture(region=region)

        if apply_som:
            img = draw_set_of_marks_grid(img, spacing=som_spacing)

        return img

    def capture_with_gating(
        self,
        region: tuple[int, int, int, int] | None = None,
        mask_rects: Sequence[tuple[int, int, int, int]] | None = None,
        image_format: Literal["jpeg", "png"] = "jpeg",
        quality: int = 85,
        apply_som: bool = False,
        som_spacing: int = 100,
    ) -> tuple[Image.Image | None, str | None, bool, int, int]:
        """Capture frame with perceptual dHash delta evaluation.

        Returns:
            Tuple of (image, base64_payload, is_static, current_hash, hamming_distance).
            If frame is static, image and base64_payload are None to save transmission tokens.
        """
        raw_img = self.capture(region=region, apply_som=False)

        is_static, current_hash, hamming_dist = self.gater.evaluate(
            raw_img,
            mask_rects=list(mask_rects) if mask_rects else None,
        )

        if is_static:
            return None, None, True, current_hash, hamming_dist

        if apply_som:
            raw_img = draw_set_of_marks_grid(raw_img, spacing=som_spacing)

        encoded_bytes = encode_image(raw_img, image_format=image_format, quality=quality)
        b64_str = image_to_base64(encoded_bytes)

        return raw_img, b64_str, False, current_hash, hamming_dist

    def close(self) -> None:
        """Release underlying DXGI and MSS resources."""
        if self._dxgi is not None:
            self._dxgi.close()
            self._dxgi = None
        if self._mss is not None:
            self._mss.close()
            self._mss = None
        self.gater.reset()
