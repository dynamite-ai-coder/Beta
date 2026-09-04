from __future__ import annotations

import asyncio
import base64
import json
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
    name = "video"
    description = "Video editing: cut, merge, effects, audio, convert, extract, speed, watermark"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._video_dir = Path(os.environ.get("VIDEO_DIR", "./videos"))
        self._video_dir.mkdir(parents=True, exist_ok=True)
        self._tmp = Path(tempfile.mkdtemp(prefix="beta_vid_"))
        self._recording = False
        self._frames_dir: Path | None = None
        self._frame_count = 0

    async def execute(self, action: str = "info", **kw: Any) -> dict[str, Any]:
        actions = {
            "info": self._info, "trim": self._trim, "cut": self._cut,
            "concat": self._concat, "merge": self._concat,
            "speed": self._speed, "reverse": self._reverse,
            "resize": self._resize, "crop": self._crop,
            "rotate": self._rotate, "flip": self._flip,
            "audio_extract": self._audio_extract, "audio_replace": self._audio_replace,
            "audio_mix": self._audio_mix, "mute": self._mute,
            "subtitle": self._subtitle, "watermark": self._watermark,
            "screenshot": self._screenshot, "to_gif": self._to_gif,
            "convert": self._convert, "compress": self._compress,
            "extract_frames": self._extract_frames, "frames_to_video": self._frames_to_video,
            "fade": self._fade, "blur": self._blur,
            "start_recording": self._start_rec, "stop_recording": self._stop_rec,
            "record_frame": self._record_frame,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    def _run_ffmpeg(self, args: list[str], timeout: int = 120) -> dict:
        try:
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {"success": r.returncode == 0, "stderr": r.stderr[:2000] if r.stderr else ""}
        except subprocess.TimeoutExpired:
            return {"error": "FFmpeg timed out"}
        except FileNotFoundError:
            return {"error": "FFmpeg not installed"}

    async def _info(self, path: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        r = self._run_ffmpeg(["-i", path, "-f", "null", "-"])
        info_r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=15,
        )
        if info_r.returncode == 0:
            data = json.loads(info_r.stdout)
            fmt = data.get("format", {})
            streams = data.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), {})
            audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
            return {
                "duration": float(fmt.get("duration", 0)),
                "size_bytes": int(fmt.get("size", 0)),
                "bitrate": int(fmt.get("bit_rate", 0)),
                "format": fmt.get("format_name", ""),
                "video": {"codec": video.get("codec_name", ""), "width": video.get("width", 0),
                          "height": video.get("height", 0), "fps": video.get("r_frame_rate", "")},
                "audio": {"codec": audio.get("codec_name", ""), "sample_rate": audio.get("sample_rate", 0),
                          "channels": audio.get("channels", 0)} if audio else None,
            }
        return {"error": "ffprobe failed"}

    async def _trim(self, path: str = "", start: float = 0, end: float = 0, out: str = "", **kw: Any) -> dict:
        if not path or not end:
            return {"error": "path and end required"}
        out = out or str(self._video_dir / f"trim_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-ss", str(start), "-to", str(end),
                               "-c", "copy", "-avoid_negative_ts", "make_zero", out])
        return {"path": out, "start": start, "end": end, **r}

    async def _cut(self, **kw: Any) -> dict:
        return await self._trim(**kw)

    async def _concat(self, paths: list[str] = None, out: str = "", **kw: Any) -> dict:
        if not paths or len(paths) < 2:
            return {"error": "at least 2 paths required"}
        out = out or str(self._video_dir / f"concat_{int(time.time())}.mp4")
        list_file = self._tmp / "concat.txt"
        list_file.write_text("\n".join(f"file '{p}'" for p in paths))
        r = self._run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", out])
        return {"path": out, "inputs": len(paths), **r}

    async def _speed(self, path: str = "", factor: float = 2.0, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"speed_{int(time.time())}.mp4")
        atempo = f"atempo={factor}" if 0.5 <= factor <= 2.0 else f"atempo={min(max(factor, 0.5), 2.0)}"
        r = self._run_ffmpeg(["-i", path, "-filter_complex",
                               f"[0:v]setpts={1/factor}*PTS[v];[0:a]{atempo}[a]",
                               "-map", "[v]", "-map", "[a]", out])
        return {"path": out, "factor": factor, **r}

    async def _reverse(self, path: str = "", out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"reverse_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-vf", "reverse", "-af", "areverse", out])
        return {"path": out, **r}

    async def _resize(self, path: str = "", width: int = 0, height: int = 0, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"resize_{int(time.time())}.mp4")
        dims = f"{width}:{height}" if width and height else (f"{width}:-2" if width else f"-2:{height}")
        r = self._run_ffmpeg(["-i", path, "-vf", f"scale={dims}", "-c:a", "copy", out])
        return {"path": out, "size": [width, height], **r}

    async def _crop(self, path: str = "", x: int = 0, y: int = 0, w: int = 0, h: int = 0, out: str = "", **kw: Any) -> dict:
        if not path or not w or not h:
            return {"error": "path, w, h required"}
        out = out or str(self._video_dir / f"crop_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-vf", f"crop={w}:{h}:{x}:{y}", "-c:a", "copy", out])
        return {"path": out, "crop": [x, y, w, h], **r}

    async def _rotate(self, path: str = "", angle: int = 90, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"rot_{int(time.time())}.mp4")
        transpose = {90: "1", 180: "2", 270: "3"}.get(angle, "1")
        r = self._run_ffmpeg(["-i", path, "-vf", f"transpose={transpose}", "-c:a", "copy", out])
        return {"path": out, "angle": angle, **r}

    async def _flip(self, path: str = "", axis: str = "horizontal", out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"flip_{int(time.time())}.mp4")
        vf = "hflip" if axis == "horizontal" else "vflip"
        r = self._run_ffmpeg(["-i", path, "-vf", vf, "-c:a", "copy", out])
        return {"path": out, **r}

    async def _audio_extract(self, path: str = "", out: str = "", fmt: str = "mp3", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"audio_{int(time.time())}.{fmt}")
        r = self._run_ffmpeg(["-i", path, "-vn", "-acodec", "copy" if fmt == "aac" else "libmp3lame", out])
        return {"path": out, **r}

    async def _audio_replace(self, path: str = "", audio: str = "", out: str = "", **kw: Any) -> dict:
        if not path or not audio:
            return {"error": "path and audio required"}
        out = out or str(self._video_dir / f"newaudio_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-i", audio, "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0", out])
        return {"path": out, **r}

    async def _audio_mix(self, path: str = "", audio: str = "", volume: float = 1.0, out: str = "", **kw: Any) -> dict:
        if not path or not audio:
            return {"error": "path and audio required"}
        out = out or str(self._video_dir / f"mix_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-i", audio,
                               "-filter_complex", f"[1:a]volume={volume}[a];[0:a][a]amix=inputs=2:duration=first[out]",
                               "-map", "0:v", "-map", "[out]", out])
        return {"path": out, **r}

    async def _mute(self, path: str = "", out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"mute_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-an", "-c:v", "copy", out])
        return {"path": out, **r}

    async def _subtitle(self, path: str = "", text: str = "", out: str = "", font_size: int = 24, **kw: Any) -> dict:
        if not path or not text:
            return {"error": "path and text required"}
        out = out or str(self._video_dir / f"sub_{int(time.time())}.mp4")
        escaped = text.replace("'", "\\'").replace(":", "\\:")
        r = self._run_ffmpeg(["-i", path, "-vf",
                               f"drawtext=text='{escaped}':fontsize={font_size}:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-th-30",
                               "-c:a", "copy", out])
        return {"path": out, **r}

    async def _watermark(self, path: str = "", image: str = "", position: str = "bottom-right", out: str = "", **kw: Any) -> dict:
        if not path or not image:
            return {"error": "path and image required"}
        out = out or str(self._video_dir / f"wm_{int(time.time())}.mp4")
        pos_map = {
            "top-left": "10:10", "top-right": "main_w-overlay_w-10:10",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
            "bottom-left": "10:main_h-overlay_h-10", "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10",
        }
        pos = pos_map.get(position, pos_map["bottom-right"])
        r = self._run_ffmpeg(["-i", path, "-i", image,
                               "-filter_complex", f"[1:v]format=rgba[wm];[0:v][wm]overlay={pos}[out]",
                               "-map", "[out]", "-map", "0:a?", out])
        return {"path": out, **r}

    async def _screenshot(self, path: str = "", time_sec: float = 0, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"frame_{int(time.time())}.jpg")
        r = self._run_ffmpeg(["-i", path, "-ss", str(time_sec), "-frames:v", "1", out])
        return {"path": out, **r}

    async def _to_gif(self, path: str = "", start: float = 0, duration: float = 3, fps: int = 15, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"anim_{int(time.time())}.gif")
        r = self._run_ffmpeg(["-ss", str(start), "-t", str(duration), "-i", path,
                               "-vf", f"fps={fps},scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                               out], timeout=60)
        return {"path": out, "duration": duration, **r}

    async def _convert(self, path: str = "", fmt: str = "mp4", out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"conv_{int(time.time())}.{fmt}")
        r = self._run_ffmpeg(["-i", path, "-c:v", "libx264", "-c:a", "aac", out])
        return {"path": out, **r}

    async def _compress(self, path: str = "", quality: int = 28, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"comp_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-c:v", "libx264", "-crf", str(quality), "-preset", "fast", "-c:a", "aac", out])
        return {"path": out, "crf": quality, **r}

    async def _extract_frames(self, path: str = "", fps: int = 1, out_dir: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out_dir = out_dir or str(self._video_dir / f"frames_{int(time.time())}")
        os.makedirs(out_dir, exist_ok=True)
        r = self._run_ffmpeg(["-i", path, "-vf", f"fps={fps}", f"{out_dir}/frame_%06d.jpg"])
        frames = len(list(Path(out_dir).glob("*.jpg"))) if Path(out_dir).exists() else 0
        return {"dir": out_dir, "frames": frames, "fps": fps, **r}

    async def _frames_to_video(self, frames_dir: str = "", fps: int = 15, out: str = "", **kw: Any) -> dict:
        if not frames_dir:
            return {"error": "frames_dir required"}
        out = out or str(self._video_dir / f"vid_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-framerate", str(fps), "-i", f"{frames_dir}/frame_%06d.jpg",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", out])
        return {"path": out, **r}

    async def _fade(self, path: str = "", fade_in: float = 1, fade_out: float = 1, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"fade_{int(time.time())}.mp4")
        vf = []
        if fade_in > 0:
            vf.append(f"fade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            info = await self._info(path=path)
            dur = info.get("duration", 10)
            vf.append(f"fade=t=out:st={dur - fade_out}:d={fade_out}")
        r = self._run_ffmpeg(["-i", path, "-vf", ",".join(vf), "-c:a", "copy", out])
        return {"path": out, **r}

    async def _blur(self, path: str = "", strength: int = 5, out: str = "", **kw: Any) -> dict:
        if not path:
            return {"error": "path required"}
        out = out or str(self._video_dir / f"blur_{int(time.time())}.mp4")
        r = self._run_ffmpeg(["-i", path, "-vf", f"boxblur={strength}:{strength}", "-c:a", "copy", out])
        return {"path": out, **r}

    async def _start_rec(self, fps: int = 10, **kw: Any) -> dict:
        if self._recording:
            return {"error": "Already recording"}
        self._frames_dir = Path(tempfile.mkdtemp(prefix="beta_vidrec_"))
        self._frame_count = 0
        self._recording = True
        self._rec_fps = max(1, min(fps, 30))
        return {"status": "recording", "fps": self._rec_fps}

    async def _stop_rec(self, out: str = "", **kw: Any) -> dict:
        if not self._recording:
            return {"error": "Not recording"}
        self._recording = False
        frames_dir = self._frames_dir
        count = self._frame_count
        fps = getattr(self, "_rec_fps", 10)
        out = out or str(self._video_dir / f"rec_{int(time.time())}.mp4")
        if count == 0:
            return {"error": "No frames"}
        r = self._run_ffmpeg(["-framerate", str(fps), "-i", f"{frames_dir}/frame_%06d.jpg",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", out])
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)
        return {"path": out, "frames": count, "duration": round(count / fps, 1), **r}

    async def _record_frame(self, b64_data: str = "", **kw: Any) -> dict:
        if not self._recording:
            return {"error": "Not recording"}
        if not b64_data:
            return {"error": "b64_data required"}
        frame_path = self._frames_dir / f"frame_{self._frame_count:06d}.jpg"
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(base64.b64decode(b64_data)))
            img = img.resize((640, 480), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            frame_path.write_bytes(buf.getvalue())
        except Exception:
            frame_path.write_bytes(base64.b64decode(b64_data))
        self._frame_count += 1
        return {"frame": self._frame_count}
