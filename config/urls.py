from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from people.views import PersonViewSet

router = DefaultRouter()
router.register("api/people", PersonViewSet)

urlpatterns = [
    path("", TemplateView.as_view(template_name="people/directory.html")),
    path("", include(router.urls)),
]
