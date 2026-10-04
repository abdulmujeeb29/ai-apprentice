from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("capture/new/", views.capture_new, name="capture_new"),
    path("capture/<uuid:session_id>/", views.capture, name="capture"),
    path("map/<uuid:map_id>/", views.map_view, name="map"),
    path("map/<uuid:map_id>/work-map.json", views.map_json, name="map_json"),
    path("map/<uuid:map_id>/agent.md", views.map_agent, name="map_agent"),
    path("teach/<uuid:map_id>/", views.teach, name="teach"),
    path("api/agent/<str:role>/signed-url", views.signed_url, name="signed_url"),
    path("api/s/<uuid:session_id>/frame", views.frame, name="frame"),
    path("api/s/<uuid:session_id>/tick", views.tick, name="tick"),
    path("api/s/<uuid:session_id>/utterance", views.utterance, name="utterance"),
    path("api/s/<uuid:session_id>/debrief", views.debrief, name="debrief"),
    path("api/s/<uuid:session_id>/workmap", views.build_map, name="build_map"),
    path("api/s/<uuid:session_id>/grade", views.grade, name="grade"),
    path("api/s/<uuid:session_id>/debug", views.session_debug, name="session_debug"),
]
