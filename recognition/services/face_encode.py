from __future__ import annotations

from typing import IO

import face_recognition
import numpy as np


def encode_faces_from_array(image_array) -> list[np.ndarray]:
    face_locations = face_recognition.face_locations(image_array)
    return face_recognition.face_encodings(image_array, face_locations)


def encode_faces_from_file(file_obj: IO[bytes]) -> list[np.ndarray]:
    image_array = face_recognition.load_image_file(file_obj)
    return encode_faces_from_array(image_array)


def encode_faces_from_path(image_path: str) -> list[np.ndarray]:
    image_array = face_recognition.load_image_file(image_path)
    return encode_faces_from_array(image_array)


def encode_primary_face_from_file(file_obj: IO[bytes]) -> np.ndarray | None:
    image_array = face_recognition.load_image_file(file_obj)
    face_locations = face_recognition.face_locations(image_array)
    if not face_locations:
        return None

    encodings = face_recognition.face_encodings(image_array, face_locations)
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
    face_locations = face_recognition.face_locations(image_array)
    if not face_locations:
        return None
    if len(face_locations) != 1:
        raise ValueError("Multiple faces detected")
    encodings = face_recognition.face_encodings(image_array, face_locations)
    if not encodings:
        return None
    return encodings[0]
