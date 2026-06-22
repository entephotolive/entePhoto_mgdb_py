from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import secrets
from uuid import uuid4

from bson.binary import Binary
from bson.objectid import ObjectId
from django.conf import settings
from django.core.files.storage import default_storage
from pymongo import ASCENDING, DESCENDING, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from config.mongo import ensure_indexes, get_database

import shutil
EVENTS_COLLECTION = "events"
PHOTOS_COLLECTION = "photos"
IMAGES_WITH_FACE_COLLECTION = "image_with_face"
FACE_ENCODINGS_COLLECTION = "face_encodings"
COUNTERS_COLLECTION = "counters"
SCANS_COLLECTION = "guest_scans"
ATTENDEES_COLLECTION = "attendees"
SESSIONS_COLLECTION = "sessions"
PHOTO_MATCHES_COLLECTION = "photo_matches"

FOLDERS_COLLECTION = "folders"
def _database():
    ensure_indexes()
    return get_database()


def _collection(name: str):
    return _database()[name]


def _now():
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _next_sequence(name: str, increment: int = 1) -> int:
    counter = _collection(COUNTERS_COLLECTION).find_one_and_update(
        {"_id": name},
        {"$inc": {"value": int(increment)}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(counter["value"])


def allocate_sequence_range(sequence_name: str, count: int) -> list[int]:
    count = int(count)
    if count <= 0:
        return []
    end = _next_sequence(sequence_name, increment=count)
    start = end - count + 1
    return list(range(start, end + 1))


def allocate_image_ids(count: int) -> list[int]:
    return allocate_sequence_range("images", count)


def allocate_face_encoding_ids(count: int) -> list[int]:
    return allocate_sequence_range("face_encodings", count)


def get_event_by_object_id(event_object_id: ObjectId):
    return _collection(EVENTS_COLLECTION).find_one({"_id": event_object_id})


def list_attendees_by_event_id(event_object_id: ObjectId):
    return _collection(ATTENDEES_COLLECTION).find(
        {"event_id": event_object_id},
        {"attendee_id": 1, "embedding": 1, "expires_at": 1},
    )


def get_attendee(event_object_id: ObjectId, attendee_id: str):
    return _collection(ATTENDEES_COLLECTION).find_one({"event_id": event_object_id, "attendee_id": attendee_id})


def create_attendee(event_object_id: ObjectId, embedding_bytes: bytes, *, expires_at=None) -> str:
    attendee_id = f"guest_{ObjectId()}"
    now = _now()
    _collection(ATTENDEES_COLLECTION).insert_one(
        {
            "attendee_id": attendee_id,
            "event_id": event_object_id,
            "embedding": Binary(embedding_bytes),
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
            "expires_at": expires_at,
        }
    )
    return attendee_id


def touch_attendee(event_object_id: ObjectId, attendee_id: str):
    now = _now()
    _collection(ATTENDEES_COLLECTION).update_one(
        {"event_id": event_object_id, "attendee_id": attendee_id},
        {"$set": {"updated_at": now, "last_seen_at": now}},
    )


def create_session(event_object_id: ObjectId, attendee_id: str, *, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + timedelta(seconds=int(ttl_seconds))
    _collection(SESSIONS_COLLECTION).insert_one(
        {
            "token_hash": _hash_token(token),
            "attendee_id": attendee_id,
            "event_id": event_object_id,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
            "expires_at": expires_at,
        }
    )
    return token


def get_session_by_token(token: str):
    if not token:
        return None
    return _collection(SESSIONS_COLLECTION).find_one({"token_hash": _hash_token(token)})


def touch_session_by_token(token: str):
    if not token:
        return
    now = _now()
    _collection(SESSIONS_COLLECTION).update_one(
        {"token_hash": _hash_token(token)},
        {"$set": {"updated_at": now, "last_seen_at": now}},
    )


def find_existing_event_image_names(event_object_id: ObjectId, image_names: list[str]) -> set[str]:
    candidates = {name for name in image_names if name}
    if not candidates:
        return set()

    query = {"event_id": event_object_id, "image_name": {"$in": list(candidates)}}
    projection = {"image_name": 1}

    existing: set[str] = set()
    for doc in _collection(PHOTOS_COLLECTION).find(query, projection):
        if doc.get("image_name"):
            existing.add(doc["image_name"])
    for doc in _collection(IMAGES_WITH_FACE_COLLECTION).find(query, projection):
        if doc.get("image_name"):
            existing.add(doc["image_name"])
    return existing


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    return ".jpg"


def _save_uploaded_file_to_public(uploaded_file, event_object_id: ObjectId | None = None) -> dict:
    suffix = _safe_suffix(getattr(uploaded_file, "name", None))
    event_prefix = str(event_object_id) if event_object_id is not None else "misc"
    storage_name = default_storage.save(f"public/{event_prefix}/{uuid4().hex}{suffix}", uploaded_file)
    absolute_path = Path(settings.MEDIA_ROOT) / storage_name
    return {
        "storage_name": storage_name,
        "absolute_path": str(absolute_path),
        "relative_url": default_storage.url(storage_name),
    }


def create_event_photo(
    event_object_id: ObjectId,
    image_id: int,
    uploaded_file,
    *,
    has_face: bool,
    face_count: int | None = None,
    faces_processed: bool = True,
    folder_id: str | None = None,
):
    image_name = getattr(uploaded_file, "name", None)
    stored_file = _save_uploaded_file_to_public(uploaded_file, event_object_id=event_object_id)

    document = {
        "id": int(image_id),
        "event_id": event_object_id,
        "folder_id": folder_id or None,
        "image_name": image_name,
        "image_storage_name": stored_file["storage_name"],
        "image_path": stored_file["absolute_path"],
        "image_url": stored_file["relative_url"],
        "has_face": bool(has_face),
        "face_count": int(face_count) if face_count is not None else None,
        "faces_processed": bool(faces_processed),
        "uploaded_at": _now(),
        "updated_at": _now(),
    }

    collection_name = IMAGES_WITH_FACE_COLLECTION if has_face else PHOTOS_COLLECTION
    try:
        result = _collection(collection_name).insert_one(document)
        document["_id"] = result.inserted_id
        document["_collection"] = collection_name
        return document
    except DuplicateKeyError as exc:
        storage_name = stored_file.get("storage_name")
        if storage_name and default_storage.exists(storage_name):
            default_storage.delete(storage_name)
        raise ValueError(f"image already uploaded: {image_name}") from exc
    except Exception:  # noqa: BLE001
        storage_name = stored_file.get("storage_name")
        if storage_name and default_storage.exists(storage_name):
            default_storage.delete(storage_name)
        raise


def create_unprocessed_event_photo(event_object_id: ObjectId, image_id: int, uploaded_file, *, folder_id: str | None = None):
    return create_event_photo(
        event_object_id,
        image_id,
        uploaded_file,
        has_face=False,
        face_count=None,
        faces_processed=False,
        folder_id=folder_id,
    )


def promote_event_photo_to_has_face(event_object_id: ObjectId, image_id: int, *, face_count: int):
    moved = _collection(PHOTOS_COLLECTION).find_one_and_delete({"event_id": event_object_id, "id": int(image_id)})
    if not moved:
        return None

    moved["has_face"] = True
    moved["faces_processed"] = True
    moved["face_count"] = int(face_count)
    moved["updated_at"] = _now()
    moved.pop("_id", None)
    moved.pop("_collection", None)

    result = _collection(IMAGES_WITH_FACE_COLLECTION).insert_one(moved)
    moved["_id"] = result.inserted_id
    moved["_collection"] = IMAGES_WITH_FACE_COLLECTION
    return moved


def mark_event_photo_processed_without_faces(event_object_id: ObjectId, image_id: int):
    _collection(PHOTOS_COLLECTION).update_one(
        {"event_id": event_object_id, "id": int(image_id)},
        {"$set": {"faces_processed": True, "face_count": 0, "updated_at": _now()}},
    )


def update_event_photo_face_metadata(event_object_id: ObjectId, image_id: int, *, face_count: int):
    _collection(IMAGES_WITH_FACE_COLLECTION).update_one(
        {"event_id": event_object_id, "id": int(image_id)},
        {"$set": {"faces_processed": True, "face_count": int(face_count), "has_face": True, "updated_at": _now()}},
    )


def delete_photo_document(document):
    if not document:
        return

    collection_name = document.get("_collection")
    if collection_name and document.get("_id") is not None:
        _collection(collection_name).delete_one({"_id": document["_id"]})

    storage_name = document.get("image_storage_name")
    if storage_name and default_storage.exists(storage_name):
        default_storage.delete(storage_name)


def find_photo_by_image_id(image_id: int):
    image_id = int(image_id)
    doc = _collection(PHOTOS_COLLECTION).find_one({"id": image_id})
    if doc:
        doc["_collection"] = PHOTOS_COLLECTION
        return doc
    doc = _collection(IMAGES_WITH_FACE_COLLECTION).find_one({"id": image_id})
    if doc:
        doc["_collection"] = IMAGES_WITH_FACE_COLLECTION
        return doc
    return None


def delete_photo_by_image_id(image_id: int) -> bool:
    document = find_photo_by_image_id(image_id)
    if not document:
        return False

    delete_query = {"image_id": int(image_id)}
    if document.get("event_id") is not None:
        delete_query["event_id"] = document["event_id"]
    _collection(FACE_ENCODINGS_COLLECTION).delete_many(delete_query)
    delete_photo_document(document)
    return True


def list_event_photos(event_object_id: ObjectId):
    photos = list(_collection(PHOTOS_COLLECTION).find({"event_id": event_object_id}).sort("uploaded_at", DESCENDING))
    with_face = list(
        _collection(IMAGES_WITH_FACE_COLLECTION).find({"event_id": event_object_id}).sort("uploaded_at", DESCENDING)
    )
    combined = photos + with_face
    combined.sort(key=lambda doc: doc.get("uploaded_at") or _now(), reverse=True)
    return combined


def list_face_encodings_by_event_id(event_object_id: ObjectId):
    return _collection(FACE_ENCODINGS_COLLECTION).find(
        {"event_id": event_object_id},
        {"image_id": 1, "encoding": 1},
        no_cursor_timeout=False,
    )


def delete_event_face_encodings(event_object_id: ObjectId, image_id: int):
    _collection(FACE_ENCODINGS_COLLECTION).delete_many({"event_id": event_object_id, "image_id": int(image_id)})


def insert_face_encodings_for_event(event_object_id: ObjectId, image_id: int, encodings: list[bytes]) -> int:
    if not encodings:
        return 0

    ids = allocate_face_encoding_ids(len(encodings))
    now = _now()
    documents = []
    for public_id, encoding_bytes in zip(ids, encodings, strict=True):
        documents.append(
            {
                "id": int(public_id),
                "image_id": int(image_id),
                "event_id": event_object_id,
                "encoding": Binary(encoding_bytes),
                "created_at": now,
            }
        )

    _collection(FACE_ENCODINGS_COLLECTION).insert_many(documents, ordered=False)
    return len(documents)


def upsert_photo_matches(
    event_object_id: ObjectId,
    *,
    image_id: int,
    photo_uploaded_at,
    matches: list[dict],
) -> int:
    """Upsert matches for a photo (avoid duplicates).

    `matches`: list of {"attendee_id": str, "distance": float, "confidence": float}
    """
    if not matches:
        return 0

    ops = []
    now = _now()
    for m in matches:
        attendee_id = m.get("attendee_id")
        if not attendee_id:
            continue
        distance = float(m.get("distance", 0.0))
        confidence = float(m.get("confidence", 0.0))
        ops.append(
            UpdateOne(
                {"event_id": event_object_id, "image_id": int(image_id), "attendee_id": attendee_id},
                {
                    "$setOnInsert": {
                        "event_id": event_object_id,
                        "image_id": int(image_id),
                        "attendee_id": attendee_id,
                        "photo_uploaded_at": photo_uploaded_at,
                        "matched_at": now,
                    },
                    "$set": {
                        "distance": distance,
                        "confidence": confidence,
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
        )

    if not ops:
        return 0

    result = _collection(PHOTO_MATCHES_COLLECTION).bulk_write(ops, ordered=False)
    return int(getattr(result, "upserted_count", 0) or 0)


def upsert_attendee_photo_matches(
    event_object_id: ObjectId,
    *,
    attendee_id: str,
    items: list[dict],
) -> int:
    """Upsert many (image_id -> attendee) matches in one bulk call.

    `items`: list of {"image_id": int, "photo_uploaded_at": dt, "distance": float, "confidence": float}
    """
    if not items:
        return 0

    ops = []
    now = _now()
    for item in items:
        image_id = item.get("image_id")
        photo_uploaded_at = item.get("photo_uploaded_at")
        if image_id is None or photo_uploaded_at is None:
            continue
        distance = float(item.get("distance", 0.0))
        confidence = float(item.get("confidence", 0.0))
        ops.append(
            UpdateOne(
                {"event_id": event_object_id, "image_id": int(image_id), "attendee_id": attendee_id},
                {
                    "$setOnInsert": {
                        "event_id": event_object_id,
                        "image_id": int(image_id),
                        "attendee_id": attendee_id,
                        "photo_uploaded_at": photo_uploaded_at,
                        "matched_at": now,
                    },
                    "$set": {"distance": distance, "confidence": confidence, "updated_at": now},
                },
                upsert=True,
            )
        )

    if not ops:
        return 0

    result = _collection(PHOTO_MATCHES_COLLECTION).bulk_write(ops, ordered=False)
    return int(getattr(result, "upserted_count", 0) or 0)


def list_photo_matches_for_attendee(
    event_object_id: ObjectId,
    attendee_id: str,
    *,
    limit: int,
    before=None,
    since=None,
):
    query = {"event_id": event_object_id, "attendee_id": attendee_id}
    if before is not None or since is not None:
        range_query = {}
        if before is not None:
            range_query["$lt"] = before
        if since is not None:
            range_query["$gt"] = since
        query["photo_uploaded_at"] = range_query

    return list(
        _collection(PHOTO_MATCHES_COLLECTION)
        .find(query, {"image_id": 1, "photo_uploaded_at": 1, "confidence": 1, "distance": 1})
        .sort("photo_uploaded_at", DESCENDING)
        .limit(int(limit))
    )


def count_photo_matches_for_attendee(event_object_id: ObjectId, attendee_id: str) -> int:
    return int(
        _collection(PHOTO_MATCHES_COLLECTION).count_documents({"event_id": event_object_id, "attendee_id": attendee_id})
    )


def get_photos_by_image_ids(event_object_id: ObjectId, image_ids: list[int]):
    int_ids = [int(i) for i in image_ids]
    query = {"event_id": event_object_id, "id": {"$in": int_ids}}
    photos = list(_collection(PHOTOS_COLLECTION).find(query))
    with_face = list(_collection(IMAGES_WITH_FACE_COLLECTION).find(query))
    return photos + with_face


def create_scan(event_object_id: ObjectId, matched_image_ids: list[int]) -> str:
    result = _collection(SCANS_COLLECTION).insert_one(
        {"event_id": event_object_id, "matched_image_ids": [int(i) for i in matched_image_ids], "created_at": _now()}
    )
    return str(result.inserted_id)


def get_scan(event_object_id: ObjectId, scan_id: str):
    if not ObjectId.is_valid(scan_id):
        return None
    return _collection(SCANS_COLLECTION).find_one({"_id": ObjectId(scan_id), "event_id": event_object_id})



def cleanup_events_expired_after_10_days() -> dict:
    now = _now()
    cutoff_date = now - timedelta(days=10)

    expired_events = list(
        _collection(EVENTS_COLLECTION).find(
            {"date": {"$lte": cutoff_date}},
            {"_id": 1, "date": 1, "title": 1},
        )
    )

    deleted_events = 0
    deleted_photos = 0

    for event in expired_events:
        event_object_id = event["_id"]
        event_id_str = str(event_object_id)

        event_filters = [
            {"event_id": event_object_id},
            {"event_id": event_id_str},
            {"eventId": event_object_id},
            {"eventId": event_id_str},
        ]

        # Delete physical event folder: media/public/<event_id>
        event_folder = Path(settings.MEDIA_ROOT) / "public" / event_id_str
        if event_folder.exists():
            shutil.rmtree(event_folder)

        # Count before delete
        for filter_query in event_filters:
            deleted_photos += _collection(PHOTOS_COLLECTION).count_documents(filter_query)
            deleted_photos += _collection(IMAGES_WITH_FACE_COLLECTION).count_documents(filter_query)

        # Delete photo documents
        for filter_query in event_filters:
            _collection(PHOTOS_COLLECTION).delete_many(filter_query)
            _collection(IMAGES_WITH_FACE_COLLECTION).delete_many(filter_query)
            _collection(FACE_ENCODINGS_COLLECTION).delete_many(filter_query)
            _collection(PHOTO_MATCHES_COLLECTION).delete_many(filter_query)
            _collection(ATTENDEES_COLLECTION).delete_many(filter_query)
            _collection(SESSIONS_COLLECTION).delete_many(filter_query)
            _collection(SCANS_COLLECTION).delete_many(filter_query)
            _collection(FOLDERS_COLLECTION).delete_many(filter_query)

        # Delete event itself
        _collection(EVENTS_COLLECTION).delete_one({"_id": event_object_id})
        deleted_events += 1

    return {
        "deleted_events": deleted_events,
        "deleted_photos": deleted_photos,
    }