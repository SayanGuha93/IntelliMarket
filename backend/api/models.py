from django.conf import settings
from django.db import models


class GoogleIdentity(models.Model):
    """Provider identity link; Google subject is globally stable and unique."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_identities")
    subject = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "subject"], name="unique_user_google_subject")]


class RAGSessionOwner(models.Model):
    """Django-side ownership index for sessions held by the separate RAG process."""
    session_id = models.UUIDField(unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rag_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
