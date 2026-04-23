from rest_framework import serializers
from bson.objectid import ObjectId


class UploadImagesSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    folder_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)

    def validate_event_id(self, value):
        if not ObjectId.is_valid(value):
            raise serializers.ValidationError("Invalid event_id")
        return value


class ScanFaceSerializer(serializers.Serializer):
    event_id = serializers.CharField()

    def validate_event_id(self, value):
        if not ObjectId.is_valid(value):
            raise serializers.ValidationError("Invalid event_id")
        return value
