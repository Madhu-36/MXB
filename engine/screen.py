import io
import asyncio
import traceback
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtCore import QBuffer, QIODevice
from thefuzz import fuzz
from utils.logger import log

class ScreenVision:
    """
    Screen Awareness & Vision Engine for MXB.
    Provides fast screen capture, Windows native OCR, text localization,
    and visual coordinate mapping for UI elements.
    """

    def __init__(self):
        self._ocr_engine = None
        self._init_ocr()

    def _init_ocr(self):
        try:
            import winrt.windows.media.ocr as ocr
            self._ocr_engine = ocr.OcrEngine.try_create_from_user_profile_languages()
            log.info("ScreenVision: Windows Native OCR engine initialized.")
        except Exception as e:
            log.warning(f"ScreenVision: Could not initialize Windows OCR: {e}")
            self._ocr_engine = None

    def capture_screen_image(self) -> Image.Image | None:
        """
        Captures the primary screen as a PIL Image.
        Uses Qt's primary screen grabber (always active and hardware-accelerated).
        """
        try:
            app = QApplication.instance()
            if not app:
                return None
            screen = QGuiApplication.primaryScreen()
            if not screen:
                return None

            pix = screen.grabWindow(0)
            if pix.isNull():
                return None

            qimg = pix.toImage()
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            qimg.save(buf, "PNG")
            png_bytes = bytes(buf.data())
            buf.close()

            return Image.open(io.BytesIO(png_bytes))
        except Exception as e:
            log.error(f"ScreenVision: Screen capture failed: {e}")
            return None

    def capture_screen_png_bytes(self) -> bytes | None:
        """Returns PNG bytes of the current desktop screen."""
        try:
            app = QApplication.instance()
            if not app:
                return None
            screen = QGuiApplication.primaryScreen()
            if not screen:
                return None

            pix = screen.grabWindow(0)
            if pix.isNull():
                return None

            qimg = pix.toImage()
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            qimg.save(buf, "PNG")
            data = bytes(buf.data())
            buf.close()
            return data
        except Exception as e:
            log.error(f"ScreenVision: PNG bytes capture failed: {e}")
            return None

    def capture_roi(self, x: int, y: int, width: int, height: int) -> Image.Image | None:
        """Captures a specific Region of Interest (ROI) from the screen as a PIL Image."""
        full_img = self.capture_screen_image()
        if not full_img:
            return None
        try:
            w, h = full_img.size
            crop_x1 = max(0, min(w - 1, int(x)))
            crop_y1 = max(0, min(h - 1, int(y)))
            crop_x2 = max(crop_x1 + 1, min(w, crop_x1 + int(width)))
            crop_y2 = max(crop_y1 + 1, min(h, crop_y1 + int(height)))
            return full_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        except Exception as e:
            log.error(f"ScreenVision: ROI capture failed: {e}")
            return None

    def read_roi_text(self, x: int, y: int, width: int, height: int) -> str:
        """Extracts text via OCR strictly within a designated screen bounding box."""
        roi_img = self.capture_roi(x, y, width, height)
        if not roi_img:
            return ""
        try:
            buf = io.BytesIO()
            roi_img.save(buf, format="PNG")
            words = self.ocr_screen_words(buf.getvalue())
            return " ".join([w["text"] for w in words]).strip()
        except Exception as e:
            log.error(f"ScreenVision: ROI text recognition failed: {e}")
            return ""

    async def _async_ocr(self, png_bytes: bytes) -> list[dict]:
        """Runs Windows Native OCR asynchronously on PNG bytes."""
        if not self._ocr_engine or not png_bytes:
            return []

        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.storage.streams as streams

        stream = streams.InMemoryRandomAccessStream()
        dw = streams.DataWriter(stream)
        dw.write_bytes(png_bytes)
        await dw.store_async()
        stream.seek(0)

        decoder = await imaging.BitmapDecoder.create_async(stream)
        soft_bmp = await decoder.get_software_bitmap_async()

        res = await self._ocr_engine.recognize_async(soft_bmp)
        extracted = []
        for line in res.lines:
            for word in line.words:
                bb = word.bounding_rect
                extracted.append({
                    "text": word.text,
                    "x": int(bb.x),
                    "y": int(bb.y),
                    "w": int(bb.width),
                    "h": int(bb.height),
                    "center_x": int(bb.x + bb.width / 2),
                    "center_y": int(bb.y + bb.height / 2),
                })
        return extracted

    def get_screen_words(self) -> list[dict]:
        """Captures screen and returns all detected words with bounding boxes."""
        png_bytes = self.capture_screen_png_bytes()
        if not png_bytes:
            return []
        try:
            return asyncio.run(self._async_ocr(png_bytes))
        except Exception as e:
            log.error(f"ScreenVision: OCR processing error: {e}")
            return []

    def read_screen_text(self) -> str:
        """Returns all visible text across the active display as a single formatted string."""
        words = self.get_screen_words()
        if not words:
            return "No text could be detected on screen."
        lines_text = " ".join([w["text"] for w in words])
        return lines_text

    def find_text_coordinates(self, query: str) -> tuple[int, int] | None:
        """
        Locates a target phrase or word on screen using fuzzy matching.
        Returns the (x, y) center coordinates of the best match, or None if not found.
        """
        query = query.lower().strip()
        words = self.get_screen_words()
        if not words:
            return None

        # 1. Exact match pass
        for w in words:
            if query == w["text"].lower().strip():
                log.info(f"ScreenVision: Found exact match '{w['text']}' at ({w['center_x']}, {w['center_y']})")
                return w["center_x"], w["center_y"]

        # 2. Multi-word phrase search in consecutive words
        query_words = query.split()
        if len(query_words) > 1:
            for i in range(len(words) - len(query_words) + 1):
                window_phrase = " ".join(words[i + j]["text"].lower() for j in range(len(query_words)))
                ratio = fuzz.ratio(query, window_phrase)
                if ratio > 80:
                    first = words[i]
                    last = words[i + len(query_words) - 1]
                    center_x = int((first["x"] + last["x"] + last["w"]) / 2)
                    center_y = int((first["y"] + last["y"] + last["h"]) / 2)
                    log.info(f"ScreenVision: Found phrase '{query}' (~{ratio}%) at ({center_x}, {center_y})")
                    return center_x, center_y

        # 3. Fuzzy match single word pass
        best_match = None
        best_score = 0
        for w in words:
            score = fuzz.ratio(query, w["text"].lower())
            if score > best_score and score >= 75:
                best_score = score
                best_match = (w["center_x"], w["center_y"])

        if best_match:
            log.info(f"ScreenVision: Found fuzzy match '{query}' (score {best_score}) at {best_match}")
            return best_match

        log.warning(f"ScreenVision: Could not find '{query}' on screen.")
        return None
