# from django.conf import settings
# from django.conf.urls.static import static
# from django.urls import include, path


# urlpatterns = [
#     path("api/", include("recognition.urls")),
# ]

# if settings.DEBUG:
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin-django", admin.site.urls),   # Django Admin Panel
    path("api/", include("recognition.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
