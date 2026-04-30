from __future__ import annotations

from typing import IO

import face_recognition
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

_MAX_DETECTION_PX = 1000  # longest side; face detection accuracy is fine at this size


def _resize_for_detection(image_array: np.ndarray) -> np.ndarray:
    """Downscale to _MAX_DETECTION_PX on the longest side before face detection.

    Face detection speed is roughly O(pixels), so halving the longest side cuts
    detection time by ~4×.  The 128-d face encoding is size-invariant once the
    face region is located, so accuracy is not affected.
    """
    h, w = image_array.shape[:2]
    longest = max(h, w)
    if longest <= _MAX_DETECTION_PX:
        return image_array
    scale = _MAX_DETECTION_PX / longest
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    pil_img = Image.fromarray(image_array)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
    return np.array(pil_img)


def encode_faces_from_array(image_array: np.ndarray) -> list[np.ndarray]:
    small = _resize_for_detection(image_array)
    face_locations = face_recognition.face_locations(small)
    return face_recognition.face_encodings(small, face_locations)


def encode_faces_from_file(file_obj: IO[bytes]) -> list[np.ndarray]:
    image_array = face_recognition.load_image_file(file_obj)
    return encode_faces_from_array(image_array)


def encode_faces_from_path(image_path: str) -> list[np.ndarray]:
    image_array = face_recognition.load_image_file(image_path)
    return encode_faces_from_array(image_array)


def encode_primary_face_from_file(file_obj: IO[bytes]) -> np.ndarray | None:
    image_array = face_recognition.load_image_file(file_obj)
    small = _resize_for_detection(image_array)
    face_locations = face_recognition.face_locations(small)
    if not face_locations:
        return None

    encodings = face_recognition.face_encodings(small, face_locations)
    if not encodings:
        return None

    def area(loc):
        top, right, bottom, left = loc
        return max(0, bottom - top) * max(0, right - left)

    largest_index = max(range(len(face_locations)), key=lambda idx: area(face_locations[idx]))
    return encodings[largest_index]


def encode_single_face_from_file(file_obj: IO[bytes]) -> np.ndarray | None:
    """Return the only face encoding in the image; reject group shots.

    Returns None when zero faces are found.
    Raises ValueError when multiple faces are found.
    """
    image_array = face_recognition.load_image_file(file_obj)
    small = _resize_for_detection(image_array)
    face_locations = face_recognition.face_locations(small)
    if not face_locations:
        return None
    if len(face_locations) != 1:
        raise ValueError("Multiple faces detected")
    encodings = face_recognition.face_encodings(small, face_locations)
    if not encodings:
        return None
    return encodings[0]
