from django.urls import path
from .views import (
    delete_wedding,
    get_images_by_event,
    list_weddings,
    scan_face,
    upload_images,
)

urlpatterns = [
    path("upload-images/", upload_images),
    path("scan-face/", scan_face),
    path("weddings/", list_weddings),
    path("delete-wedding/<int:id>/", delete_wedding),
    path("images/<str:event_id>/", get_images_by_event),
]
