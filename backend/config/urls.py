from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.views.static import serve


def health_check(request):
    return JsonResponse({"status": "ok"})


def favicon(request):
    return JsonResponse({}, status=204)


urlpatterns = [
    path('', health_check, name='health_check'),
    path('favicon.ico', favicon),
    path('admin/', admin.site.urls),
    path('api/v1/', include('payouts.urls')),
]
