import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from recognition.routing import websocket_urlpatterns

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialize Django ASGI app first so the app registry loads before routing.
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # No AllowedHostsOriginValidator — we use CORS_ALLOW_ALL_ORIGINS=True for dev.
        # In production, wrap with AllowedHostsOriginValidator and pin ALLOWED_HOSTS.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
