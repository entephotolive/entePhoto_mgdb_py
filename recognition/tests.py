from unittest.mock import patch

from django.test import SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
import numpy as np
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
                "images": [SimpleUploadedFile("a.jpg", b"fake", content_type="image/jpeg")],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "Event not found")
        self.assertEqual(response.data["event_id"], "507f1f77bcf86cd799439011")
        mock_assert_ready.assert_called_once()

    @patch("recognition.views.create_face_encoding_for_event")
    @patch("recognition.views.face_recognition.face_encodings")
    @patch("recognition.views.face_recognition.face_locations")
    @patch("recognition.views.face_recognition.load_image_file")
    @patch("recognition.views.create_event_photo")
    @patch("recognition.views.allocate_image_id")
    @patch("recognition.views.event_image_name_exists")
    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_saves_encodings_for_event(
        self,
        mock_assert_ready,
        mock_get_event,
        mock_event_image_name_exists,
        mock_allocate_image_id,
        mock_create_event_photo,
        mock_load_image,
        mock_face_locations,
        mock_face_encodings,
        mock_create_encoding,
    ):
        mock_get_event.return_value = {"_id": object()}
        mock_event_image_name_exists.return_value = False
        mock_allocate_image_id.side_effect = [1, 2]
        mock_create_event_photo.side_effect = [
            {"id": 1, "has_face": True, "image_url": "/media/public/x.jpg"},
            {"id": 2, "has_face": True, "image_url": "/media/public/y.jpg"},
        ]
        mock_load_image.return_value = object()
        mock_face_locations.return_value = [(0, 0, 1, 1)]
        mock_face_encodings.return_value = [np.zeros(128, dtype=np.float64)]

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [
                    SimpleUploadedFile("a.jpg", b"fake", content_type="image/jpeg"),
                    SimpleUploadedFile("b.jpg", b"fake", content_type="image/jpeg"),
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
        self.assertEqual(response.data["data"][0]["face"], True)
        self.assertEqual(mock_create_encoding.call_count, 2)

    @patch("recognition.views.face_recognition.load_image_file")
    @patch("recognition.views.allocate_image_id")
    @patch("recognition.views.event_image_name_exists")
    @patch("recognition.views.get_event_by_object_id")
    @patch("recognition.views.assert_database_ready")
    def test_upload_images_skips_duplicates_before_encoding(
        self,
        mock_assert_ready,
        mock_get_event,
        mock_event_image_name_exists,
        mock_allocate_image_id,
        mock_load_image,
    ):
        mock_get_event.return_value = {"_id": object()}
        mock_event_image_name_exists.return_value = True

        request = self.factory.post(
            "/api/upload-images/",
            {
                "event_id": "507f1f77bcf86cd799439011",
                "images": [SimpleUploadedFile("a.jpg", b"fake", content_type="image/jpeg")],
            },
            format="multipart",
        )

        response = upload_images(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["images_uploaded"], 0)
        self.assertEqual(response.data["images_not_uploaded"], 1)
        self.assertEqual(len(response.data["data"]), 0)
        self.assertEqual(mock_allocate_image_id.call_count, 0)
        self.assertEqual(mock_load_image.call_count, 0)
