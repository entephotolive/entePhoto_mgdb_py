FROM python:3.10

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --upgrade pip
RUN pip install dlib-bin==20.0.1
RUN pip install --prefer-binary -r requirements.txt

CMD ["sh", "-c", "python manage.py ensure_mongo_indexes && gunicorn config.wsgi:application --bind 0.0.0.0:8000"]
