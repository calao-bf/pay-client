import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=["pay_client", "appli_test"],
        ROOT_URLCONF="urls_test",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        PAY_URL="http://pay.test",
        PAY_API_KEY="ck_test_essai",
        PAY_WEBHOOK_SECRET="whsec_essai",
        ALLOWED_HOSTS=["*"],
        USE_TZ=True,
    )
    django.setup()
