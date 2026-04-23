from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bson.binary import Binary
from bson.objectid import ObjectId
from django.conf import settings
from django.core.files.storage import default_storage
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from config.mongo import ensure_indexes, get_database


WEDDINGS_COLLECTION = "weddings"
EVENTS_COLLECTION = "events"
IMAGES_COLLECTION = "images"
PHOTOS_COLLECTION = "photos"
IMAGES_WITH_FACE_COLLECTION = "image_with_face"
FACE_ENCODINGS_COLLECTION = "face_encodings"
USERS_COLLECTION = "users"
COUNTERS_COLLECTION = "counters"


def _database():
    ensure_indexes()
    return get_database()


def _collection(name):
    return _database()[name]


def _now():
    return datetime.now(timezone.utc)


def _next_sequence(name):
    counter = _collection(COUNTERS_COLLECTION).find_one_and_update(
        {"_id": name},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return counter["value"]


def allocate_image_id():
    return _next_sequence("images")


def _serialize_user_snapshot(user_snapshot):
    if not user_snapshot:
        return None

    return {
        "id": user_snapshot.get("id"),
        "username": user_snapshot.get("username") or "Unknown",
        "email": user_snapshot.get("email"),
        "source": user_snapshot.get("source", "request"),
    }


def upsert_user(user_snapshot):
    if not user_snapshot:
        return None

    user_document = _serialize_user_snapshot(user_snapshot)
    lookup = {}

    if user_document.get("id") is not None:
        lookup["id"] = user_document["id"]
    elif user_document.get("username"):
        lookup["username"] = user_document["username"]
    elif user_document.get("email"):
        lookup["email"] = user_document["email"]
    else:
        return user_document

    _collection(USERS_COLLECTION).update_one(
        lookup,
        {
            "$set": {
                **user_document,
                "updated_at": _now(),
            },
            "$setOnInsert": {
                "created_at": _now(),
            },
        },
        upsert=True,
    )
    return user_document


def create_wedding(name, date=None, location=None, user_snapshot=None):
    wedding_document = {
        "id": _next_sequence("weddings"),
        "name": name,
        "date": date,
        "location": location,
        "created_by": upsert_user(user_snapshot),
        "created_at": _now(),
    }
    _collection(WEDDINGS_COLLECTION).insert_one(wedding_document)
    return wedding_document


def get_wedding_by_public_id(wedding_id):
    return _collection(WEDDINGS_COLLECTION).find_one({"id": int(wedding_id)})


def get_event_by_object_id(event_object_id: ObjectId):
    return _collection(EVENTS_COLLECTION).find_one({"_id": event_object_id})


def event_image_name_exists(event_object_id: ObjectId, image_name: str):
    if not image_name:
        return False
    if _collection(PHOTOS_COLLECTION).find_one({"event_id": event_object_id, "image_name": image_name}):
        return True
    if _collection(IMAGES_WITH_FACE_COLLECTION).find_one({"event_id": event_object_id, "image_name": image_name}):
        return True
    return False

def _save_uploaded_file_to_public(uploaded_file, event_object_id: ObjectId | None = None):
    suffix = Path(uploaded_file.name).suffix or ".jpg"
    event_prefix = str(event_object_id) if event_object_id is not None else "misc"
    storage_name = default_storage.save(f"public/{event_prefix}/{uuid4().hex}{suffix}", uploaded_file)
    absolute_path = Path(settings.MEDIA_ROOT) / storage_name
    return {
        "storage_name": storage_name,
        "absolute_path": str(absolute_path),
        "relative_url": default_storage.url(storage_name),
    }


def create_event_photo(event_object_id: ObjectId, image_id: int, uploaded_file, has_face: bool, folder_id=None):
    image_name = getattr(uploaded_file, "name", None)

    # Prevent duplicates by name within the same event (across both collections).
    if image_name:
        if event_image_name_exists(event_object_id, image_name):
            raise ValueError(f"image already uploaded: {image_name}")

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
        "uploaded_at": _now(),
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
        details = getattr(exc, "details", None) or {}
        key_pattern = details.get("keyPattern") or {}
        if key_pattern.get("hash") == 1:
            raise ValueError("Legacy unique index on `hash` still exists (hash_1). Restart the backend to drop it.") from exc
        raise ValueError(f"image already uploaded: {image_name}") from exc
    except Exception:  # noqa: BLE001
        storage_name = stored_file.get("storage_name")
        if storage_name and default_storage.exists(storage_name):
            default_storage.delete(storage_name)
        raise


def delete_event_photo(document):
    if not document:
        return

    collection_name = document.get("_collection")
    if collection_name and document.get("_id") is not None:
        _collection(collection_name).delete_one({"_id": document["_id"]})

    storage_name = document.get("image_storage_name")
    if storage_name and default_storage.exists(storage_name):
        default_storage.delete(storage_name)


def list_event_photos(event_object_id: ObjectId):
    photos = list(_collection(PHOTOS_COLLECTION).find({"event_id": event_object_id}).sort("uploaded_at", DESCENDING))
    with_face = list(
        _collection(IMAGES_WITH_FACE_COLLECTION).find({"event_id": event_object_id}).sort("uploaded_at", DESCENDING)
    )
    combined = photos + with_face
    combined.sort(key=lambda doc: doc.get("uploaded_at") or _now(), reverse=True)
    return combined


def delete_event_face_encodings(event_object_id: ObjectId, image_id: int):
    _collection(FACE_ENCODINGS_COLLECTION).delete_many({"event_id": event_object_id, "image_id": int(image_id)})


def list_weddings():
    weddings = list(_collection(WEDDINGS_COLLECTION).find().sort("id", DESCENDING))
    images = list(_collection(IMAGES_COLLECTION).find({}, {"wedding_id": 1}))

    photo_counts = {}
    for image in images:
        wedding_id = image.get("wedding_id")
        if wedding_id is None:
            continue
        photo_counts[wedding_id] = photo_counts.get(wedding_id, 0) + 1

    for wedding in weddings:
        wedding["photo_count"] = photo_counts.get(wedding["id"], 0)

    return weddings


def delete_wedding(wedding_id):
    images = list_images_by_wedding_id(wedding_id)
    for image in images:
        delete_image(image["id"])

    result = _collection(WEDDINGS_COLLECTION).delete_one({"id": int(wedding_id)})
    return result.deleted_count > 0


def _save_uploaded_file(uploaded_file):
    suffix = Path(uploaded_file.name).suffix or ".jpg"
    storage_name = default_storage.save(f"weddings/{uuid4().hex}{suffix}", uploaded_file)
    absolute_path = Path(settings.MEDIA_ROOT) / storage_name
    return {
        "storage_name": storage_name,
        "absolute_path": str(absolute_path),
        "relative_url": default_storage.url(storage_name),
    }


def create_image(wedding_id, uploaded_file):
    stored_file = _save_uploaded_file(uploaded_file)
    image_document = {
        "id": _next_sequence("images"),
        "wedding_id": int(wedding_id),
        "image_name": stored_file["storage_name"],
        "image_path": stored_file["absolute_path"],
        "image_url": stored_file["relative_url"],
        "uploaded_at": _now(),
    }
    _collection(IMAGES_COLLECTION).insert_one(image_document)
    return image_document


def get_image_by_public_id(image_id):
    return _collection(IMAGES_COLLECTION).find_one({"id": int(image_id)})


def list_images_by_wedding_id(wedding_id):
    return list(_collection(IMAGES_COLLECTION).find({"wedding_id": int(wedding_id)}).sort("uploaded_at", DESCENDING))


def delete_image(image_id):
    image = get_image_by_public_id(image_id)
    if not image:
        return False

    if image.get("image_name") and default_storage.exists(image["image_name"]):
        default_storage.delete(image["image_name"])

    _collection(FACE_ENCODINGS_COLLECTION).delete_many({"image_id": int(image_id)})
    _collection(IMAGES_COLLECTION).delete_one({"id": int(image_id)})
    return True


def create_face_encoding(image_id, wedding_id, encoding_bytes):
    face_document = {
        "id": _next_sequence("face_encodings"),
        "image_id": int(image_id),
        "wedding_id": int(wedding_id),
        "encoding": Binary(encoding_bytes),
        "created_at": _now(),
    }
    _collection(FACE_ENCODINGS_COLLECTION).insert_one(face_document)
    return face_document


def create_face_encoding_for_event(image_id, event_object_id: ObjectId, encoding_bytes):
    face_document = {
        "id": _next_sequence("face_encodings"),
        "image_id": int(image_id),
        "event_id": event_object_id,
        "encoding": Binary(encoding_bytes),
        "created_at": _now(),
    }
    _collection(FACE_ENCODINGS_COLLECTION).insert_one(face_document)
    return face_document


def list_face_encodings_by_wedding_id(wedding_id):
    return list(_collection(FACE_ENCODINGS_COLLECTION).find({"wedding_id": int(wedding_id)}))


def list_face_encodings_by_event_id(event_object_id: ObjectId):
    return list(_collection(FACE_ENCODINGS_COLLECTION).find({"event_id": event_object_id}))


def get_photos_by_image_ids(event_object_id: ObjectId, image_ids: list):
    """Return photo documents (from both collections) matching the given image_ids for an event."""
    int_ids = [int(i) for i in image_ids]
    query = {"event_id": event_object_id, "id": {"$in": int_ids}}
    photos = list(_collection(PHOTOS_COLLECTION).find(query))
    with_face = list(_collection(IMAGES_WITH_FACE_COLLECTION).find(query))
    return photos + with_face
