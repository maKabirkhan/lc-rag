import os
from typing import List
from fastapi import HTTPException, UploadFile
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".doc"}


def validate_file(file: UploadFile) -> None:
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file_ext} not allowed. Only PDF, TXT, DOC, DOCX are accepted"
        )


def load_document(file_path: str) -> List:
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if ext == ".pdf":
            loader = PyPDFLoader(file_path)
        elif ext == ".txt":
            loader = TextLoader(file_path, encoding='utf-8')
        elif ext in [".docx", ".doc"]:
            loader = Docx2txtLoader(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
        
        documents = loader.load()
        
        for doc in documents:
            if 'source' not in doc.metadata:
                doc.metadata['source'] = os.path.basename(file_path)
        
        return documents
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading document: {str(e)}")


def process_documents(documents: List) -> List:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=200,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    
    chunks = text_splitter.split_documents(documents)
    
    for i, chunk in enumerate(chunks):
        chunk.metadata['chunk_index'] = i
        chunk.metadata['chunk_length'] = len(chunk.page_content)
        chunk.metadata['preview'] = chunk.page_content[:100].replace('\n', ' ').strip()
    
    return chunks