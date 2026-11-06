import os
from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination

from langchain_anthropic import ChatAnthropic
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

import requests

from .models import Conversation, Message, Document, QueryHistory
from .serializers import (
    RegisterSerializer, ConversationSerializer,
    DocumentSerializer, QueryHistorySerializer
)


def get_llm():
    return ChatAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_MODEL,
        temperature=0.7,
    )


def get_vectorstore():
    embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
    return Chroma(
        persist_directory=settings.CHROMA_DB_PATH,
        embedding_function=embeddings,
    )


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a given city."""
    try:
        response = requests.get(f"https://wttr.in/{city}?format=3", timeout=5)
        return response.text
    except Exception:
        return f"Could not fetch weather for {city}."


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            return Response({'token': token.key}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({'token': token.key})
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)


class ConversationListView(APIView):

    def get(self, request):
        conversations = Conversation.objects.filter(user=request.user).order_by('-created_at')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(conversations, request)
        serializer = ConversationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        title = request.data.get('title', 'New Conversation')
        conversation = Conversation.objects.create(user=request.user, title=title)
        serializer = ConversationSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):

    def get(self, request, pk):
        try:
            conversation = Conversation.objects.get(pk=pk, user=request.user)
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ConversationSerializer(conversation)
        return Response(serializer.data)


class ChatView(APIView):

    def post(self, request):
        conversation_id = request.data.get('conversation_id')
        question = request.data.get('question', '')

        if not question:
            return Response({'error': 'question is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            conversation = Conversation.objects.get(pk=conversation_id, user=request.user)
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)

        past_messages = conversation.messages.order_by('created_at')
        chat_history = []
        for msg in past_messages:
            if msg.role == 'user':
                chat_history.append(HumanMessage(content=msg.content))
            else:
                chat_history.append(AIMessage(content=msg.content))

        chat_history.append(HumanMessage(content=question))

        llm = get_llm()
        response = llm.invoke(chat_history)
        answer = response.content

        Message.objects.create(conversation=conversation, role='user', content=question)
        Message.objects.create(conversation=conversation, role='assistant', content=answer)

        QueryHistory.objects.create(
            user=request.user,
            endpoint='chat',
            question=question,
            answer=answer,
        )

        return Response({'question': question, 'answer': answer})


class UploadDocView(APIView):

    def post(self, request):
        uploaded_file = request.FILES.get('file')
        title = request.data.get('title', '')

        if not uploaded_file:
            return Response({'error': 'file is required'}, status=status.HTTP_400_BAD_REQUEST)

        os.makedirs(settings.TEMP_UPLOAD_PATH, exist_ok=True)
        file_path = os.path.join(settings.TEMP_UPLOAD_PATH, uploaded_file.name)

        with open(file_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        if uploaded_file.name.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
            pages = loader.load()
            for page in pages:
                page.metadata['title'] = title or uploaded_file.name
                page.metadata['user'] = request.user.username
        else:
            content = open(file_path, 'r').read()
            from langchain_core.documents import Document as LCDocument
            pages = [LCDocument(
                page_content=content,
                metadata={'title': title or uploaded_file.name, 'user': request.user.username}
            )]

        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_documents(pages)

        vectorstore = get_vectorstore()
        vectorstore.add_documents(chunks)

        os.remove(file_path)

        Document.objects.create(
            user=request.user,
            title=title or uploaded_file.name,
            filename=uploaded_file.name,
        )

        QueryHistory.objects.create(
            user=request.user,
            endpoint='upload-doc',
            question=f"Uploaded: {uploaded_file.name}",
            answer=f"Ingested {len(chunks)} chunks",
        )

        return Response({
            'message': 'Document uploaded successfully',
            'filename': uploaded_file.name,
            'chunks': len(chunks),
        }, status=status.HTTP_201_CREATED)


class AgentView(APIView):

    def post(self, request):
        question = request.data.get('question', '')
        conversation_id = request.data.get('conversation_id')

        if not question:
            return Response({'error': 'question is required'}, status=status.HTTP_400_BAD_REQUEST)

        vectorstore = get_vectorstore()

        @tool
        def search_documents(query: str) -> str:
            """Search uploaded documents for relevant information."""
            chunks = vectorstore.similarity_search(query, k=3)
            if not chunks:
                return "No relevant documents found."
            return "\n\n".join([c.page_content for c in chunks])

        tools = [get_weather, search_documents]
        llm = get_llm()
        agent = create_react_agent(llm, tools)

        system_prompt = (
            "You are a helpful AI assistant with access to tools. "
            "ALWAYS use the search_documents tool first to look for relevant information in uploaded documents before answering any factual question. "
            "Use get_weather when the user asks about weather in any city. "
            "Base your answer on tool results whenever possible. "
            "Only fall back to your own knowledge if the tools return no useful results."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        result = agent.invoke({"messages": messages})
        answer = result["messages"][-1].content

        relevant_chunks = vectorstore.similarity_search(question, k=3)
        sources = list(set([c.metadata.get('title', 'Unknown') for c in relevant_chunks]))

        if conversation_id:
            try:
                conversation = Conversation.objects.get(pk=conversation_id, user=request.user)
                Message.objects.create(conversation=conversation, role='user', content=question)
                Message.objects.create(conversation=conversation, role='assistant', content=answer)
            except Conversation.DoesNotExist:
                pass

        QueryHistory.objects.create(
            user=request.user,
            endpoint='agent',
            question=question,
            answer=answer,
        )

        return Response({
            'question': question,
            'answer': answer,
            'sources': sources,
        })


class DocumentListView(APIView):

    def get(self, request):
        documents = Document.objects.filter(user=request.user).order_by('-created_at')
        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data)


class QueryHistoryView(APIView):

    def get(self, request):
        queries = QueryHistory.objects.filter(user=request.user).order_by('-created_at')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queries, request)
        serializer = QueryHistorySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
