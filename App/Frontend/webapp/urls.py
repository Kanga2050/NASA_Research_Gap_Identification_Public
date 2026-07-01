from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from App.Frontend.portal.views import dashboard, issue_api_key, submit_task

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api-keys/new/", issue_api_key, name="issue_api_key"),
    path("tasks/new/", submit_task, name="submit_task"),
    path("admin/", admin.site.urls),
]