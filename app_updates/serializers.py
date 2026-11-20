from rest_framework import serializers

from .models import AppUpdatePolicy


class AppUpdateCheckQuerySerializer(serializers.Serializer):
    platform = serializers.ChoiceField(
        choices=AppUpdatePolicy.Platform.choices,
    )
    # جزء من عقد التكامل فقط، ولا يُستخدم في المقارنة.
    current_version = serializers.CharField(
        max_length=50,
        allow_blank=False,
        trim_whitespace=True,
    )
    current_build = serializers.IntegerField(
        min_value=1,
    )


class AppUpdateCheckResultSerializer(serializers.Serializer):
    platform = serializers.CharField()
    check_enabled = serializers.BooleanField()
    latest_version = serializers.CharField(allow_null=True)
    latest_build = serializers.IntegerField(allow_null=True)
    minimum_supported_build = serializers.IntegerField(allow_null=True)
    update_available = serializers.BooleanField()
    force_update = serializers.BooleanField()
    update_message = serializers.CharField(allow_blank=True)
    store_url = serializers.URLField(allow_null=True)


class AppUpdateCheckResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    code = serializers.CharField()
    message = serializers.CharField()
    data = AppUpdateCheckResultSerializer()
    meta = serializers.DictField()
