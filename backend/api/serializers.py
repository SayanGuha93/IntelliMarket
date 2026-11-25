"""Input validation for externally supplied authentication values."""
from rest_framework import serializers


class GoogleCredentialSerializer(serializers.Serializer):
    credential = serializers.CharField(min_length=20, max_length=10000, trim_whitespace=True)


class ProductSearchSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    category = serializers.CharField(required=False, allow_blank=True, max_length=100)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, default=100)
