from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "videorec"
    description = "Record browser activity as MP4/WebM video"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._output_dir = Path(os.environ.get("VIDEO_DIR", "./videos"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._browser_worker = None
        self._recording = False
        self._frames_dir: Path | None = None
        self._frame_count = 0

    def set_browser(self, worker: Any) -> None:
        self._browser_worker = worker

    async def execute(self, action: str = "start", **kw: Any) -> dict[str, Any]:
        actions = {
            "start": self._start,
            "stop": self._stop,
            "capture_frame": self._capture_frame,
            "status": self._status,
            "make_video": self._make_video,
            "screenshot_video": self._screenshot_video,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    async def _start(self, fps: int = 5, **kw: Any) -> dict:
        if self._recording:
            return {"error": "Already recording"}

        self._frames_dir = Path(tempfile.mkdtemp(prefix="beta_video_"))
        self._frame_count = 0
        self._recording = True
        self._fps = max(1, min(fps, 30))

        return {"status": "recording", "fps": self._fps, "frames_dir": str(self._frames_dir)}

    async def _stop(self, **kw: Any) -> dict:
        if not self._recording:
            return {"error": "Not recording"}

        self._recording = False
        frames_dir = self._frames_dir
        frame_count = self._frame_count
        fps = getattr(self, "_fps", 5)

        if not frames_dir or frame_count == 0:
            return {"error": "No frames captured"}

        output = self._output_dir / f"rec_{int(time.time())}.mp4"
        success = await asyncio.to_thread(self._encode_video, str(frames_dir), str(output), fps)

        try:
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)
        except Exception:
            pass

        self._frames_dir = None
        self._frame_count = 0

        if success:
            size = output.stat().st_size if output.exists() else 0
            return {
                "status": "done",
                "path": str(output),
                "filename": output.name,
                "frames": frame_count,
                "fps": fps,
                "duration_seconds": round(frame_count / fps, 1),
                "size_bytes": size,
            }
        return {"error": "Video encoding failed"}

    async def _capture_frame(self, **kw: Any) -> dict:
        if not self._recording:
            return {"error": "Not recording - call start first"}
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}

        b64 = await self._browser_worker.take_screenshot()
        if not b64 or not self._frames_dir:
            return {"error": "Screenshot failed"}

        frame_path = self._frames_dir / f"frame_{self._frame_count:06d}.jpg"
        img_bytes = base64.b64decode(b64)

        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_bytes))
            img = img.resize((640, 480), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            frame_path.write_bytes(buf.getvalue())
        except ImportError:
            frame_path.write_bytes(img_bytes)

        self._frame_count += 1
        return {"frame": self._frame_count, "path": str(frame_path)}

    async def _status(self, **kw: Any) -> dict:
        return {
            "recording": self._recording,
            "frames": self._frame_count,
            "fps": getattr(self, "_fps", 5),
            "has_ffmpeg": self._check_ffmpeg(),
        }

    async def _make_video(self, frames_dir: str = "", output: str = "", fps: int = 5, **kw: Any) -> dict:
        if not frames_dir:
            return {"error": "frames_dir required"}
        if not output:
            output = str(self._output_dir / f"video_{int(time.time())}.mp4")

        success = await asyncio.to_thread(self._encode_video, frames_dir, output, fps)
        if success:
            size = Path(output).stat().st_size if Path(output).exists() else 0
            return {"path": output, "size_bytes": size, "fps": fps}
        return {"error": "Encoding failed"}

    async def _screenshot_video(self, duration: int = 5, fps: int = 2, name: str = "", **kw: Any) -> dict:
        if not self._browser_worker or not self._browser_worker.is_ready:
            return {"error": "Browser not ready"}

        frames_dir = Path(tempfile.mkdtemp(prefix="beta_ssvid_"))
        frame_count = 0
        interval = 1.0 / fps

        for _ in range(duration * fps):
            b64 = await self._browser_worker.take_screenshot()
            if b64:
                frame_path = frames_dir / f"frame_{frame_count:06d}.jpg"
                img_bytes = base64.b64decode(b64)
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(img_bytes))
                    img = img.resize((640, 480), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=80)
                    frame_path.write_bytes(buf.getvalue())
                except ImportError:
                    frame_path.write_bytes(img_bytes)
                frame_count += 1
            await asyncio.sleep(interval)

        filename = name or f"screenshots_{int(time.time())}.mp4"
        if not filename.endswith(".mp4"):
            filename += ".mp4"
        output = self._output_dir / filename

        success = await asyncio.to_thread(self._encode_video, str(frames_dir), str(output), fps)

        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)

        if success and output.exists():
            return {
                "path": str(output),
                "filename": filename,
                "frames": frame_count,
                "duration_seconds": duration,
                "size_bytes": output.stat().st_size,
            }
        return {"error": "Video creation failed"}

    def _check_ffmpeg(self) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _encode_video(self, frames_dir: str, output: str, fps: int) -> bool:
        frames_path = Path(frames_dir)
        frames = sorted(frames_path.glob("frame_*.jpg")) or sorted(frames_path.glob("frame_*.png"))
        if not frames:
            return False

        try:
            cmd = [
                "ffmpeg", "-y", "-framerate", str(fps),
                "-i", str(frames_path / "frame_%06d.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "fast", "-crf", "23",
                output,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            return result.returncode == 0 and Path(output).exists()
        except Exception as e:
            logger.error("ffmpeg encode error: %s", e)
            return False
