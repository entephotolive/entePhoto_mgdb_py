from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication
from bson import ObjectId
from datetime import datetime

from .db import users_collection, folders_collection


class GoogleMobileLoginAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        google_token = request.data.get("id_token")

        if not google_token:
            return Response(
                {"detail": "id_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = id_token.verify_oauth2_token(
                google_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except ValueError:
            return Response(
                {"detail": "Invalid Google token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        google_sub = payload.get("sub")
        email = payload.get("email", "").lower()
        name = payload.get("name", "")
        picture = payload.get("picture", "")
        email_verified = payload.get("email_verified", False)

        if not email or not email_verified:
            return Response(
                {"detail": "Google email is not verified"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        now = datetime.utcnow()

        user = users_collection.find_one({
            "$or": [
                {"google_sub": google_sub},
                {"email": email},
            ]
        })

        if user:
            users_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "google_sub": google_sub,
                        "name": name,
                        "avatarUrl": picture,
                        "provider": "google",
                        "updatedAt": now,
                        "lastLogin": now,
                    }
                },
            )
            photographer_id = str(user["_id"])
        else:
            result = users_collection.insert_one({
                "google_sub": google_sub,
                "email": email,
                "name": name,
                "avatarUrl": picture,
                "provider": "google",
                "role": "photographer",
                "isBlocked": False,
                "specializations": [],
                "createdAt": now,
                "updatedAt": now,
                "lastLogin": now,
            })
            photographer_id = str(result.inserted_id)

        refresh = RefreshToken()
        refresh["photographer_id"] = photographer_id
        refresh["email"] = email
        refresh["role"] = "photographer"

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "photographer": {
                "id": photographer_id,
                "email": email,
                "name": name,
                "picture": picture,
            },
        })


class PhotographerFoldersAPIView(APIView):
    authentication_classes = [JWTStatelessUserAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        photographer_id = request.auth.get("photographer_id")

        if not photographer_id:
            return Response(
                {"detail": "Invalid token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        folders = folders_collection.find({
            "createdBy": ObjectId(photographer_id),
        }).sort("createdAt", -1)

        data = []

        for folder in folders:
            data.append({
                "id": str(folder["_id"]),
                "name": folder.get("name"),
                "slug": folder.get("slug"),
                "photoCount": folder.get("photoCount", 0),
                "eventId": str(folder.get("eventId")) if folder.get("eventId") else None,
                "createdAt": folder.get("createdAt"),
            })

        return Response({
            "folders": data,
        })