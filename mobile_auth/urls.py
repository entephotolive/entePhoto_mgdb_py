from django.urls import path
from .views import GoogleMobileLoginAPIView, PhotographerFoldersAPIView

urlpatterns = [
    path("auth/google/", GoogleMobileLoginAPIView.as_view()),
    path("folders/", PhotographerFoldersAPIView.as_view()),
]


