# Wedding Face Recognition System

## Features
- Upload wedding images
- Auto face detection and MongoDB-backed face encoding storage
- Face matching against saved encodings
- Django REST API with MongoDB Atlas
- Celery background processing for face extraction

## Data Layer
- MongoDB Atlas via `pymongo`
- Central connection module in `config/mongo.py`
- Process-wide cached `MongoClient`
- Automatic index creation for weddings, images, face encodings, users, and counters
- No SQL migrations or relational database dependencies

## Environment Variables
```bash
MONGODB_URI=mongodb+srv://mohammedmizhabdk_db_user:BMV7x8.q4U5![gkk@cluster0.qimfzzm.mongodb.net](mailto:gkk@cluster0.qimfzzm.mongodb.net)/photo-ceremony
SECRET_KEY=django-insecure-fallback-dev-key-change-in-production
DEBUG=True
ALLOWED_HOSTS=*
TIME_ZONE=UTC
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
