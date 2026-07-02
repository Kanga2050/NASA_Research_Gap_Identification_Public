from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from App.Frontend.portal.views import dashboard, issue_api_key, preview_output_html, submit_task

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api-keys/new/", issue_api_key, name="issue_api_key"),
    path("tasks/new/", submit_task, name="submit_task"),
    path("outputs/html/<str:name>/", preview_output_html, name="preview_output_html"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    # The app is normally served through Server.py's uvicorn/ASGI mount rather
    # than `manage.py runserver`, so Django's auto static-serving hook (which
    # only wires itself into the runserver command) never kicks in. Wire the
    # staticfiles view in explicitly so /static/... resolves under any server.
    urlpatterns += staticfiles_urlpatterns()