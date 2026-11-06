from django.urls import path
from .views import (
    RegisterView, LoginView,
    ConversationListView, ConversationDetailView,
    ChatView, UploadDocView, AgentView,
    DocumentListView, QueryHistoryView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('conversations/', ConversationListView.as_view(), name='conversations'),
    path('conversations/<int:pk>/', ConversationDetailView.as_view(), name='conversation-detail'),
    path('chat/', ChatView.as_view(), name='chat'),
    path('upload-doc/', UploadDocView.as_view(), name='upload-doc'),
    path('agent/', AgentView.as_view(), name='agent'),
    path('documents/', DocumentListView.as_view(), name='documents'),
    path('query-history/', QueryHistoryView.as_view(), name='query-history'),
]
