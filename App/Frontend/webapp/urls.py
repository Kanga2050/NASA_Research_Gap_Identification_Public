from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from App.Frontend.portal.views import (
    account_settings,
    agent_chat,
    agent_reset,
    change_password,
    csv_columns,
    dashboard,
    export_file,
    import_file,
    issue_api_key,
    preview_output,
    preview_output_html,
    revoke_api_key,
    signup,
    studio,
    studio_run,
    submit_task,
    task_status,
    update_agent_settings,
    update_username,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("signup/", signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(template_name="registration/logged_out.html"), name="logout"),
    path("api-keys/new/", issue_api_key, name="issue_api_key"),
    path("api-keys/<int:key_id>/revoke/", revoke_api_key, name="revoke_api_key"),
    path("settings/", account_settings, name="account_settings"),
    path("settings/username/", update_username, name="update_username"),
    path("settings/password/", change_password, name="change_password"),
    path("settings/agent/", update_agent_settings, name="update_agent_settings"),
    path("agent/chat/", agent_chat, name="agent_chat"),
    path("agent/reset/", agent_reset, name="agent_reset"),
    path("studio/", studio, name="studio"),
    path("studio/run/", studio_run, name="studio_run"),
    path("tasks/new/", submit_task, name="submit_task"),
    path("tasks/<str:task_id>/status/", task_status, name="task_status"),
    path("outputs/html/<str:name>/", preview_output_html, name="preview_output_html"),
    path("outputs/preview/<str:kind>/<str:name>/", preview_output, name="preview_output"),
    path("csvs/<str:name>/columns/", csv_columns, name="csv_columns"),
    path("files/import/", import_file, name="import_file"),
    path("files/export/<str:kind>/<str:name>/", export_file, name="export_file"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    # The app is normally served through Server.py's uvicorn/ASGI mount rather
    # than `manage.py runserver`, so Django's auto static-serving hook (which
    # only wires itself into the runserver command) never kicks in. Wire the
    # staticfiles view in explicitly so /static/... resolves under any server.
    urlpatterns += staticfiles_urlpatterns()
