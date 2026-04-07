import os
from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))


def create_pinecone_index(chatbot_id: str) -> str:
    """Create Pinecone index for the chatbot"""
    index_name = f"chatbot-{chatbot_id}"
    
    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
    
    return index_name


def get_pinecone_index(index_name: str):
    """Get Pinecone index instance"""
    return pc.Index(index_name)


def delete_pinecone_index(index_name: str) -> None:
    """Delete Pinecone index if it exists"""
    if index_name and index_name in pc.list_indexes().names():
        pc.delete_index(index_name)