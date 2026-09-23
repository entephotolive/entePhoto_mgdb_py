from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import GoogleMobileLoginAPIView, PhotographerEventsAPIView

urlpatterns = [
    path("auth/google/", GoogleMobileLoginAPIView.as_view()),
    path("auth/token/refresh/", TokenRefreshView.as_view()),
    path("events/", PhotographerEventsAPIView.as_view()),
]


