from __future__ import annotations

from typing import IO

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from PIL import Image

# ---------------------------------------------------------------------------
# InsightFace Initialization
# ---------------------------------------------------------------------------
app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"],
)

app.prepare(
    ctx_id=-1,
    det_size=(640, 640),
)
_MAX_DETECTION_PX = 3000
# _MAX_DETECTION_PX = 1000


def _resize_for_detection(image_array: np.ndarray) -> np.ndarray:
    h, w = image_array.shape[:2]
    longest = max(h, w)

    if longest <= _MAX_DETECTION_PX:
        return image_array

    scale = _MAX_DETECTION_PX / longest

    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    # InsightFace receives OpenCV BGR arrays. Convert only for PIL resizing,
    # then convert back so detector input remains in the expected color order.
    rgb_image = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_image)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _face_embedding(face) -> np.ndarray:
    embedding = getattr(face, "normed_embedding", None)
    if embedding is None:
        embedding = face.embedding
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

    return np.asarray(embedding, dtype=np.float32)


def encode_faces_from_array(image_array: np.ndarray) -> list[np.ndarray]:
    image_array = _resize_for_detection(image_array)

    faces = app.get(image_array)

    embeddings = []

    for face in faces:
        embeddings.append(_face_embedding(face))

    return embeddings


def encode_faces_from_file(file_obj: IO[bytes]) -> list[np.ndarray]:
    image_bytes = np.frombuffer(
        file_obj.read(),
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_bytes,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        return []

    return encode_faces_from_array(image)


def encode_faces_from_path(image_path: str) -> list[np.ndarray]:
    image = cv2.imread(image_path)

    if image is None:
        return []

    return encode_faces_from_array(image)


def encode_primary_face_from_file(file_obj: IO[bytes]) -> np.ndarray | None:
    image_bytes = np.frombuffer(
        file_obj.read(),
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_bytes,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        return None

    image = _resize_for_detection(image)

    faces = app.get(image)

    if not faces:
        return None

    largest_face = max(
        faces,
        key=lambda face: (
            face.bbox[2] - face.bbox[0]
        ) * (
            face.bbox[3] - face.bbox[1]
        ),
    )

    return _face_embedding(largest_face)


def encode_single_face_from_file(file_obj: IO[bytes]) -> np.ndarray | None:
    image_bytes = np.frombuffer(
        file_obj.read(),
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_bytes,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        return None

    image = _resize_for_detection(image)

    faces = app.get(image)

    if len(faces) == 0:
        return None

    if len(faces) > 1:
        raise ValueError("Multiple faces detected")

    return _face_embedding(faces[0])
