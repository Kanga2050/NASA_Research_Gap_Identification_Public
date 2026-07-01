import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")
application = get_wsgi_application()