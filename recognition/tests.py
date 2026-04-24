from unittest.mock import patch
import io

from django.test import SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
import numpy as np
from PIL import Image
from rest_framework.test import APIRequestFactory

from config.mongo import _extract_database_name, _normalize_mongodb_uri
from recognition.views import upload_images


class MongoUriTests(SimpleTestCase):
    def test_markdown_wrapped_uri_is_normalized(self):
        raw_uri = (
            "mongodb+srv://mohammedmizhabdk_db_user:BMV7x8.q4U5!"
            "[gkk@cluster0.qimfzzm.mongodb.net](mailto:gkk@cluster0.qimfzzm.mongodb.net)/photo-ceremony"
        )

        self.assertEqual(
            _normalize_mongodb_uri(raw_uri),
            "mongodb+srv://mohammedmizhabdk_db_user:BMV7x8.q4U5!gkk@cluster0.qimfzzm.mongodb.net/photo-ceremony",
        )
        self.assertEqual(_extract_database_name(raw_uri), "photo-ceremony")


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
        self.assertEqual(response.data["error"], "Invalid request")
        self.assertIn("event_id", response.data["details"])

    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_returns_404_when_event_missing(self, mock_assert_ready, mock_get_event):
        mock_get_event.return_value = None

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [SimpleUploadedFile("a.jpg", self._make_test_jpeg(), content_type="image/jpeg")],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "Event not found")
        self.assertEqual(response.data["event_id"], "507f1f77bcf86cd799439011")
        mock_assert_ready.assert_called_once()

    @patch("recognition.views.create_event_photo")
    @patch("recognition.views.insert_face_encodings_for_event")
    @patch("recognition.views.encode_faces_from_file")
    @patch("recognition.views.allocate_image_ids")
    @patch("recognition.views.find_existing_event_image_names")
    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_saves_encodings_for_event(
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
        mock_allocate_image_ids.return_value = [1, 2]
        mock_create_event_photo.side_effect = [
            {"id": 1, "has_face": True, "image_url": "/media/public/x.jpg"},
            {"id": 2, "has_face": True, "image_url": "/media/public/y.jpg"},
        ]
        mock_encode_faces_from_file.return_value = [np.zeros(128, dtype=np.float64)]
        mock_insert_face_encodings.return_value = 1

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [
                    SimpleUploadedFile("a.jpg", self._make_test_jpeg(), content_type="image/jpeg"),
                    SimpleUploadedFile("b.jpg", self._make_test_jpeg(), content_type="image/jpeg"),
                ],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["images_uploaded"], 2)
        self.assertEqual(response.data["total_faces_detected"], 2)
        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(response.data["data"][0]["event_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(response.data["data"][0]["image_id"], 1)
        self.assertEqual(response.data["data"][0]["image_name"], "a.jpg")
        self.assertEqual(response.data["data"][0]["has_face"], True)
        self.assertEqual(mock_insert_face_encodings.call_count, 2)

    @patch("recognition.views.create_event_photo")
    @patch("recognition.views.encode_faces_from_file")
    @patch("recognition.views.allocate_image_ids")
    @patch("recognition.views.find_existing_event_image_names")
    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_skips_duplicates_before_encoding(
        self,
        mock_assert_ready,
        mock_get_event,
        mock_find_existing_names,
        mock_allocate_image_ids,
        mock_encode_faces_from_file,
        mock_create_event_photo,
    ):
        mock_get_event.return_value = {"_id": object()}
        mock_find_existing_names.return_value = {"a.jpg"}

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [SimpleUploadedFile("a.jpg", self._make_test_jpeg(), content_type="image/jpeg")],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["images_uploaded"], 0)
        self.assertEqual(response.data["images_not_uploaded"], 1)
        self.assertEqual(len(response.data["data"]), 0)
        mock_allocate_image_ids.assert_called_once_with(0)
        self.assertEqual(mock_encode_faces_from_file.call_count, 0)
        self.assertEqual(mock_create_event_photo.call_count, 0)
