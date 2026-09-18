from django.urls import path
from .views import GoogleMobileLoginAPIView, PhotographerFoldersAPIView

urlpatterns = [
    path("auth/google/", GoogleMobileLoginAPIView.as_view()),
    path("events/", PhotographerFoldersAPIView.as_view()),
]


