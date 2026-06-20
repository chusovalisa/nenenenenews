from rest_framework import serializers

from apps.core.models import SystemConfig


class SystemConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = ["id", "key", "value", "description", "is_active", "created_at", "updated_at"]
