from django.urls import path
from .views import (
    delete_photo,
    event_detail,
    health,
    my_photos,
    scan_face,
    upload_images,
    cleanup_expired_events,
)

urlpatterns = [
    path("upload-images/", upload_images),
    path("scan-face/", scan_face),
    path("my-photos/", my_photos),
    path("event/<str:event_id>/", event_detail),
    path("photo/<int:id>/", delete_photo),
    path("health/", health),
    path("cron/cleanup-expired-events/", cleanup_expired_events),
]
