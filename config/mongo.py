import re
from functools import lru_cache
from threading import Lock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import OperationFailure, PyMongoError


_client_lock = Lock()
_indexes_lock = Lock()
_indexes_ready = False


def _extract_database_name(uri):
    uri = _normalize_mongodb_uri(uri)
    database_name = uri.rsplit("/", 1)[-1]
    if "?" in database_name:
        database_name = database_name.split("?", 1)[0]
    return database_name.strip()


def _normalize_mongodb_uri(uri):
    if not uri:
        return uri

    return re.sub(r"\[([^\]]+)\]\(mailto:[^)]+\)", r"\1", uri)


@lru_cache(maxsize=1)
def get_mongo_client():
    mongodb_uri = _normalize_mongodb_uri(getattr(settings, "MONGODB_URI", None))
    if not mongodb_uri:
        raise ImproperlyConfigured("MONGODB_URI is required to connect to MongoDB Atlas.")
    if not mongodb_uri.startswith("mongodb"):
        raise ImproperlyConfigured("MONGODB_URI must start with mongodb:// or mongodb+srv://.")

    with _client_lock:
        return MongoClient(
            mongodb_uri,
            appname="photo-ceremony-backend",
            maxPoolSize=20,
            minPoolSize=1,
            retryReads=True,
            retryWrites=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            tz_aware=True,
        )


@lru_cache(maxsize=1)
def get_database():
    database_name = _extract_database_name(settings.MONGODB_URI)
    if not database_name:
        raise ImproperlyConfigured("MONGODB_URI must include a database name.")
    return get_mongo_client()[database_name]


def ping_database():
    get_database().command("ping")


def ensure_indexes():
    global _indexes_ready

    if _indexes_ready:
        return

    def safe_drop_index(collection, index_name):
        try:
            collection.drop_index(index_name)
        except Exception:  # noqa: BLE001
            return

    def safe_create_index(collection, keys, **kwargs):
        """Create an index, but never attempt to (re)define an _id index.

        MongoDB automatically creates a unique _id index and disallows certain
        options (like `unique`) on _id index specifications. Some deployments
        may still have older code paths attempting this, so we defensively skip
        those failures while still surfacing other index problems.
        """

        # Avoid creating a second _id index (it already exists).
        try:
            first_key = keys[0][0] if isinstance(keys, (list, tuple)) and keys else None
        except Exception:  # noqa: BLE001
            first_key = None

        if first_key == "_id":
            return

        try:
            collection.create_index(keys, **kwargs)
        except OperationFailure as exc:
            # Atlas returns code 197 for invalid index specification options.
            if exc.code == 197 and "_id index specification" in str(exc):
                return
            # Some Atlas tiers / older server versions may reject certain index options
            # (e.g. partial filter expressions). Don't block startup on this.
            if exc.code == 67 or (exc.details and exc.details.get("codeName") == "CannotCreateIndex"):
                return
            # Existing data may violate a new unique index (e.g. duplicate or null ids).
            # Don't block app startup on this; the collection can be cleaned up later.
            if exc.code == 11000 or (exc.details and exc.details.get("codeName") == "DuplicateKey"):
                return

            # If an index exists with the same name but different options, try to replace it.
            code_name = exc.details.get("codeName") if exc.details else None
            if code_name in {"IndexOptionsConflict", "IndexKeySpecsConflict"}:
                existing_name = kwargs.get("name")
                if not existing_name:
                    raise
                try:
                    collection.drop_index(existing_name)
                except Exception:  # noqa: BLE001
                    # Best-effort: if we can't drop it, surface the original error.
                    raise
                try:
                    collection.create_index(keys, **kwargs)
                except OperationFailure as exc2:
                    if exc2.code == 11000 or (exc2.details and exc2.details.get("codeName") == "DuplicateKey"):
                        return
                    raise
                return
            raise

    with _indexes_lock:
        if _indexes_ready:
            return

        database = get_database()

        # Remove legacy hash-based uniqueness that breaks inserts when `hash` is missing/null.
        safe_drop_index(database["photos"], "hash_1")
        safe_drop_index(database["image_with_face"], "hash_1")
        # Remove legacy 'name' unique index — schema now uses 'image_name', so this
        # index was causing DuplicateKeyError for every second no-face image (null == null).
        safe_drop_index(database["photos"], "name_1")

        safe_create_index(database["weddings"], [("id", ASCENDING)], unique=True, name="wedding_public_id")
        safe_create_index(database["weddings"], [("created_by.username", ASCENDING)], name="wedding_created_by_username")
        safe_create_index(database["weddings"], [("date", DESCENDING)], name="wedding_date_desc")

        safe_create_index(database["images"], [("id", ASCENDING)], unique=True, name="image_public_id")
        safe_create_index(
            database["images"],
            [("wedding_id", ASCENDING), ("uploaded_at", DESCENDING)],
            name="image_wedding_uploaded_at",
        )

        safe_create_index(database["face_encodings"], [("id", ASCENDING)], unique=True, name="face_public_id")
        safe_create_index(
            database["face_encodings"],
            [("wedding_id", ASCENDING), ("image_id", ASCENDING)],
            name="face_wedding_image",
        )
        safe_create_index(
            database["face_encodings"],
            [("event_id", ASCENDING), ("image_id", ASCENDING)],
            name="face_event_image",
        )

        safe_create_index(
            database["photos"],
            [("id", ASCENDING)],
            unique=True,
            name="photo_public_id",
            # Avoid `$ne: null` here since some MongoDB versions rewrite it to `$not`,
            # which is not supported in partial index expressions in Atlas.
            partialFilterExpression={"id": {"$gt": 0}},
        )
        safe_create_index(
            database["photos"],
            [("event_id", ASCENDING), ("image_name", ASCENDING)],
            unique=True,
            name="photo_event_image_name_unique",
            partialFilterExpression={"image_name": {"$gt": ""}},
        )
        safe_create_index(
            database["photos"],
            [("event_id", ASCENDING), ("uploaded_at", DESCENDING)],
            name="photo_event_uploaded_at",
        )

        safe_create_index(
            database["image_with_face"],
            [("id", ASCENDING)],
            unique=True,
            name="image_with_face_public_id",
            partialFilterExpression={"id": {"$gt": 0}},
        )
        safe_create_index(
            database["image_with_face"],
            [("event_id", ASCENDING), ("image_name", ASCENDING)],
            unique=True,
            name="image_with_face_event_image_name_unique",
            partialFilterExpression={"image_name": {"$gt": ""}},
        )
        safe_create_index(
            database["image_with_face"],
            [("event_id", ASCENDING), ("uploaded_at", DESCENDING)],
            name="image_with_face_event_uploaded_at",
        )

        safe_create_index(database["users"], [("id", ASCENDING)], unique=True, sparse=True, name="user_public_id")
        safe_create_index(database["users"], [("username", ASCENDING)], unique=True, sparse=True, name="user_username")
        safe_create_index(database["users"], [("email", ASCENDING)], unique=True, sparse=True, name="user_email")

        safe_create_index(
            database["guest_scans"],
            [("event_id", ASCENDING), ("created_at", DESCENDING)],
            name="guest_scans_event_created_at",
        )

        safe_create_index(
            database["attendees"],
            [("attendee_id", ASCENDING)],
            unique=True,
            name="attendees_attendee_id_unique",
            partialFilterExpression={"attendee_id": {"$gt": ""}},
        )
        safe_create_index(
            database["attendees"],
            [("event_id", ASCENDING), ("updated_at", DESCENDING)],
            name="attendees_event_updated_at",
        )

        safe_create_index(
            database["sessions"],
            [("token_hash", ASCENDING)],
            unique=True,
            name="sessions_token_hash_unique",
            partialFilterExpression={"token_hash": {"$gt": ""}},
        )
        safe_create_index(
            database["sessions"],
            [("expires_at", ASCENDING)],
            name="sessions_expires_at_ttl",
            expireAfterSeconds=0,
        )
        safe_create_index(
            database["sessions"],
            [("event_id", ASCENDING), ("attendee_id", ASCENDING)],
            name="sessions_event_attendee",
        )

        safe_create_index(
            database["photo_matches"],
            [("event_id", ASCENDING), ("image_id", ASCENDING), ("attendee_id", ASCENDING)],
            unique=True,
            name="photo_matches_unique",
        )
        safe_create_index(
            database["photo_matches"],
            [("event_id", ASCENDING), ("attendee_id", ASCENDING), ("photo_uploaded_at", DESCENDING)],
            name="photo_matches_attendee_feed",
        )
        safe_create_index(
            database["photo_matches"],
            [("event_id", ASCENDING), ("image_id", ASCENDING)],
            name="photo_matches_event_image",
        )

        _indexes_ready = True


def assert_database_ready():
    _verify_database_ready()


@lru_cache(maxsize=1)
def _verify_database_ready():
    try:
        ping_database()
        ensure_indexes()
    except PyMongoError as exc:
        raise ImproperlyConfigured(f"MongoDB Atlas connection failed: {exc}") from exc

    return True
