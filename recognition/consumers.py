"""
WebSocket consumer for real-time photo match notifications.

Each attendee connects to a private channel group:
    photo_matches_{event_id}_{attendee_id}

When the server detects a new match for that attendee (either during upload
or face-scan), it calls notify_attendee_new_match() which broadcasts a
`new_photo` message to that group. All connected clients for that attendee
receive the photo instantly without polling.
"""
import json

from channels.generic.websocket import AsyncWebsocketConsumer


class PhotoMatchConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        event_id = self.scope["url_route"]["kwargs"]["event_id"]
        attendee_id = self.scope["url_route"]["kwargs"]["attendee_id"]

        # One private group per attendee per event
        self.group_name = f"photo_matches_{event_id}_{attendee_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Called by channel layer when a new photo match is broadcast
    async def new_photo(self, event):
        await self.send(text_data=json.dumps({
            "type": "new_photo",
            "photo": event["photo"],
        }))
