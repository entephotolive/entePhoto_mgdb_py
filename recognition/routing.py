from django.urls import re_path
from .consumers import PhotoMatchConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/matches/(?P<event_id>[^/]+)/(?P<attendee_id>[^/]+)/$",
        PhotoMatchConsumer.as_asgi(),
    ),
]
