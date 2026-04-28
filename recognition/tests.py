from unittest.mock import patch
import io
import os

from django.test import SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
import numpy as np
from PIL import Image
from rest_framework.test import APIRequestFactory

from config.mongo import _extract_database_name, _normalize_mongodb_uri
from recognition.views import upload_images


# Read MongoDB URL only from .env
MONGODB_URI = os.getenv("MONGODB_URI")


class MongoUriTests(SimpleTestCase):
    def test_env_uri_is_loaded(self):
        self.assertIsNotNone(MONGODB_URI)
        self.assertIn("mongodb+srv://", MONGODB_URI)
        self.assertEqual(_extract_database_name(MONGODB_URI), "entephoto-db")


class UploadImagesViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _make_test_jpeg(self) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buf, format="JPEG")
        return buf.getvalue()

    def test_upload_images_rejects_invalid_event_id(self):
        request = self.factory.post(
            "/api/upload-images/",
            {"event_id": "not-an-objectid"},
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 400)

    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_returns_404_when_event_missing(
        self, mock_assert_ready, mock_get_event
    ):
        mock_get_event.return_value = None

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [
                    SimpleUploadedFile(
                        "a.jpg",
                        self._make_test_jpeg(),
                        content_type="image/jpeg"
                    )
                ],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 404)

    @patch("recognition.views.create_event_photo")
    @patch("recognition.views.insert_face_encodings_for_event")
    @patch("recognition.views.encode_faces_from_file")
    @patch("recognition.views.allocate_image_ids")
    @patch("recognition.views.find_existing_event_image_names")
    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_success(
        self,
        mock_assert_ready,
        mock_get_event,
        mock_find_existing_names,
        mock_allocate_image_ids,
        mock_encode_faces_from_file,
        mock_insert_face_encodings,
        mock_create_event_photo,
    ):
        mock_get_event.return_value = {"_id": object()}
        mock_find_existing_names.return_value = set()
        mock_allocate_image_ids.return_value = [1]

        mock_create_event_photo.return_value = {
            "id": 1,
            "has_face": True,
            "image_url": "/media/public/x.jpg",
        }

        mock_encode_faces_from_file.return_value = [np.zeros(128)]
        mock_insert_face_encodings.return_value = 1

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [
                    SimpleUploadedFile(
                        "a.jpg",
                        self._make_test_jpeg(),
                        content_type="image/jpeg"
                    )
                ],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 200)
