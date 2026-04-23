from celery import shared_task
from pymongo.errors import PyMongoError

from .repositories import create_face_encoding, create_face_encoding_for_event, get_image_by_public_id
from .services.face_encode import encode_faces


@shared_task
def process_image_faces(image_id):
    try:
        image_document = get_image_by_public_id(image_id)
        if not image_document:
            return "Image not found"

        image_path = image_document.get("image_path")
        if not image_path:
            return "Image has no path"

        encodings = encode_faces(image_path)

        if not encodings:
            return "No faces found"

        for encoding in encodings:
            if image_document.get("event_id") is not None:
                create_face_encoding_for_event(
                    image_id=image_document["id"],
                    event_object_id=image_document["event_id"],
                    encoding_bytes=encoding.tobytes(),
                )
            else:
                create_face_encoding(
                    image_id=image_document["id"],
                    wedding_id=image_document["wedding_id"],
                    encoding_bytes=encoding.tobytes(),
                )

        return f"{len(encodings)} faces saved"
    except PyMongoError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
