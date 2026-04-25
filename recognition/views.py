from __future__ import annotations

from datetime import datetime, timezone

from bson.objectid import ObjectId
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from PIL import Image, UnidentifiedImageError
from pymongo.errors import PyMongoError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from config.mongo import assert_database_ready, ping_database
from .repositories import (
    allocate_image_ids,
    count_photo_matches_for_attendee,
    create_event_photo,
    create_unprocessed_event_photo,
    delete_photo_document,
    delete_event_face_encodings,
    delete_photo_by_image_id,
    get_session_by_token,
    find_existing_event_image_names,
    get_event_by_object_id,
    get_photos_by_image_ids,
    list_attendees_by_event_id,
    list_photo_matches_for_attendee,
    touch_attendee,
    touch_session_by_token,
    create_attendee,
    create_session,
    insert_face_encodings_for_event,
    list_event_photos,
    list_face_encodings_by_event_id,
    upsert_attendee_photo_matches,
    upsert_photo_matches,
)
from .serializers import MyPhotosSerializer, ScanFaceSerializer, UploadImagesSerializer
from .services.face_encode import encode_faces_from_file, encode_single_face_from_file
from .services.face_match import (
    find_matching_attendee_id,
    find_matching_image_ids,
    find_matching_image_ids_with_distances,
    match_photo_faces_to_attendees,
)
from .tasks import process_event_photo_faces
from .notify import notify_attendee_new_match


def _database_error_response(exc: Exception):
    return Response({"error": "Database operation failed", "details": str(exc)}, status=500)


def _build_image_url(request, image_document: dict) -> str:
    image_url = image_document.get("image_url") or ""
    if image_url.startswith(("http://", "https://")):
        return image_url
    return request.build_absolute_uri(image_url)


def _rewind(file_obj) -> None:
    try:
        file_obj.seek(0)
    except Exception:  # noqa: BLE001
        return


def _validate_image_upload(uploaded_file) -> str | None:
    if not uploaded_file:
        return "Image is required"

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > settings.MAX_UPLOAD_BYTES:
        return f"Image too large (max {settings.MAX_UPLOAD_MB} MB)"

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and content_type not in settings.ALLOWED_IMAGE_MIME_TYPES:
        return f"Unsupported content type: {content_type}"

    try:
        _rewind(uploaded_file)
        img = Image.open(uploaded_file)
        img.verify()
    except UnidentifiedImageError:
        return "Invalid image file"
    except Exception:  # noqa: BLE001
        return "Invalid image file"
    finally:
        _rewind(uploaded_file)

    return None


def _jsonify(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


def _require_event(event_id: str):
    if not ObjectId.is_valid(event_id):
        return None, None, Response({"error": "Invalid event_id"}, status=400)

    event_object_id = ObjectId(event_id)
    try:
        assert_database_ready()
        event = get_event_by_object_id(event_object_id)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return None, None, _database_error_response(exc)

    if not event:
        return None, None, Response({"error": "Event not found", "event_id": event_id}, status=404)

    return event_object_id, event, None


def _get_session_token(request) -> str:
    return request.COOKIES.get(settings.SESSION_COOKIE_NAME, "") or ""


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=int(settings.SESSION_TTL_SECONDS),
        httponly=bool(settings.SESSION_COOKIE_HTTPONLY),
        secure=bool(settings.SESSION_COOKIE_SECURE),
        samesite=str(settings.SESSION_COOKIE_SAMESITE),
    )


def _get_valid_session(request):
    token = _get_session_token(request)
    if not token:
        return None

    session = get_session_by_token(token)
    if not session:
        return None

    expires_at = session.get("expires_at")
    if expires_at and isinstance(expires_at, datetime):
        if expires_at <= datetime.now(timezone.utc):
            return None

    touch_session_by_token(token)
    return session


@api_view(["GET"])
def health(request):
    try:
        ping_database()
        assert_database_ready()
    except Exception as exc:  # noqa: BLE001
        return Response({"status": "error", "details": str(exc)}, status=500)

    return Response({"status": "ok"})


health.throttle_scope = "health"


@api_view(["GET"])
def event_detail(request, event_id: str):
    event_object_id, event, error_response = _require_event(event_id)
    if error_response is not None:
        return error_response

    try:
        photos = list_event_photos(event_object_id)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    response_items = []
    for photo in photos:
        image_url = _build_image_url(request, photo)
        response_items.append(
            {
                "image_id": photo.get("id"),
                "event_id": event_id,
                "image_name": photo.get("image_name"),
                "face": bool(photo.get("has_face")),
                "has_face": bool(photo.get("has_face")),
                "faces_processed": bool(photo.get("faces_processed")),
                "face_count": photo.get("face_count"),
                "image": image_url,
                "image_url": image_url,
            }
        )

    return Response({"event": _jsonify(event), "photos": response_items})


event_detail.throttle_scope = "read"


@api_view(["POST"])
def upload_images(request):
    serializer = UploadImagesSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": "Invalid request", "details": serializer.errors}, status=400)

    event_id = serializer.validated_data["event_id"]
    folder_id = serializer.validated_data.get("folder_id") or None
    images = request.FILES.getlist("images")

    if not images:
        return Response({"error": "At least one image is required"}, status=400)

    for uploaded_image in images:
        validation_error = _validate_image_upload(uploaded_image)
        if validation_error:
            return Response({"error": "Invalid upload", "details": validation_error}, status=400)

    event_object_id, _event, error_response = _require_event(event_id)
    if error_response is not None:
        return error_response

    existing_names = find_existing_event_image_names(event_object_id, [getattr(img, "name", None) for img in images])
    seen_names = set(existing_names)
    images_to_create = [img for img in images if not (getattr(img, "name", None) and img.name in existing_names)]

    image_ids = allocate_image_ids(len(images_to_create))
    id_iter = iter(image_ids)

    images_uploaded = 0
    total_faces_detected = 0
    images_without_face = 0
    images_not_uploaded = len(images) - len(images_to_create)
    reason_why_not_uploaded = [
        {"filename": name, "reason": f"image already uploaded: {name}"} for name in sorted(existing_names)
    ]

    data = []

    for uploaded_image in images_to_create:
        image_name = getattr(uploaded_image, "name", None)
        if image_name and image_name in seen_names:
            images_not_uploaded += 1
            reason_why_not_uploaded.append({"filename": image_name, "reason": f"image already uploaded: {image_name}"})
            continue
        try:
            image_id = next(id_iter)
        except StopIteration:
            break

        try:
            if settings.USE_ASYNC_FACE_PROCESSING:
                created_photo = create_unprocessed_event_photo(
                    event_object_id,
                    image_id,
                    uploaded_image,
                    folder_id=folder_id,
                )
                process_event_photo_faces.delay(created_photo["id"])
                if image_name:
                    seen_names.add(image_name)

                images_uploaded += 1
                data.append(
                    {
                        "image_name": image_name,
                        "event_id": event_id,
                        "folder_id": folder_id,
                        "image_id": image_id,
                        "face": None,
                        "has_face": None,
                        "queued_for_processing": True,
                    }
                )
                continue

            file_obj = getattr(uploaded_image, "file", uploaded_image)
            _rewind(file_obj)
            encodings = encode_faces_from_file(file_obj)
            face_count = len(encodings or [])
            has_face = face_count > 0

            if not has_face:
                images_without_face += 1

            _rewind(uploaded_image)
            created_photo = create_event_photo(
                event_object_id,
                image_id,
                uploaded_image,
                has_face=has_face,
                face_count=face_count,
                faces_processed=True,
                folder_id=folder_id,
            )
            if image_name:
                seen_names.add(image_name)

            if has_face:
                try:
                    inserted = insert_face_encodings_for_event(
                        event_object_id,
                        image_id,
                        [encoding.tobytes() for encoding in encodings],
                    )
                    total_faces_detected += inserted

                    # Match this photo against existing attendees so they see new photos without rescanning.
                    attendee_cursor = list_attendees_by_event_id(event_object_id)
                    try:
                        matches = match_photo_faces_to_attendees(
                            attendee_cursor,
                            encodings,
                            tolerance=settings.FACE_MATCH_TOLERANCE,
                        )
                    finally:
                        try:
                            attendee_cursor.close()
                        except Exception:  # noqa: BLE001
                            pass

                    uploaded_at = created_photo.get("uploaded_at")
                    if uploaded_at and matches:
                        upsert_photo_matches(
                            event_object_id,
                            image_id=image_id,
                            photo_uploaded_at=uploaded_at,
                            matches=matches,
                        )
                        # Push the new photo to each matched attendee's WebSocket.
                        image_url = _build_image_url(request, created_photo)
                        photo_payload = {
                            "image_id": image_id,
                            "image_url": image_url,
                            "image_name": image_name or f"Photo {image_id}",
                        }
                        for match in matches:
                            matched_attendee_id = match.get("attendee_id")
                            if matched_attendee_id:
                                notify_attendee_new_match(
                                    event_id=event_id,
                                    attendee_id=matched_attendee_id,
                                    photo=photo_payload,
                                )
                except Exception:  # noqa: BLE001
                    delete_event_face_encodings(event_object_id, image_id)
                    delete_photo_document(created_photo)
                    raise

            images_uploaded += 1
            data.append(
                {
                    "image_name": image_name,
                    "event_id": event_id,
                    "folder_id": folder_id,
                    "image_id": image_id,
                    "face": has_face,
                    "has_face": has_face,
                    "face_count": face_count,
                    "queued_for_processing": False,
                }
            )
        except Exception as exc:  # noqa: BLE001
            images_not_uploaded += 1
            reason_why_not_uploaded.append({"filename": image_name, "reason": str(exc)})

    return Response(
        {
            "images_uploaded": images_uploaded,
            "total_faces_detected": total_faces_detected,
            "images_without_face": images_without_face,
            "images_not_uploaded": images_not_uploaded,
            "reason_why_not_uploaded": reason_why_not_uploaded,
            "data": data,
        }
    )


upload_images.throttle_scope = "upload"


@api_view(["POST"])
def scan_face(request):
    serializer = ScanFaceSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": "Invalid request", "details": serializer.errors}, status=400)

    image = request.FILES.get("image")
    validation_error = _validate_image_upload(image)
    if validation_error:
        return Response({"error": "Invalid upload", "details": validation_error}, status=400)

    event_id = serializer.validated_data["event_id"]
    event_object_id, _event, error_response = _require_event(event_id)
    if error_response is not None:
        return error_response

    try:
        file_obj = getattr(image, "file", image)
        _rewind(file_obj)
        try:
            guest_encoding = encode_single_face_from_file(file_obj)
        except ValueError:
            return Response({"error": "Multiple faces detected"}, status=400)

        if guest_encoding is None:
            return Response({"error": "No face found"}, status=400)

        attendee_cursor = list_attendees_by_event_id(event_object_id)
        try:
            attendee_match = find_matching_attendee_id(
                attendee_cursor,
                guest_encoding,
                tolerance=settings.FACE_MATCH_TOLERANCE,
            )
        finally:
            try:
                attendee_cursor.close()
            except Exception:  # noqa: BLE001
                pass

        if attendee_match is not None:
            attendee_id, _distance = attendee_match
            touch_attendee(event_object_id, attendee_id)
        else:
            attendee_id = create_attendee(event_object_id, guest_encoding.tobytes(), expires_at=None)

        # Ensure the response has a session cookie (token maps to attendee_id+event_id in Mongo).
        existing_session = _get_valid_session(request)
        existing_token = _get_session_token(request)
        if (
            existing_session
            and existing_session.get("attendee_id") == attendee_id
            and existing_session.get("event_id") == event_object_id
            and existing_token
        ):
            session_token = existing_token
        else:
            session_token = create_session(event_object_id, attendee_id, ttl_seconds=int(settings.SESSION_TTL_SECONDS))

        # Backfill photo matches for this attendee only when needed.
        if count_photo_matches_for_attendee(event_object_id, attendee_id) == 0:
            cursor = list_face_encodings_by_event_id(event_object_id)
            try:
                image_matches = find_matching_image_ids_with_distances(
                    cursor,
                    guest_encoding,
                    tolerance=settings.FACE_MATCH_TOLERANCE,
                )
            finally:
                try:
                    cursor.close()
                except Exception:  # noqa: BLE001
                    pass

            if settings.MAX_MATCHED_PHOTOS and len(image_matches) > settings.MAX_MATCHED_PHOTOS:
                image_matches = image_matches[: settings.MAX_MATCHED_PHOTOS]

            image_ids = [image_id for image_id, _dist in image_matches]
            photo_docs = get_photos_by_image_ids(event_object_id, image_ids) if image_ids else []
            uploaded_at_by_id = {int(p.get("id")): p.get("uploaded_at") for p in photo_docs if p.get("id") is not None}

            items = []
            for image_id, distance in image_matches:
                uploaded_at = uploaded_at_by_id.get(int(image_id))
                if not uploaded_at:
                    continue
                items.append(
                    {
                        "image_id": int(image_id),
                        "photo_uploaded_at": uploaded_at,
                        "distance": float(distance),
                        "confidence": max(0.0, 1.0 - float(distance)),
                    }
                )

            upsert_attendee_photo_matches(event_object_id, attendee_id=attendee_id, items=items)

        matched_count = count_photo_matches_for_attendee(event_object_id, attendee_id)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return Response({"error": "Face scan failed", "details": str(exc)}, status=400)

    response = Response({"success": True, "attendee_id": attendee_id, "matched_count": matched_count})
    _set_session_cookie(response, session_token)
    return response


scan_face.throttle_scope = "scan"


@api_view(["GET"])
def my_photos(request):
    # Preferred flow: resolve identity from secure session cookie.
    session = _get_valid_session(request)
    if session:
        event_object_id = session.get("event_id")
        attendee_id = session.get("attendee_id")
        if not event_object_id or not attendee_id:
            return Response({"error": "Invalid session"}, status=401)

        limit_raw = request.query_params.get("limit") or "50"
        try:
            limit = max(1, min(200, int(limit_raw)))
        except ValueError:
            limit = 50

        before = _parse_iso_datetime(request.query_params.get("before") or "")
        since = _parse_iso_datetime(request.query_params.get("since") or "")

        try:
            assert_database_ready()
            matches = list_photo_matches_for_attendee(
                event_object_id,
                str(attendee_id),
                limit=limit,
                before=before,
                since=since,
            )
            image_ids = [int(m.get("image_id")) for m in matches if m.get("image_id") is not None]
            photo_docs = get_photos_by_image_ids(event_object_id, image_ids) if image_ids else []
        except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
            return _database_error_response(exc)

        photo_by_id = {int(p.get("id")): p for p in photo_docs if p.get("id") is not None}
        photos = []
        for m in matches:
            image_id = int(m.get("image_id"))
            photo = photo_by_id.get(image_id)
            if not photo:
                continue
            image_url = _build_image_url(request, photo)
            uploaded_at = photo.get("uploaded_at")
            photos.append(
                {
                    "id": image_id,
                    "url": image_url,
                    "created_at": uploaded_at.isoformat() if isinstance(uploaded_at, datetime) else None,
                }
            )

        next_before = None
        if photos:
            last_uploaded_at = photo_by_id.get(photos[-1]["id"], {}).get("uploaded_at")
            if isinstance(last_uploaded_at, datetime):
                next_before = last_uploaded_at.isoformat()

        return Response({"success": True, "count": len(photos), "photos": photos, "next_before": next_before})

    # Legacy fallback: allow the older scan_id-based flow.
    serializer = MyPhotosSerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response({"error": "Invalid request", "details": serializer.errors}, status=400)

    event_id = serializer.validated_data["event_id"]
    scan_id = serializer.validated_data["scan_id"]
    event_object_id, _event, error_response = _require_event(event_id)
    if error_response is not None:
        return error_response

    try:
        # Check if scan_id is actually an attendee_id (e.g., guest_...)
        if scan_id.startswith("guest_"):
            matches = list_photo_matches_for_attendee(
                event_object_id,
                scan_id,
                limit=100,
            )
            image_ids = [int(m.get("image_id")) for m in matches if m.get("image_id") is not None]
            photo_docs = get_photos_by_image_ids(event_object_id, image_ids) if image_ids else []

            photo_by_id = {int(p.get("id")): p for p in photo_docs if p.get("id") is not None}
            matched_photos = []
            for m in matches:
                img_id = int(m.get("image_id"))
                photo = photo_by_id.get(img_id)
                if not photo:
                    continue
                image_url = _build_image_url(request, photo)
                matched_photos.append(
                    {
                        "image_id": img_id,
                        "image_name": photo.get("image_name"),
                        "image_url": image_url,
                        "image": image_url,
                        "has_face": bool(photo.get("has_face")),
                    }
                )
            return Response({"matched_count": len(matched_photos), "matched_images": matched_photos})

        from .repositories import get_scan

        scan = get_scan(event_object_id, scan_id)
        if not scan:
            return Response({"error": "Not found"}, status=404)

        matched_image_ids = [int(i) for i in (scan.get("matched_image_ids") or [])]
        photo_docs = get_photos_by_image_ids(event_object_id, matched_image_ids) if matched_image_ids else []
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    photo_by_id = {int(p.get("id")): p for p in photo_docs if p.get("id") is not None}
    matched_photos = []
    for image_id in matched_image_ids:
        photo = photo_by_id.get(int(image_id))
        if not photo:
            continue
        image_url = _build_image_url(request, photo)
        matched_photos.append(
            {
                "image_id": photo.get("id"),
                "image_name": photo.get("image_name"),
                "image_url": image_url,
                "image": image_url,
                "has_face": bool(photo.get("has_face")),
            }
        )

    return Response({"matched_count": len(matched_photos), "matched_images": matched_photos})


my_photos.throttle_scope = "read"


@api_view(["DELETE"])
def delete_photo(request, id: int):
    if not settings.ADMIN_TOKEN:
        return Response({"error": "Admin token not configured"}, status=403)

    provided = request.headers.get("X-Admin-Token") or request.META.get("HTTP_X_ADMIN_TOKEN") or ""
    if provided != settings.ADMIN_TOKEN:
        return Response({"error": "Forbidden"}, status=403)

    try:
        assert_database_ready()
        deleted = delete_photo_by_image_id(int(id))
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    if not deleted:
        return Response({"error": "Not found"}, status=404)

    return Response({"success": True})


delete_photo.throttle_scope = "upload"
