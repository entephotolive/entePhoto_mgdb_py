from __future__ import annotations

from collections.abc import Iterable

import numpy as np


DEFAULT_TOLERANCE = 0.5
DEFAULT_BATCH_SIZE = 1024


def find_matching_image_ids(
    face_documents: Iterable[dict],
    guest_encoding: np.ndarray,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[int]:
    """Return matched image IDs ordered by best (lowest) distance.

    `face_documents` should yield dicts with keys: `image_id` and `encoding` (bytes-like).
    """

    guest = np.asarray(guest_encoding, dtype=np.float64)
    best_distance_by_image: dict[int, float] = {}

    batch_encodings: list[np.ndarray] = []
    batch_image_ids: list[int] = []

    def flush():
        if not batch_encodings:
            return
        known = np.vstack(batch_encodings)  # (n, 128)
        distances = np.linalg.norm(known - guest, axis=1)
        for img_id, dist in zip(batch_image_ids, distances, strict=True):
            if dist <= tolerance:
                prev = best_distance_by_image.get(img_id)
                if prev is None or dist < prev:
                    best_distance_by_image[img_id] = float(dist)
        batch_encodings.clear()
        batch_image_ids.clear()

    for doc in face_documents:
        try:
            img_id = int(doc.get("image_id"))
            encoding_bytes = doc.get("encoding")
            if not encoding_bytes:
                continue
            encoding = np.frombuffer(encoding_bytes, dtype=np.float64)
            if encoding.shape[0] != 128:
                continue
        except Exception:  # noqa: BLE001
            continue

        batch_encodings.append(encoding)
        batch_image_ids.append(img_id)
        if len(batch_encodings) >= batch_size:
            flush()

    flush()

    return [image_id for image_id, _ in sorted(best_distance_by_image.items(), key=lambda item: item[1])]


def find_matching_image_ids_with_distances(
    face_documents: Iterable[dict],
    guest_encoding: np.ndarray,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[tuple[int, float]]:
    guest = np.asarray(guest_encoding, dtype=np.float64)
    best_distance_by_image: dict[int, float] = {}

    batch_encodings: list[np.ndarray] = []
    batch_image_ids: list[int] = []

    def flush():
        if not batch_encodings:
            return
        known = np.vstack(batch_encodings)
        distances = np.linalg.norm(known - guest, axis=1)
        for img_id, dist in zip(batch_image_ids, distances, strict=True):
            if dist <= tolerance:
                prev = best_distance_by_image.get(img_id)
                if prev is None or dist < prev:
                    best_distance_by_image[img_id] = float(dist)
        batch_encodings.clear()
        batch_image_ids.clear()

    for doc in face_documents:
        try:
            img_id = int(doc.get("image_id"))
            encoding_bytes = doc.get("encoding")
            if not encoding_bytes:
                continue
            encoding = np.frombuffer(encoding_bytes, dtype=np.float64)
            if encoding.shape[0] != 128:
                continue
        except Exception:  # noqa: BLE001
            continue

        batch_encodings.append(encoding)
        batch_image_ids.append(img_id)
        if len(batch_encodings) >= batch_size:
            flush()

    flush()

    return sorted(best_distance_by_image.items(), key=lambda item: item[1])


def find_matching_attendee_id(
    attendee_documents: Iterable[dict],
    guest_encoding: np.ndarray,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[str, float] | None:
    """Return (attendee_id, distance) for the best match, or None."""
    guest = np.asarray(guest_encoding, dtype=np.float64)

    best_attendee_id: str | None = None
    best_distance: float | None = None

    batch_encodings: list[np.ndarray] = []
    batch_attendee_ids: list[str] = []

    def flush():
        nonlocal best_attendee_id, best_distance
        if not batch_encodings:
            return
        known = np.vstack(batch_encodings)
        distances = np.linalg.norm(known - guest, axis=1)
        for attendee_id, dist in zip(batch_attendee_ids, distances, strict=True):
            if dist <= tolerance and (best_distance is None or dist < best_distance):
                best_distance = float(dist)
                best_attendee_id = attendee_id
        batch_encodings.clear()
        batch_attendee_ids.clear()

    for doc in attendee_documents:
        attendee_id = doc.get("attendee_id")
        if not attendee_id:
            continue
        encoding_bytes = doc.get("embedding")
        if not encoding_bytes:
            continue
        try:
            encoding = np.frombuffer(encoding_bytes, dtype=np.float64)
            if encoding.shape[0] != 128:
                continue
        except Exception:  # noqa: BLE001
            continue

        batch_encodings.append(encoding)
        batch_attendee_ids.append(str(attendee_id))
        if len(batch_encodings) >= batch_size:
            flush()

    flush()

    if best_attendee_id is None or best_distance is None:
        return None
    return best_attendee_id, best_distance


def match_photo_faces_to_attendees(
    attendee_documents: Iterable[dict],
    face_encodings: list[np.ndarray],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[dict]:
    """Return attendee matches for a photo given its face encodings.

    Output: [{"attendee_id": str, "distance": float, "confidence": float}, ...]
    """
    if not face_encodings:
        return []

    attendee_ids: list[str] = []
    attendee_encodings: list[np.ndarray] = []

    for doc in attendee_documents:
        attendee_id = doc.get("attendee_id")
        embedding_bytes = doc.get("embedding")
        if not attendee_id or not embedding_bytes:
            continue
        try:
            emb = np.frombuffer(embedding_bytes, dtype=np.float64)
            if emb.shape[0] != 128:
                continue
        except Exception:  # noqa: BLE001
            continue
        attendee_ids.append(str(attendee_id))
        attendee_encodings.append(emb)

    if not attendee_encodings:
        return []

    known = np.vstack(attendee_encodings)  # (n, 128)
    best_distance: dict[str, float] = {}

    for face in face_encodings:
        face_vec = np.asarray(face, dtype=np.float64)
        distances = np.linalg.norm(known - face_vec, axis=1)
        for attendee_id, dist in zip(attendee_ids, distances, strict=True):
            if dist <= tolerance:
                prev = best_distance.get(attendee_id)
                if prev is None or dist < prev:
                    best_distance[attendee_id] = float(dist)

    return [
        {
            "attendee_id": attendee_id,
            "distance": dist,
            "confidence": max(0.0, 1.0 - dist),
        }
        for attendee_id, dist in sorted(best_distance.items(), key=lambda item: item[1])
    ]
