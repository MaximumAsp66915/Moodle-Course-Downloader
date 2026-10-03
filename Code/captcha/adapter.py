"""Bridge between CW Radar's ``CAPTCHA_SOLVER`` hook and your trained char model.

Enable in ``.env``::

    CAPTCHA_SOLVER=cw_radar_bot.captcha.adapter:solve_captcha
    CAPTCHA_MODEL_PATH=cw_radar_bot/captcha/char_model.pt

Differences from calling ``CaptchaSolver.predict`` directly:

* The image is decoded in memory (no temp file round-trip).
* Preprocessing mirrors ``predict_with_confidence`` step for step, but never
  writes ``debug_crops/`` (avoids disk I/O race conditions in async workers).
* The model loads once lazily and inference is serialised behind a threading lock.
* Contains the standalone SingleCharCNN architecture and valley-based segmentation
  pipeline directly to eliminate runtime coupling with offline training scripts.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import torch
import torch.nn as nn
from torchvision import transforms

logger = logging.getLogger(__name__)

CAPTCHA_LENGTH = 5
MIN_VALLEY_GAP = 3
CHAR_PADDING = 2

# Constrain PyTorch thread usage to prevent CPU starvation on production servers
torch.set_num_threads(1)

# Path resolution: check explicit env var, fallback to local char_model.pt
REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_MODEL = Path(__file__).resolve().parent / "char_model.pt"

_configured = os.environ.get("CAPTCHA_MODEL_PATH", "").strip()
if _configured:
    _candidate = Path(_configured)
    MODEL_PATH = _candidate if _candidate.is_absolute() else REPO_ROOT / _candidate
else:
    MODEL_PATH = LOCAL_MODEL

_lock = threading.Lock()
_solver: CaptchaSolver | None = None


# --------------------------------------------------------------------------
# Neural Network Architecture (SingleCharCNN)
# --------------------------------------------------------------------------
class SingleCharCNN(nn.Module):
    """Deep convolutional classifier designed for single 32x32 character glyphs."""

    def __init__(self, num_classes: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.MaxPool2d(2),

            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((2, 2)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512 * 2 * 2, 1024),
            nn.BatchNorm1d(1024),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(1024, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


# --------------------------------------------------------------------------
# Inference Engine & Model Wrapper
# --------------------------------------------------------------------------
class CaptchaSolver:
    """Wraps model checkpoint loading, preprocessing transforms, and crop inference."""

    def __init__(self, model_file: str):
        self.device = torch.device("cpu")

        checkpoint = torch.load(model_file, map_location=self.device)
        self.char_labels: list[str] = checkpoint["char_labels"]
        self.img_size: int = checkpoint["img_size"]

        self.model = SingleCharCNN(num_classes=len(self.char_labels)).to(self.device)
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.eval()

        self.transform = transforms.Compose([
            transforms.Grayscale(num_output_channels=1),
            transforms.Resize((self.img_size, self.img_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5], std=[0.5]),
        ])

    @torch.no_grad()
    def _classify_crop(self, crop_gray: np.ndarray) -> tuple[str, float]:
        """Classifies a single cropped character image."""
        pil_img = Image.fromarray(crop_gray)
        tensor = self.transform(pil_img).unsqueeze(0).to(self.device)
        logits = self.model(tensor)
        probs = torch.softmax(logits, dim=1)
        conf, idx = probs.max(dim=1)
        return self.char_labels[idx.item()], conf.item()


# --------------------------------------------------------------------------
# Image Preprocessing and Valley-based Segmentation
# --------------------------------------------------------------------------
def preprocess(image_bytes: bytes) -> np.ndarray:
    """Same filtering as training-time gentle preprocessing: bilateral denoise + Otsu threshold."""
    img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Captcha bytes are not a decodable image.")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
    _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def get_ink_density_profile(gray: np.ndarray) -> np.ndarray:
    """Calculates column-wise foreground pixel sum for valley detection."""
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 25, 10,
    )
    binary = cv2.medianBlur(binary, 3)
    return np.sum(binary > 0, axis=0)


def find_split_points_by_valleys(profile: np.ndarray, width: int, n_chars: int) -> list[int] | None:
    """Finds optimal character splitting boundaries based on vertical ink valleys."""
    expected_char_width = width / n_chars
    split_points = []

    for i in range(1, n_chars):
        target_x = int(i * expected_char_width)
        search_radius = int(expected_char_width * 0.3)
        lo = max(0, target_x - search_radius)
        hi = min(width, target_x + search_radius)

        window = profile[lo:hi]
        if len(window) == 0:
            return None

        min_idx = int(np.argmin(window))
        split_points.append(lo + min_idx)

    for a, b in zip(split_points, split_points[1:]):
        if b - a < MIN_VALLEY_GAP:
            return None

    return split_points


def segment_image(thresh: np.ndarray, n_chars: int = CAPTCHA_LENGTH) -> list[tuple[int, int]]:
    """Segments the binary image into column ranges using valleys with fixed-width fallback."""
    width = thresh.shape[1]
    profile = get_ink_density_profile(thresh)
    split_points = find_split_points_by_valleys(profile, width, n_chars)

    if split_points is None:
        boundaries = [int(i * width / n_chars) for i in range(n_chars + 1)]
    else:
        boundaries = [0] + split_points + [width]

    return [(boundaries[i], boundaries[i + 1]) for i in range(n_chars)]


def crop_character(thresh: np.ndarray, x_start: int, x_end: int) -> np.ndarray:
    """Extracts a bounded character crop with horizontal padding."""
    x_start = max(0, x_start - CHAR_PADDING)
    x_end = min(thresh.shape[1], x_end + CHAR_PADDING)
    return thresh[:, x_start:x_end]


# --------------------------------------------------------------------------
# Public Interface
# --------------------------------------------------------------------------
def _load() -> CaptchaSolver:
    """Initializes and returns the singleton CaptchaSolver instance."""
    global _solver
    if _solver is None:
        target = MODEL_PATH if MODEL_PATH.is_file() else LOCAL_MODEL
        if not target.is_file():
            raise FileNotFoundError(f"Captcha model not found at {MODEL_PATH} or {LOCAL_MODEL}")
        _solver = CaptchaSolver(str(target))
        logger.info("Captcha model loaded from %s", target)
    return _solver


def solve_captcha(image_bytes: bytes) -> str:
    """Decodes, segments, and predicts the 5-character string from raw CAPTCHA image bytes."""
    thresh = preprocess(image_bytes)
    with _lock:
        solver = _load()
        chars: list[str] = []
        for x_start, x_end in segment_image(thresh, CAPTCHA_LENGTH):
            crop = crop_character(thresh, x_start, x_end)
            chars.append("?" if crop.size == 0 else solver._classify_crop(crop)[0])

    predicted = "".join(chars)
    logger.info("Captcha solved by SingleCharCNN: %s", predicted)
    return predicted
