from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from client.plugins.base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "media"
    description = "Image editing: resize, crop, filters, overlay, watermark, convert, enhance"
    version = "1.0.0"
    author = "Beta"

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._media_dir = Path(os.environ.get("MEDIA_DIR", "./media"))
        self._media_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, action: str = "info", **kw: Any) -> dict[str, Any]:
        actions = {
            "info": self._info,
            "resize": self._resize,
            "crop": self._crop,
            "rotate": self._rotate,
            "flip": self._flip,
            "brightness": self._brightness,
            "contrast": self._contrast,
            "blur": self._blur,
            "sharpen": self._sharpen,
            "grayscale": self._grayscale,
            "sepia": self._sepia,
            "invert": self._invert,
            "overlay": self._overlay,
            "watermark": self._watermark,
            "text": self._text,
            "convert": self._convert,
            "thumbnail": self._thumbnail,
            "composite": self._composite,
            "color_adjust": self._color_adjust,
            "edge_detect": self._edge_detect,
            "emboss": self._emboss,
            "posterize": self._posterize,
            "pixelate": self._pixelate,
            "mirror": self._mirror,
            "border": self._border,
            "round_corners": self._round_corners,
            "from_base64": self._from_base64,
            "to_base64": self._to_base64,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}", "available": list(actions.keys())}
        return await fn(**kw)

    def _load(self, path: str) -> Any:
        from PIL import Image, ImageFilter
        return Image.open(path)

    def _save(self, img: Any, path: str, quality: int = 90) -> str:
        if not path:
            path = str(self._media_dir / f"edit_{int(time.time())}.png")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if path.lower().endswith(('.jpg', '.jpeg')):
            img = img.convert('RGB')
            img.save(path, quality=quality, optimize=True)
        else:
            img.save(path, optimize=True)
        return path

    async def _info(self, path: str = "", b64: str = "", **kw: Any) -> dict:
        from PIL import Image
        if b64:
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
        elif path:
            img = Image.open(path)
        else:
            return {"error": "path or b64 required"}
        return {
            "format": img.format, "mode": img.mode, "size": list(img.size),
            "width": img.width, "height": img.height,
            "info": {k: str(v)[:100] for k, v in list(img.info.items())[:10]},
        }

    async def _resize(self, path: str = "", width: int = 0, height: int = 0,
                       percent: float = 0, keep_ratio: bool = True, out: str = "", **kw: Any) -> dict:
        img = self._load(path)
        if percent > 0:
            width = int(img.width * percent / 100)
            height = int(img.height * percent / 100)
        elif width and not height and keep_ratio:
            height = int(img.height * width / img.width)
        elif height and not width and keep_ratio:
            width = int(img.width * height / img.height)
        if not width or not height:
            return {"error": "width/height or percent required"}
        img = img.resize((width, height), Image.LANCZOS)
        out = self._save(img, out)
        return {"path": out, "size": [width, height]}

    async def _crop(self, path: str = "", x: int = 0, y: int = 0,
                     w: int = 0, h: int = 0, out: str = "", **kw: Any) -> dict:
        img = self._load(path)
        if not w or not h:
            return {"error": "w and h required"}
        img = img.crop((x, y, x + w, y + h))
        out = self._save(img, out)
        return {"path": out, "crop_box": [x, y, x + w, y + h]}

    async def _rotate(self, path: str = "", angle: float = 0, out: str = "", **kw: Any) -> dict:
        img = self._load(path)
        img = img.rotate(angle, expand=True, resample=Image.BICUBIC)
        out = self._save(img, out)
        return {"path": out, "angle": angle}

    async def _flip(self, path: str = "", direction: str = "horizontal", out: str = "", **kw: Any) -> dict:
        from PIL import Image
        img = self._load(path)
        if direction == "horizontal":
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif direction == "vertical":
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        out = self._save(img, out)
        return {"path": out, "direction": direction}

    async def _brightness(self, path: str = "", factor: float = 1.5, out: str = "", **kw: Any) -> dict:
        from PIL import ImageEnhance
        img = self._load(path)
        img = ImageEnhance.Brightness(img).enhance(factor)
        out = self._save(img, out)
        return {"path": out, "factor": factor}

    async def _contrast(self, path: str = "", factor: float = 1.5, out: str = "", **kw: Any) -> dict:
        from PIL import ImageEnhance
        img = self._load(path)
        img = ImageEnhance.Contrast(img).enhance(factor)
        out = self._save(img, out)
        return {"path": out, "factor": factor}

    async def _blur(self, path: str = "", radius: int = 5, out: str = "", **kw: Any) -> dict:
        from PIL import ImageFilter
        img = self._load(path)
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        out = self._save(img, out)
        return {"path": out, "radius": radius}

    async def _sharpen(self, path: str = "", factor: float = 2.0, out: str = "", **kw: Any) -> dict:
        from PIL import ImageFilter, ImageEnhance
        img = self._load(path)
        img = img.filter(ImageFilter.SHARPEN)
        if factor > 1.0:
            img = ImageEnhance.Sharpness(img).enhance(factor)
        out = self._save(img, out)
        return {"path": out, "factor": factor}

    async def _grayscale(self, path: str = "", out: str = "", **kw: Any) -> dict:
        img = self._load(path).convert("L")
        out = self._save(img, out)
        return {"path": out}

    async def _sepia(self, path: str = "", intensity: float = 1.0, out: str = "", **kw: Any) -> dict:
        import numpy as np
        img = self._load(path).convert("RGB")
        arr = np.array(img, dtype=np.float64)
        sepia = np.array([
            [0.393, 0.769, 0.189],
            [0.349, 0.686, 0.168],
            [0.272, 0.534, 0.131],
        ])
        arr = np.dot(arr, sepia.T)
        arr = np.clip(arr * intensity, 0, 255).astype(np.uint8)
        from PIL import Image
        img = Image.fromarray(arr)
        out = self._save(img, out)
        return {"path": out, "intensity": intensity}

    async def _invert(self, path: str = "", out: str = "", **kw: Any) -> dict:
        from PIL import ImageOps
        img = self._load(path)
        if img.mode == "RGBA":
            r, g, b, a = img.split()
            img = Image.merge("RGB", (r, g, b))
            img = ImageOps.invert(img)
            img.putalpha(a)
        else:
            img = ImageOps.invert(img.convert("RGB"))
        out = self._save(img, out)
        return {"path": out}

    async def _overlay(self, path: str = "", overlay_path: str = "",
                        x: int = 0, y: int = 0, opacity: float = 1.0, out: str = "", **kw: Any) -> dict:
        base = self._load(path).convert("RGBA")
        top = self._load(overlay_path).convert("RGBA")
        if opacity < 1.0:
            alpha = top.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity))
            top.putalpha(alpha)
        base.paste(top, (x, y), top)
        out = self._save(base, out)
        return {"path": out, "position": [x, y]}

    async def _watermark(self, path: str = "", text: str = "WATERMARK",
                          position: str = "bottom-right", opacity: float = 0.3,
                          font_size: int = 36, out: str = "", **kw: Any) -> dict:
        from PIL import Image, ImageDraw, ImageFont, ImageEnhance
        base = self._load(path).convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        positions = {
            "top-left": (10, 10), "top-right": (base.width - tw - 10, 10),
            "center": ((base.width - tw) // 2, (base.height - th) // 2),
            "bottom-left": (10, base.height - th - 10),
            "bottom-right": (base.width - tw - 10, base.height - th - 10),
        }
        pos = positions.get(position, positions["bottom-right"])
        alpha_val = int(255 * opacity)
        draw.text(pos, text, fill=(255, 255, 255, alpha_val), font=font)
        result = Image.alpha_composite(base, overlay)
        out = self._save(result, out)
        return {"path": out, "text": text, "position": position}

    async def _text(self, path: str = "", text: str = "Hello",
                     x: int = 50, y: int = 50, font_size: int = 48,
                     color: str = "#FFFFFF", out: str = "", **kw: Any) -> dict:
        from PIL import Image, ImageDraw, ImageFont
        img = self._load(path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        r = int(color[1:3], 16) if color.startswith("#") else 255
        g = int(color[3:5], 16) if color.startswith("#") else 255
        b = int(color[5:7], 16) if color.startswith("#") else 255
        draw.text((x, y), text, fill=(r, g, b, 255), font=font)
        result = Image.alpha_composite(img, overlay)
        out = self._save(result, out)
        return {"path": out}

    async def _convert(self, path: str = "", fmt: str = "PNG", out: str = "", **kw: Any) -> dict:
        img = self._load(path)
        if fmt.upper() in ("JPG", "JPEG"):
            img = img.convert("RGB")
        if not out:
            base = Path(path).stem
            out = str(self._media_dir / f"{base}.{fmt.lower()}")
        if fmt.upper() in ("JPG", "JPEG"):
            img.save(out, quality=95)
        else:
            img.save(out)
        return {"path": out, "format": fmt}

    async def _thumbnail(self, path: str = "", size: int = 256, out: str = "", **kw: Any) -> dict:
        img = self._load(path)
        img.thumbnail((size, size), Image.LANCZOS)
        out = self._save(img, out)
        return {"path": out, "size": list(img.size)}

    async def _composite(self, paths: list[str] = None, cols: int = 0, out: str = "", **kw: Any) -> dict:
        from PIL import Image
        if not paths:
            return {"error": "paths list required"}
        imgs = [Image.open(p).convert("RGB") for p in paths]
        if not cols:
            cols = min(len(imgs), 3)
        rows = (len(imgs) + cols - 1) // cols
        w = max(i.width for i in imgs)
        h = max(i.height for i in imgs)
        canvas = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
        for idx, img in enumerate(imgs):
            r, c = divmod(idx, cols)
            canvas.paste(img, (c * w, r * h))
        out = self._save(canvas, out)
        return {"path": out, "grid": [cols, rows], "count": len(imgs)}

    async def _color_adjust(self, path: str = "", hue: int = 0, saturation: int = 0,
                             warmth: int = 0, out: str = "", **kw: Any) -> dict:
        from PIL import ImageEnhance
        img = self._load(path).convert("RGB")
        if saturation != 0:
            img = ImageEnhance.Color(img).enhance(1 + saturation / 100)
        if warmth > 0:
            import numpy as np
            arr = np.array(img, dtype=np.float64)
            arr[:, :, 0] = np.clip(arr[:, :, 0] + warmth, 0, 255)
            arr[:, :, 2] = np.clip(arr[:, :, 2] - warmth, 0, 255)
            from PIL import Image as PILImage
            img = PILImage.fromarray(arr.astype(np.uint8))
        elif warmth < 0:
            import numpy as np
            arr = np.array(img, dtype=np.float64)
            arr[:, :, 0] = np.clip(arr[:, :, 0] + warmth, 0, 255)
            arr[:, :, 2] = np.clip(arr[:, :, 2] - warmth, 0, 255)
            from PIL import Image as PILImage
            img = PILImage.fromarray(arr.astype(np.uint8))
        out = self._save(img, out)
        return {"path": out}

    async def _edge_detect(self, path: str = "", out: str = "", **kw: Any) -> dict:
        from PIL import ImageFilter
        img = self._load(path).convert("L").filter(ImageFilter.FIND_EDGES)
        out = self._save(img, out)
        return {"path": out}

    async def _emboss(self, path: str = "", out: str = "", **kw: Any) -> dict:
        from PIL import ImageFilter
        img = self._load(path).filter(ImageFilter.EMBOSS)
        out = self._save(img, out)
        return {"path": out}

    async def _posterize(self, path: str = "", bits: int = 3, out: str = "", **kw: Any) -> dict:
        from PIL import ImageOps
        img = self._load(path).convert("RGB")
        img = ImageOps.posterize(img, bits)
        out = self._save(img, out)
        return {"path": out, "bits": bits}

    async def _pixelate(self, path: str = "", block_size: int = 10, out: str = "", **kw: Any) -> dict:
        from PIL import Image
        img = self._load(path).convert("RGB")
        small = img.resize((img.width // block_size, img.height // block_size), Image.BILINEAR)
        img = small.resize(img.size, Image.NEAREST)
        out = self._save(img, out)
        return {"path": out, "block_size": block_size}

    async def _mirror(self, path: str = "", axis: str = "horizontal", out: str = "", **kw: Any) -> dict:
        from PIL import Image
        img = self._load(path).convert("RGBA")
        w, h = img.size
        mirrored = Image.new("RGBA", (w * 2 if axis == "horizontal" else w, h * 2 if axis == "vertical" else h))
        if axis == "horizontal":
            mirrored.paste(img, (0, 0))
            mirrored.paste(img.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
        else:
            mirrored.paste(img, (0, 0))
            mirrored.paste(img.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
        out = self._save(mirrored, out)
        return {"path": out}

    async def _border(self, path: str = "", size: int = 10, color: str = "#000000", out: str = "", **kw: Any) -> dict:
        from PIL import Image, ImageOps
        img = self._load(path)
        r = int(color[1:3], 16) if color.startswith("#") else 0
        g = int(color[3:5], 16) if color.startswith("#") else 0
        b = int(color[5:7], 16) if color.startswith("#") else 0
        img = ImageOps.expand(img, border=size, fill=(r, g, b))
        out = self._save(img, out)
        return {"path": out}

    async def _round_corners(self, path: str = "", radius: int = 20, out: str = "", **kw: Any) -> dict:
        from PIL import Image, ImageDraw
        img = self._load(path).convert("RGBA")
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
        img.putalpha(mask)
        out = self._save(img, out)
        return {"path": out, "radius": radius}

    async def _from_base64(self, b64: str = "", out: str = "", fmt: str = "PNG", **kw: Any) -> dict:
        if not b64:
            return {"error": "b64 required"}
        data = base64.b64decode(b64)
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if not out:
            out = str(self._media_dir / f"import_{int(time.time())}.{fmt.lower()}")
        img.save(out)
        return {"path": out, "size": list(img.size), "format": img.format}

    async def _to_base64(self, path: str = "", fmt: str = "PNG", quality: int = 85, **kw: Any) -> dict:
        img = self._load(path)
        buf = io.BytesIO()
        if fmt.upper() in ("JPG", "JPEG"):
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality)
        else:
            img.save(buf, format=fmt)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"b64": b64, "size": len(b64), "format": fmt}
