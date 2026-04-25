from celery import shared_task
from django.conf import settings
from pymongo.errors import PyMongoError

from .repositories import (
    insert_face_encodings_for_event,
    list_attendees_by_event_id,
    mark_event_photo_processed_without_faces,
    promote_event_photo_to_has_face,
    upsert_photo_matches,
    update_event_photo_face_metadata,
    find_photo_by_image_id,
)
from .services.face_encode import encode_faces_from_path
from .services.face_match import match_photo_faces_to_attendees
from .notify import notify_attendee_new_match


@shared_task
def process_event_photo_faces(image_id: int):
    try:
        photo_document = find_photo_by_image_id(image_id)
        if not photo_document:
            return "Photo not found"

        image_path = photo_document.get("image_path")
        if not image_path:
            return "Photo has no path"

        event_id = photo_document.get("event_id")
        if event_id is None:
            return "Photo has no event_id"

        encodings = encode_faces_from_path(image_path)
        face_count = len(encodings or [])

        if not encodings:
            mark_event_photo_processed_without_faces(event_id, image_id)
            return "No faces found"

        inserted = insert_face_encodings_for_event(event_id, image_id, [e.tobytes() for e in encodings])

        attendee_cursor = list_attendees_by_event_id(event_id)
        try:
            matches = match_photo_faces_to_attendees(
                attendee_cursor,
                encodings,
                tolerance=getattr(settings, "FACE_MATCH_TOLERANCE", 0.5),
            )
        finally:
            try:
                attendee_cursor.close()
            except Exception:  # noqa: BLE001
                pass

        uploaded_at = photo_document.get("uploaded_at")
        if uploaded_at and matches:
            upsert_photo_matches(event_id, image_id=image_id, photo_uploaded_at=uploaded_at, matches=matches)

            # Push the new photo to each matched attendee's WebSocket.
            image_url = photo_document.get("image_url", "")
            event_id_str = str(event_id)
            photo_payload = {
                "image_id": image_id,
                "image_url": image_url,
                "image_name": photo_document.get("image_name") or f"Photo {image_id}",
            }
            for match in matches:
                matched_attendee_id = match.get("attendee_id")
                if matched_attendee_id:
                    notify_attendee_new_match(
                        event_id=event_id_str,
                        attendee_id=matched_attendee_id,
                        photo=photo_payload,
                    )

        # Promote the photo document to the "has face" collection if needed.
        if photo_document.get("_collection") != "image_with_face":
            promote_event_photo_to_has_face(event_id, image_id, face_count=face_count)
        else:
            update_event_photo_face_metadata(event_id, image_id, face_count=face_count)

        return f"{inserted} face encodings saved"
    except PyMongoError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
