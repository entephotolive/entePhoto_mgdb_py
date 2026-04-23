import face_recognition
import face_recognition
import numpy as np
from bson.objectid import ObjectId
from django.core.exceptions import ImproperlyConfigured
from pymongo.errors import PyMongoError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from config.mongo import assert_database_ready
from .repositories import (
    allocate_image_id,
    create_face_encoding_for_event,
    create_event_photo,
    delete_event_face_encodings,
    delete_event_photo,
    delete_wedding as delete_wedding_document,
    event_image_name_exists,
    get_event_by_object_id,
    get_photos_by_image_ids,
    list_face_encodings_by_event_id,
    list_event_photos,
    list_weddings as list_wedding_documents,
)
from .serializers import ScanFaceSerializer, UploadImagesSerializer
from .services.face_match import match_faces


def _database_error_response(exc):
    return Response({"error": "Database operation failed", "details": str(exc)}, status=500)

def _build_image_url(request, image_document):
    image_url = image_document.get("image_url") or ""
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url
    return request.build_absolute_uri(image_url)


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

    images_uploaded = 0
    total_faces_detected = 0
    images_without_face = 0
    images_not_uploaded = 0
    reason_why_not_uploaded = []

    event_object_id = ObjectId(event_id)

    try:
        assert_database_ready()
        event = get_event_by_object_id(event_object_id)
        if not event:
            return Response({"error": "Event not found", "event_id": event_id}, status=404)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    data = []

    for uploaded_image in images:
        try:
            image_name = getattr(uploaded_image, "name", None)
            if image_name and event_image_name_exists(event_object_id, image_name):
                images_not_uploaded += 1
                reason_why_not_uploaded.append(
                    {"filename": image_name, "reason": f"image already uploaded: {image_name}"}
                )
                continue

            image_id = allocate_image_id()

            file_obj = getattr(uploaded_image, "file", uploaded_image)
            try:
                file_obj.seek(0)
            except Exception:  # noqa: BLE001
                pass

            image_array = face_recognition.load_image_file(file_obj)
            face_locations = face_recognition.face_locations(image_array)
            encodings = face_recognition.face_encodings(image_array, face_locations)

            has_face = bool(encodings)
            if not encodings:
                images_without_face += 1

            # Ensure we persist the uploaded file from the beginning.
            try:
                file_obj.seek(0)
            except Exception:  # noqa: BLE001
                pass
            try:
                uploaded_image.seek(0)
            except Exception:  # noqa: BLE001
                pass
            try:
                uploaded_image.file.seek(0)
            except Exception:  # noqa: BLE001
                pass

            created_photo = create_event_photo(
                event_object_id=event_object_id,
                image_id=image_id,
                uploaded_file=uploaded_image,
                has_face=has_face,
                folder_id=folder_id,
            )

            if encodings:
                try:
                    for encoding in encodings:
                        create_face_encoding_for_event(
                            image_id=image_id,
                            event_object_id=event_object_id,
                            encoding_bytes=encoding.tobytes(),
                        )
                    total_faces_detected += len(encodings)
                except Exception:  # noqa: BLE001
                    # Roll back the photo doc + stored file if we can't persist encodings.
                    delete_event_face_encodings(event_object_id, image_id)
                    delete_event_photo(created_photo)
                    raise

            images_uploaded += 1
            data.append(
                {
                    "image_name": image_name,
                    "event_id": event_id,
                    "folder_id": folder_id,
                    "image_id": image_id,
                    "face": has_face,
                }
            )
        except Exception as exc:  # noqa: BLE001
            images_not_uploaded += 1
            reason_why_not_uploaded.append({"filename": getattr(uploaded_image, "name", None), "reason": str(exc)})

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


@api_view(["POST"])
def scan_face(request):
    serializer = ScanFaceSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": "Invalid request", "details": serializer.errors}, status=400)

    image = request.FILES.get("image")
    if not image:
        return Response({"error": "Image is required"}, status=400)

    event_id = serializer.validated_data["event_id"]
    event_object_id = ObjectId(event_id)

    try:
        assert_database_ready()
        event = get_event_by_object_id(event_object_id)
        if not event:
            return Response({"error": "Event not found", "event_id": event_id}, status=404)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    try:
        file_obj = getattr(image, "file", image)
        try:
            file_obj.seek(0)
        except Exception:  # noqa: BLE001
            pass

        guest_image = face_recognition.load_image_file(file_obj)
        guest_encodings = face_recognition.face_encodings(guest_image)

        if not guest_encodings:
            return Response({"error": "No face found"}, status=400)

        guest_encoding = guest_encodings[0]
        matched_image_ids = set()

        for face_document in list_face_encodings_by_event_id(event_object_id):
            known_encoding = np.frombuffer(face_document["encoding"], dtype=np.float64)
            result = match_faces([known_encoding.tobytes()], guest_encoding)

            if result[0]:
                matched_image_ids.add(face_document["image_id"])
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return Response({"error": "Face scan failed", "details": str(exc)}, status=400)

    # Resolve matched image IDs → photo documents → image URLs
    matched_photos = []
    if matched_image_ids:
        try:
            photo_docs = get_photos_by_image_ids(event_object_id, list(matched_image_ids))
            for photo in photo_docs:
                matched_photos.append(
                    {
                        "image_id": photo.get("id"),
                        "image_name": photo.get("image_name"),
                        "image_url": _build_image_url(request, photo),
                        "has_face": bool(photo.get("has_face")),
                    }
                )
        except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
            return _database_error_response(exc)

    return Response(
        {
            "matched_count": len(matched_photos),
            "matched_images": matched_photos,
        }
    )


@api_view(["GET"])
def list_weddings(request):
    try:
        assert_database_ready()
        weddings = list_wedding_documents()
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    data = []
    for wedding in weddings:
        created_by = wedding.get("created_by") or {}
        data.append(
            {
                "id": str(wedding["id"]),
                "title": wedding["name"],
                "date": wedding["date"].isoformat() if wedding.get("date") else None,
                "location": wedding.get("location") or "No location",
                "createdBy": {
                    "name": created_by.get("username") or "Unknown",
                },
                "photoCount": wedding.get("photo_count", 0),
            }
        )

    return Response(data)


@api_view(["DELETE"])
def delete_wedding(request, id):
    try:
        assert_database_ready()
        deleted = delete_wedding_document(id)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    if not deleted:
        return Response({"error": "Not found"}, status=404)

    return Response({"success": True})


@api_view(["GET"])
def get_images_by_event(request, event_id):
    if not ObjectId.is_valid(event_id):
        return Response({"error": "Invalid event_id"}, status=400)

    event_object_id = ObjectId(event_id)
    try:
        assert_database_ready()
        event = get_event_by_object_id(event_object_id)
        if not event:
            return Response({"error": "Event not found", "event_id": event_id}, status=404)
    except (PyMongoError, ImproperlyConfigured, ValueError) as exc:
        return _database_error_response(exc)

    photos = list_event_photos(event_object_id)
    response_items = []
    for photo in photos:
        response_items.append(
            {
                "image_id": photo.get("id"),
                "event_id": event_id,
                "image_name": photo.get("image_name"),
                "face": bool(photo.get("has_face")),
                "image": _build_image_url(request, photo),
            }
        )

    return Response(response_items)
