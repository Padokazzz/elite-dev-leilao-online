from rest_framework import serializers


class ArtworkSearchSerializer(serializers.Serializer):
    q = serializers.CharField(
        max_length=100,
        allow_blank=False,
        trim_whitespace=True,
    )
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=20,
    )


class ArtworkImportSerializer(serializers.Serializer):
    external_id = serializers.RegexField(
        regex=r"^[0-9]+$",
        max_length=20,
        trim_whitespace=True,
    )
