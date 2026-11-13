from django.urls import path

from .vues import webhook

app_name = "pay_client"
urlpatterns = [path("webhook/", webhook, name="webhook")]
