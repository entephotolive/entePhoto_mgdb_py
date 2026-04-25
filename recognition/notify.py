"""
Utility to broadcast a new photo match to all connected WebSocket clients
for a specific attendee.

Called from views.py (synchronous HTTP context) after upload_images matches
a new photo, and from tasks.py (Celery async context) after async processing.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def notify_attendee_new_match(event_id: str, attendee_id: str, photo: dict) -> None:
    """
    Push a single new matched photo to the attendee's WebSocket group.

    Args:
        event_id:    MongoDB ObjectId string for the event.
        attendee_id: The attendee's string ID (e.g., "guest_...").
        photo:       Dict with keys: image_id, image_url, image_name.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # Channels not configured; silently skip

    group_name = f"photo_matches_{event_id}_{attendee_id}"
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "new_photo",
            "photo": photo,
        },
    )
