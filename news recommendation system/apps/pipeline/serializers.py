from rest_framework import serializers

from apps.pipeline.models import PipelineJob


class PipelineJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineJob
        fields = "__all__"
