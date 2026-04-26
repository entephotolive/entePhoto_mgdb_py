# Live Event Face-Photo Matching Backend (Django + MongoDB)

## Features
- Upload event photos/images (bulk)
- Extract and store face encodings in MongoDB (sync by default; optional Celery async)
- Scan a guest selfie and instantly return matched event photos
- Event-based photo grouping (Mongo `events` collection by ObjectId)
- Public media storage under `media/public/<event_id>/...`
- Rate-limited APIs and upload validation

## API Endpoints
- `POST /api/upload-images/` (multipart: `event_id`, `folder_id` optional, `images[]`)
- `POST /api/scan-face/` (multipart: `event_id`, `image`)
- `GET /api/my-photos/?event_id=<id>&scan_id=<id>`
- `GET /api/event/<event_id>/`
- `DELETE /api/photo/<id>/` (requires `X-Admin-Token` when `ADMIN_TOKEN` is set)
- `GET /api/health/`

## Data Layer
- MongoDB Atlas via `pymongo`
- Central connection module in `config/mongo.py`
- Process-wide cached `MongoClient`
- Automatic index creation for events/photos/face encodings/counters (+ guest scans)
- No SQL migrations or relational database dependencies (Django ORM disabled)

## Environment Variables
```bash
MONGODB_URI=
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=*
TIME_ZONE=UTC

# Upload + matching tuning
MAX_UPLOAD_MB=10
FACE_MATCH_TOLERANCE=0.5
MAX_MATCHED_PHOTOS=200
ALLOWED_IMAGE_MIME_TYPES=image/jpeg,image/png,image/webp

# Rate limits (DRF scoped throttles)
UPLOAD_RATE=30/min
SCAN_RATE=30/min
READ_RATE=120/min
HEALTH_RATE=120/min

# Optional async processing
CELERY_BROKER_URL=
CELERY_RESULT_BACKEND=
USE_ASYNC_FACE_PROCESSING=False

# Optional admin protection for DELETE
ADMIN_TOKEN=
```

## Local Setup
```bash
pip install -r requirements.txt
python manage.py ensure_mongo_indexes
python manage.py runserver
```

## Production Startup
```bash
python manage.py ensure_mongo_indexes
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```
