from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from firebase_admin import auth, firestore
from typing import List
import os
import uuid
import tempfile
from datetime import datetime
from utils.auth import verify_admin, verify_user
from utils.document_processing import validate_file, load_document, process_documents
from utils.vector_store import create_pinecone_index, get_pinecone_index, delete_pinecone_index
from utils.chat_history import get_chat_history, format_chat_history, save_message, get_user_chat_sessions, create_new_chat_session, delete_chat_session, generate_session_name, update_session_name 
from models.schemas import ChatRequest, ChatHistoryRequest, NewChatSessionRequest
from config.settings import embeddings, llm, CHAT_PROMPT, MAX_FILES
from firebase_admin import storage
import mimetypes
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Header, HTTPException
from datetime import datetime
from firebase_admin import auth


router = APIRouter()
db = firestore.client()
bucket = storage.bucket() 

executor = ThreadPoolExecutor(max_workers=10)

async def run_in_thread(func, *args, **kwargs):
    """Run a blocking function in a separate thread"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))

def upload_to_firebase_storage(file_content: bytes, filename: str, chatbot_id: str) -> str:
    try:
        file_path = f"chatbots/{chatbot_id}/{filename}"
        blob = bucket.blob(file_path)
        content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            content_type = "application/octet-stream"  
        blob.upload_from_string(
            file_content,
            content_type=content_type
        )
        blob.make_public()
        
        download_url = blob.public_url
        
        return download_url
    except Exception as e:
        print(f"Error uploading to Firebase Storage: {str(e)}")
        raise


def delete_from_firebase_storage(chatbot_id: str, filename: str):
    try:
        file_path = f"chatbots/{chatbot_id}/{filename}"
        blob = bucket.blob(file_path)
        blob.delete()
        print(f"Deleted {filename} from Firebase Storage")
    except Exception as e:
        print(f"Error deleting from Firebase Storage: {str(e)}")


@router.post("/chatbot")
async def create_chatbot(
    authorization: str = Header(...),
    name: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    suggested_questions: List[str] = Form(...),
    is_visible: bool = Form(default=False),
    documents: List[UploadFile] = File(...)
):
    try:
        decoded_token = verify_admin(authorization)
        
        if not name or len(name) > 100:
            raise HTTPException(status_code=400, detail="Name must be 1-100 characters")
        
        if not description or len(description) > 500:
            raise HTTPException(status_code=400, detail="Description must be 1-500 characters")
        
        if not suggested_questions or len(suggested_questions) == 0:
            raise HTTPException(status_code=400, detail="At least one suggested question required")
        
        questions_list = [q.strip() for q in suggested_questions if q.strip()]
        if len(questions_list) == 0:
            raise HTTPException(status_code=400, detail="At least one non-empty suggested question required")
        
        if len(documents) == 0 or len(documents) > MAX_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Must upload between 1 and {MAX_FILES} files"
            )
        
        for doc in documents:
            validate_file(doc)
        
        chatbot_id = str(uuid.uuid4())
        all_chunks = []
        file_metadata = []
        chunks_by_file = {}
        
        with tempfile.TemporaryDirectory() as temp_dir:
            for doc in documents:
                content = await doc.read()
                download_url = upload_to_firebase_storage(content, doc.filename, chatbot_id)
                
                temp_path = os.path.join(temp_dir, doc.filename)
                with open(temp_path, "wb") as f:
                    f.write(content)
                
                file_metadata.append({
                    "filename": doc.filename,
                    "url": download_url,
                    "size": len(content),
                    "content_type": doc.content_type
                })
                
                loaded_docs = load_document(temp_path)
                chunks = process_documents(loaded_docs)
                
                for chunk in chunks:
                    chunk.metadata["source"] = doc.filename
                    chunk.metadata["file_url"] = download_url
                
                chunks_by_file[doc.filename] = chunks
                all_chunks.extend(chunks)
        
        if not all_chunks:
            raise HTTPException(status_code=400, detail="No content extracted from documents")
        
        index_name = create_pinecone_index(chatbot_id)
        index = get_pinecone_index(index_name)
        
        vectors = []
        document_vector_map = {}
        vector_counter = 0
        
        for file_name, chunks in chunks_by_file.items():
            document_vector_map[file_name] = []
            
            for chunk in chunks:
                vector_id = f"{chatbot_id}-{vector_counter}"
                embedding = embeddings.embed_query(chunk.page_content)
                
                file_url = next((f["url"] for f in file_metadata if f["filename"] == file_name), "")
                
                metadata = {
                    "text": chunk.page_content,
                    "source": file_name,
                    "file_url": file_url,
                    "chunk_index": chunk.metadata.get("chunk_index", 0)
                }
                
                if chunk.metadata.get("page") is not None:
                    metadata["page"] = chunk.metadata["page"]
                
                vectors.append({
                    "id": vector_id,
                    "values": embedding,
                    "metadata": metadata
                })
                
                document_vector_map[file_name].append(vector_id)
                vector_counter += 1
        
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            index.upsert(vectors=batch)
        
        chatbot_metadata = {
            "chatbot_id": chatbot_id,
            "name": name,
            "description": description,
            "category": category,
            "suggested_questions": questions_list,
            "file_names": [f["filename"] for f in file_metadata],
            "files": file_metadata,
            "pinecone_index": index_name,
            "total_chunks": len(all_chunks),
            "created_by": decoded_token.get("email"),
            "created_at": datetime.utcnow(),
            "status": "active",
            "is_visible": is_visible,
            "max_vector_id": vector_counter,
            "document_vector_map": document_vector_map
        }
        
        db.collection("chatbots").document(chatbot_id).set(chatbot_metadata)
        
        return {
            "success": True,
            "message": f"Chatbot created successfully ({'visible' if is_visible else 'hidden'})",
            "chatbot_id": chatbot_id,
            "is_visible": is_visible,
            "total_chunks_indexed": len(all_chunks),
            "files_processed": len(file_metadata),
            "files": file_metadata,
            "suggested_questions": questions_list,
            "vector_tracking": {file: len(ids) for file, ids in document_vector_map.items()}
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/chatbot/{chatbot_id}/documents")
async def update_chatbot_documents(
    chatbot_id: str,
    authorization: str = Header(...),
    documents_to_add: List[UploadFile] = File(default=[]),
    documents_to_delete: str = Form(default=""),
    name: str = Form(default=None),
    description: str = Form(default=None),
    category: str = Form(default=None),
    suggested_questions: List[str] = Form(default=None),
    is_visible: bool = Form(default=None)
):
    try:
        decoded_token = verify_admin(authorization)
        
        chatbot_ref = db.collection("chatbots").document(chatbot_id)
        chatbot_doc = chatbot_ref.get()
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        current_files = chatbot_data.get("files", [])
        current_file_names = [f["filename"] for f in current_files]
        index_name = chatbot_data.get("pinecone_index")
        
        if name is not None:
            if not name or len(name) > 100:
                raise HTTPException(status_code=400, detail="Name must be 1-100 characters")
        
        if description is not None:
            if not description or len(description) > 500:
                raise HTTPException(status_code=400, detail="Description must be 1-500 characters")
        
        questions_list = None
        if suggested_questions is not None:
            questions_list = [q.strip() for q in suggested_questions if q.strip()]
            if len(questions_list) == 0:
                raise HTTPException(status_code=400, detail="At least one non-empty suggested question required")
        
        files_to_delete = [f.strip() for f in documents_to_delete.split(",") if f.strip()]
        
        for file_name in files_to_delete:
            if file_name not in current_file_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{file_name}' not found in chatbot documents"
                )
        
        remaining_files = [f for f in current_files if f["filename"] not in files_to_delete]
        new_total_files = len(remaining_files) + len(documents_to_add)
        
        if new_total_files > MAX_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Total files would exceed limit of {MAX_FILES}"
            )
        
        if new_total_files == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete all documents, there must be at least one document"
            )
        
        for doc in documents_to_add:
            validate_file(doc)
        
        index = get_pinecone_index(index_name)
        
        vectors_deleted = 0
        doc_vector_map = chatbot_data.get("document_vector_map", {})
        
        if files_to_delete:
            all_vector_ids = []
            for file_name in files_to_delete:
                delete_from_firebase_storage(chatbot_id, file_name)
                
                vector_ids = doc_vector_map.get(file_name, [])
                all_vector_ids.extend(vector_ids)
                print(f"📄 File '{file_name}' has {len(vector_ids)} vectors to delete")
            
            if all_vector_ids:
                batch_size = 1000
                for i in range(0, len(all_vector_ids), batch_size):
                    batch = all_vector_ids[i:i + batch_size]
                    index.delete(ids=batch)
                    vectors_deleted += len(batch)
                print(f"✅ Deleted {vectors_deleted} vectors from Pinecone")
            
            for file_name in files_to_delete:
                doc_vector_map.pop(file_name, None)
        
        new_chunks = []
        new_file_metadata = []
        new_vector_ids = {}
        chunks_by_file = {}
        if documents_to_add:
            with tempfile.TemporaryDirectory() as temp_dir:
                for doc in documents_to_add:
                    content = await doc.read()
                    download_url = upload_to_firebase_storage(content, doc.filename, chatbot_id)
                    
                    temp_path = os.path.join(temp_dir, doc.filename)
                    with open(temp_path, "wb") as f:
                        f.write(content)
                    new_file_metadata.append({
                        "filename": doc.filename,
                        "url": download_url,
                        "size": len(content),
                        "content_type": doc.content_type
                    })
                    
                    loaded_docs = load_document(temp_path)
                    chunks = process_documents(loaded_docs)
                    
                    for chunk in chunks:
                        chunk.metadata["source"] = doc.filename
                        chunk.metadata["file_url"] = download_url
                    
                    chunks_by_file[doc.filename] = chunks
                    new_chunks.extend(chunks)
            
            if new_chunks:
                vectors = []
                current_max_id = chatbot_data.get("max_vector_id", 0)
                vector_counter = current_max_id
                
                for file_name, chunks in chunks_by_file.items():
                    new_vector_ids[file_name] = []
                    file_url = next((f["url"] for f in new_file_metadata if f["filename"] == file_name), "")
                    
                    for chunk in chunks:
                        vector_id = f"{chatbot_id}-{vector_counter}"
                        embedding = embeddings.embed_query(chunk.page_content)
                        
                        vectors.append({
                            "id": vector_id,
                            "values": embedding,
                            "metadata": {
                                "text": chunk.page_content,
                                "source": file_name,
                                "file_url": file_url
                            }
                        })
                        
                        new_vector_ids[file_name].append(vector_id)
                        vector_counter += 1
                
                batch_size = 100
                for i in range(0, len(vectors), batch_size):
                    batch = vectors[i:i + batch_size]
                    index.upsert(vectors=batch)
                
                print(f"Added {len(vectors)} new vectors to Pinecone")
                
                doc_vector_map.update(new_vector_ids)
                current_max_id = vector_counter
        
        updated_files = remaining_files + new_file_metadata
        new_total_chunks = chatbot_data.get("total_chunks", 0) - vectors_deleted + len(new_chunks)
        
        update_data = {
            "updated_at": datetime.utcnow(),
            "updated_by": decoded_token.get("email")
        }
        
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if category is not None:
            update_data["category"] = category
        if questions_list is not None:
            update_data["suggested_questions"] = questions_list
        if is_visible is not None:
            update_data["is_visible"] = is_visible
        
        if files_to_delete or documents_to_add:
            update_data["files"] = updated_files
            update_data["file_names"] = [f["filename"] for f in updated_files]
            update_data["total_chunks"] = new_total_chunks
            update_data["document_vector_map"] = doc_vector_map
            if documents_to_add:
                update_data["max_vector_id"] = current_max_id
        
        chatbot_ref.update(update_data)
        
        updates_made = []
        if name is not None:
            updates_made.append("name")
        if description is not None:
            updates_made.append("description")
        if category is not None:
            updates_made.append("category")
        if questions_list is not None:
            updates_made.append("suggested questions")
        if is_visible is not None:
            updates_made.append("visibility")
        if files_to_delete:
            updates_made.append(f"{len(files_to_delete)} file(s) deleted")
        if documents_to_add:
            updates_made.append(f"{len(new_file_metadata)} file(s) added")
        
        return {
            "success": True,
            "message": f"Chatbot updated successfully: {', '.join(updates_made) if updates_made else 'no changes'}",
            "chatbot_id": chatbot_id,
            "updates": {
                "metadata_updated": bool(name or description or category or questions_list or is_visible is not None),
                "files_deleted": len(files_to_delete),
                "vectors_deleted": vectors_deleted,
                "files_added": len(new_file_metadata),
                "vectors_added": len(new_chunks)
            },
            "current_state": {
                "files": updated_files if (files_to_delete or documents_to_add) else current_files,
                "total_files": new_total_files if (files_to_delete or documents_to_add) else len(current_files),
                "total_chunks": new_total_chunks if (files_to_delete or documents_to_add) else chatbot_data.get("total_chunks", 0),
                "is_visible": is_visible if is_visible is not None else chatbot_data.get("is_visible", False),
                "suggested_questions": questions_list if questions_list is not None else chatbot_data.get("suggested_questions", [])
            },
            "deletion_verified": {
                "pinecone_vectors_removed": vectors_deleted,
                "firestore_files_removed": len(files_to_delete),
                "firebase_storage_files_deleted": len(files_to_delete),
                "vector_map_cleaned": files_to_delete
            }
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/chat/sessions/{chatbot_id}/{session_id}")
async def delete_session(
    chatbot_id: str,
    session_id: str,
    authorization: str = Header(...)
):
    try:
        decoded_token = verify_user(authorization)
        user_id = decoded_token.get("uid")
        
        success = delete_chat_session(user_id, chatbot_id, session_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "success": True,
            "message": "Session deleted successfully",
            "session_id": session_id
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")




@router.post("/chat")
async def chat_with_rag(
    request: ChatRequest,
    authorization: str = Header(...)
):
    try:
        # Run token verification in thread
        decoded_token = await run_in_thread(verify_user, authorization)
        user_id = decoded_token.get("uid")
        is_admin = decoded_token.get("admin", False)
        
        if not request.message or len(request.message.strip()) == 0:
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        if len(request.message) > 1000:
            raise HTTPException(status_code=400, detail="Message too long (max 1000 characters)")
        
        # Run Firestore operations in thread
        chatbot_ref = db.collection("chatbots").document(request.chatbot_id)
        chatbot_doc = await run_in_thread(chatbot_ref.get)
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        
        if not is_admin and not chatbot_data.get("is_visible", False):
            raise HTTPException(status_code=404, detail="Chatbot not found or not available")
        
        if chatbot_data.get("status") != "active":
            raise HTTPException(status_code=400, detail="Chatbot is not active")
        
        session_id = request.session_id
        
        if not session_id:
            session_id = await run_in_thread(
                create_new_chat_session,
                user_id=user_id,
                chatbot_id=request.chatbot_id,
                chatbot_name=chatbot_data.get("name", "Unknown")
            )
        else:
            session_ref = (db.collection("chat_history")
                            .document(user_id)
                            .collection("c")
                            .document(request.chatbot_id)
                            .collection("s")
                            .document(session_id))
            
            session_doc = await run_in_thread(session_ref.get)
            
            if not session_doc.exists:
                # Run session creation in thread
                await run_in_thread(
                    _create_session_documents,
                    user_id,
                    request.chatbot_id,
                    session_id,
                    chatbot_data,
                    session_ref
                )
        
        # Run chat history retrieval in thread
        chat_history = await run_in_thread(
            get_chat_history,
            user_id=user_id,
            chatbot_id=request.chatbot_id,
            session_id=session_id,
            include_metadata=False
        )
        
        is_first_message = len(chat_history) == 0
        formatted_history = format_chat_history(chat_history)
        
        index_name = chatbot_data.get("pinecone_index")
        index = get_pinecone_index(index_name)
        
        # Run embedding and vector search in threads
        query_embedding = await run_in_thread(embeddings.embed_query, request.message)
        
        search_results = await run_in_thread(
            index.query,
            vector=query_embedding,
            top_k=15,
            include_metadata=True
        )
        
        # Process results (this is fast, can run synchronously)
        context_chunks = []
        citation_map = {}
        citation_counter = 1
        RELEVANCE_THRESHOLD = 0.5
        
        relevant_matches = [m for m in search_results.matches if m.score >= RELEVANCE_THRESHOLD]
        relevant_matches.sort(key=lambda x: x.score, reverse=True)
        
        selected_matches = []
        for match in relevant_matches:
            is_too_similar = False
            current_text = match.metadata.get("text", "")
            
            for selected in selected_matches:
                selected_text = selected.metadata.get("text", "")
                current_words = set(current_text.lower().split())
                selected_words = set(selected_text.lower().split())
                
                if len(current_words & selected_words) / len(current_words | selected_words) > 0.7:
                    is_too_similar = True
                    break
            
            if not is_too_similar:
                selected_matches.append(match)
            
            if len(selected_matches) >= 10:
                break
        
        for match in selected_matches:
            text = match.metadata.get("text", "")
            source = match.metadata.get("source", "unknown")
            file_url = match.metadata.get("file_url", "")
            page = match.metadata.get("page")
            
            citation_id = f"cite_{citation_counter}"
            
            location_parts = []
            if page is not None:
                location_parts.append(f"p. {int(page + 1)}")
            
            location_str = ", ".join(location_parts) if location_parts else "document"
            
            citation_map[citation_id] = {
                "id": citation_id,
                "source": source,
                "file_url": file_url,
                "page": int(page + 1) if page is not None else None,
                "location": location_str,
                "relevance_score": round(match.score, 3)
            }
            
            text_with_citation = f"{text} [{citation_id}]"
            
            context_chunks.append({
                "text": text,
                "text_with_citation": text_with_citation,
                "score": match.score,
                "source": source,
                "file_url": file_url,
                "page": int(page + 1) if page is not None else None,
                "location": location_str,
                "citation_id": citation_id
            })
            
            citation_counter += 1
        
        context_text_list = [chunk["text_with_citation"] for chunk in context_chunks]
        combined_context = "\n\n".join(context_text_list)
        
        formatted_prompt = CHAT_PROMPT.format_messages(
            chatbot_name=chatbot_data.get("name"),
            context=combined_context if combined_context else "No relevant context found.",
            history=formatted_history,
            question=request.message
        )
        
        # Run LLM call in thread (this is the main blocking operation)
        ai_response = await run_in_thread(llm.invoke, formatted_prompt)
        response_text = ai_response.content
        
        import re
        citation_pattern = r'\[cite_(\d+)\]'
        citations_used = re.findall(citation_pattern, response_text)
        
        used_citations = []
        for cite_num in set(citations_used):
            cite_id = f"cite_{cite_num}"
            if cite_id in citation_map:
                used_citations.append(citation_map[cite_id])
        
        context_to_save = context_chunks if used_citations else []
        
        # Run message saving operations in parallel
        await asyncio.gather(
            run_in_thread(
                save_message,
                user_id=user_id,
                chatbot_id=request.chatbot_id,
                session_id=session_id,
                role="user",
                content=request.message,
                citations=None,
                context_used=None
            ),
            run_in_thread(
                save_message,
                user_id=user_id,
                chatbot_id=request.chatbot_id,
                session_id=session_id,
                role="assistant",
                content=response_text,
                citations=used_citations,
                context_used=context_to_save
            )
        )
        
        session_name = None
        if is_first_message:
            # Run session name generation in thread
            session_name = await run_in_thread(generate_session_name, request.message, llm)
            await run_in_thread(update_session_name, user_id, request.chatbot_id, session_id, session_name)
        
        response_data = {
            "success": True,
            "message": request.message,
            "response": response_text,
            "session_id": session_id,
            "session_name": session_name,
            "debug_info": {
                "total_matches": len(search_results.matches),
                "relevant_matches": len(relevant_matches),
                "selected_chunks": len(selected_matches),
                "citations_provided": len(used_citations)
            }
        }
        
        if used_citations:
            response_data["citations"] = used_citations
            response_data["context_used"] = context_to_save
        
        return response_data
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


def _create_session_documents(user_id, chatbot_id, session_id, chatbot_data, session_ref):
    """Helper function to create session documents (runs in thread)"""
    user_ref = db.collection("chat_history").document(user_id)
    user_ref.set({
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow()
    }, merge=True)
    
    chatbot_ref = user_ref.collection("c").document(chatbot_id)
    chatbot_ref.set({
        "chatbot_id": chatbot_id,
        "chatbot_name": chatbot_data.get("name", "Unknown"),
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow()
    }, merge=True)
    
    session_ref.set({
        "session_id": session_id,
        "chatbot_id": chatbot_id,
        "chatbot_name": chatbot_data.get("name", "Unknown"),
        "session_name": "New Conversation",
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "last_message_at": datetime.utcnow(),
        "message_count": 0,
        "is_named": False
    })


@router.post("/chat/sessions/new")
async def create_new_session(
    body: NewChatSessionRequest,
    authorization: str = Header(...)
):
    try:
        # Run token verification in thread
        decoded_token = await run_in_thread(verify_user, authorization)
        user_id = decoded_token.get("uid")
        
        if body.chatbot_id is None:
            raise HTTPException(status_code=400, detail="chatbot_id is required")
        
        print("chatbot_id:", body.chatbot_id)
        
        chatbot_ref = db.collection("chatbots").document(body.chatbot_id)
        chatbot_doc = await run_in_thread(chatbot_ref.get)
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        is_admin = decoded_token.get("admin", False)
        
        if not is_admin and not chatbot_data.get("is_visible", False):
            raise HTTPException(status_code=404, detail="Chatbot not found or not available")
        
        # Run session creation in thread
        session_id = await run_in_thread(
            create_new_chat_session,
            user_id=user_id,
            chatbot_id=body.chatbot_id,
            chatbot_name=chatbot_data.get("name", "Untitled")
        )
        
        return {
            "success": True,
            "session_id": session_id,
            "chatbot_id": body.chatbot_id,
            "chatbot_name": chatbot_data.get("name"),
            "created_at": datetime.utcnow().isoformat()
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/chat/sessions/{chatbot_id}")
async def list_chat_sessions(
    chatbot_id: str,
    authorization: str = Header(...)
):
    try:
        # Run token verification in thread
        decoded_token = await run_in_thread(verify_user, authorization)
        user_id = decoded_token.get("uid")
        
        # Run session retrieval in thread
        sessions = await run_in_thread(get_user_chat_sessions, user_id, chatbot_id)
        
        return {
            "success": True,
            "chatbot_id": chatbot_id,
            "sessions": sessions,
            "total_sessions": len(sessions)
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
@router.post("/chat/history")
async def get_chat_history_endpoint(
    body: ChatHistoryRequest,
    authorization: str = Header(...)
):
    """
    Get chat history with optional metadata (citations and context)
    """
    try:
        decoded_token = verify_user(authorization)
        user_id = decoded_token.get("uid")
        
        print(f"✅ User authenticated: {user_id}")
        
        # Get history with metadata (citations and context)
        history = get_chat_history(
            user_id=user_id,
            chatbot_id=body.chatbot_id,
            session_id=body.session_id,
            include_metadata=True  # Include citations and context
        )
        
        return {
            "success": True,
            "chatbot_id": body.chatbot_id,
            "session_id": body.session_id,
            "history": history,
            "count": len(history)
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
@router.get("/chatbots")
async def list_chatbots(
    authorization: str = Header(...),
    category: str = None
):
    try:
        decoded_token = verify_user(authorization)
        is_admin = decoded_token.get("admin", False)
        
        query = db.collection("chatbots")
        
        if category:
            query = query.where("category", "==", category)
        
        if not is_admin:
            query = query.where("is_visible", "==", True)
        
        chatbots = []
        for doc in query.stream():
            data = doc.to_dict()
            
            created_at = data.get("created_at")
            updated_at = data.get("updated_at")
            
            chatbot_info = {
                "chatbot_id": data.get("chatbot_id"),
                "name": data.get("name"),
                "description": data.get("description"),
                "category": data.get("category"),
                "status": data.get("status", "active"),
                "suggested_questions": data.get("suggested_questions", []),
                "total_chunks": data.get("total_chunks", 0),
                "total_files": len(data.get("file_names", [])),
                "created_at": created_at.isoformat() if created_at else None,
                "last_updated": updated_at.isoformat() if updated_at else (created_at.isoformat() if created_at else None)
            }
            
            if is_admin:
                chatbot_info["is_visible"] = data.get("is_visible", False)
                chatbot_info["file_names"] = data.get("file_names", [])
                chatbot_info["created_by"] = data.get("created_by")
                chatbot_info["updated_by"] = data.get("updated_by")
                chatbot_info["pinecone_index"] = data.get("pinecone_index")
            
            chatbots.append(chatbot_info)
        
        chatbots.sort(key=lambda x: x.get("last_updated") or "", reverse=True)
        
        return {
            "success": True,
            "chatbots": chatbots,
            "total_count": len(chatbots),
            "is_admin": is_admin,
            "filtered_by_category": category
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/chatbot/{chatbot_id}")
async def get_chatbot_details(
    chatbot_id: str,
    authorization: str = Header(...)
):
    try:
        decoded_token = verify_user(authorization)
        is_admin = decoded_token.get("admin", False)
        
        chatbot_ref = db.collection("chatbots").document(chatbot_id)
        chatbot_doc = chatbot_ref.get()
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        
        if not is_admin and not chatbot_data.get("is_visible", False):
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        file_names = chatbot_data.get("file_names", [])
        total_chunks = chatbot_data.get("total_chunks", 0)
        
        return {
            "success": True,
            "chatbot_id": chatbot_id,
            "chatbot_name": chatbot_data.get("name"),
            "category": chatbot_data.get("category"),
            "description": chatbot_data.get("description"),
            "suggested_questions": chatbot_data.get("suggested_questions", []),
            "is_visible": chatbot_data.get("is_visible", False),
            "documents": {
                "file_names": file_names,
                "total_files": len(file_names),
                "total_chunks": total_chunks,
                "max_files_allowed": MAX_FILES,
                "remaining_slots": MAX_FILES - len(file_names)
            },
            "created_at": chatbot_data.get("created_at").isoformat() if chatbot_data.get("created_at") else None,
            "created_by": chatbot_data.get("created_by"),
            "updated_at": chatbot_data.get("updated_at").isoformat() if chatbot_data.get("updated_at") else None,
            "is_admin": is_admin
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/chatbot/{chatbot_id}/documents")
async def get_chatbot_documents(
    chatbot_id: str,
    authorization: str = Header(...)
):
    try:
        decoded_token = verify_admin(authorization)
        
        chatbot_ref = db.collection("chatbots").document(chatbot_id)
        chatbot_doc = chatbot_ref.get()
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        
        file_names = chatbot_data.get("file_names", [])
        total_chunks = chatbot_data.get("total_chunks", 0)
        index_name = chatbot_data.get("pinecone_index")
        
        document_stats = {}
        if index_name:
            try:
                index = get_pinecone_index(index_name)
                
                for file_name in file_names:
                    results = index.query(
                        vector=[0] * 1536,
                        top_k=10000,
                        include_metadata=True,
                        filter={"source": {"$eq": file_name}}
                    )
                    document_stats[file_name] = {
                        "chunk_count": len(results.matches),
                        "file_name": file_name
                    }
            except Exception as e:
                print(f" Could not fetch Pinecone stats: {e}")
        
        return {
            "success": True,
            "chatbot_id": chatbot_id,
            "chatbot_name": chatbot_data.get("name"),
            "category": chatbot_data.get("category"),
            "description": chatbot_data.get("description"),
            "suggested_questions": chatbot_data.get("suggested_questions", []),
            "documents": {
                "file_names": file_names,
                "total_files": len(file_names),
                "total_chunks": total_chunks,
                "max_files_allowed": MAX_FILES,
                "remaining_slots": MAX_FILES - len(file_names)
            },
            "document_stats": document_stats if document_stats else None,
            "created_at": chatbot_data.get("created_at").isoformat() if chatbot_data.get("created_at") else None,
            "created_by": chatbot_data.get("created_by"),
            "updated_at": chatbot_data.get("updated_at").isoformat() if chatbot_data.get("updated_at") else None,
            "updated_by": chatbot_data.get("updated_by")
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/chatbot/{chatbot_id}")
async def delete_chatbot(
    chatbot_id: str,
    authorization: str = Header(...)
):
    try:
        decoded_token = verify_admin(authorization)
        doc = db.collection("chatbots").document(chatbot_id).get()
        
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = doc.to_dict()
        index_name = chatbot_data.get("pinecone_index")
        
        delete_pinecone_index(index_name)
        
        db.collection("chatbots").document(chatbot_id).delete()
        
        return {
            "success": True,
            "message": "Chatbot deleted successfully",
            "deleted_by": decoded_token.get("email"),
            "chatbot_id": chatbot_id
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/chatbot/{chatbot_id}/suggested-questions")
async def get_suggested_questions(
    chatbot_id: str,
    authorization: str = Header(None)
):
    """Get suggested questions for a chatbot"""
    try:
        chatbot_ref = db.collection("chatbots").document(chatbot_id)
        chatbot_doc = chatbot_ref.get()
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        is_visible = chatbot_data.get("is_visible", False)
        
        if not is_visible:
            if not authorization:
                raise HTTPException(
                    status_code=403,
                    detail="This chatbot is hidden. Admin access required."
                )
            
            decoded_token = verify_admin(authorization)
        
        suggested_questions = chatbot_data.get("suggested_questions", [])
        
        return {
            "success": True,
            "chatbot_id": chatbot_id,
            "chatbot_name": chatbot_data.get("name", ""),
            "category": chatbot_data.get("category", ""),
            "suggested_questions": suggested_questions,
            "total_questions": len(suggested_questions),
            "is_visible": is_visible
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f" ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch("/chatbot/{chatbot_id}/toggle-visibility")
async def toggle_chatbot_visibility(
    chatbot_id: str,
    authorization: str = Header(...)
):
    """Toggle chatbot visibility (ADMIN ONLY)"""
    try:
        decoded_token = verify_admin(authorization)
        
        chatbot_ref = db.collection("chatbots").document(chatbot_id)
        chatbot_doc = chatbot_ref.get()
        
        if not chatbot_doc.exists:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        
        chatbot_data = chatbot_doc.to_dict()
        current_visibility = chatbot_data.get("is_visible", False)
        new_visibility = not current_visibility
        
        chatbot_ref.update({
            "is_visible": new_visibility,
            "visibility_updated_at": datetime.utcnow(),
            "visibility_updated_by": decoded_token.get("email")
        })
        
        return {
            "success": True,
            "message": f"Chatbot is now {'visible' if new_visibility else 'hidden'}",
            "chatbot_id": chatbot_id,
            "was_visible": current_visibility,
            "is_visible": new_visibility
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

