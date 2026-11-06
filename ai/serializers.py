from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Conversation, Message, Document, QueryHistory


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
        )
        return user


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'created_at']
        read_only_fields = ['id', 'role', 'content', 'created_at']


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'created_at', 'messages']
        read_only_fields = ['id', 'created_at', 'messages']


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ['id', 'title', 'filename', 'created_at']
        read_only_fields = ['id', 'filename', 'created_at']


class QueryHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = QueryHistory
        fields = ['id', 'endpoint', 'question', 'answer', 'created_at']
        read_only_fields = ['id', 'endpoint', 'question', 'answer', 'created_at']
