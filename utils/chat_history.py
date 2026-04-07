from firebase_admin import firestore
from datetime import datetime
import uuid

db = firestore.client()

def generate_session_name(first_message: str, llm) -> str:
    try:
        naming_prompt = f"""Based on this user message, generate a short, concise title (max 6 words) that describes the conversation topic. 
Only return the title, nothing else.

User message: {first_message}

Title:"""
        
        response = llm.invoke(naming_prompt)
        session_name = response.content.strip()
        session_name = session_name.strip('"').strip("'")
        
        if len(session_name) > 60:
            session_name = session_name[:57] + "..."
        
        return session_name
    except Exception as e:
        return first_message[:50] + ("..." if len(first_message) > 50 else "")


def create_new_chat_session(user_id: str, chatbot_id: str, chatbot_name: str, session_name: str = None) -> str:
    session_id = str(uuid.uuid4())
    
    user_ref = db.collection("chat_history").document(user_id)
    user_ref.set({
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow()
    }, merge=True)
    
    chatbot_ref = user_ref.collection("c").document(chatbot_id)
    chatbot_ref.set({
        "chatbot_id": chatbot_id,
        "chatbot_name": chatbot_name,
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow()
    }, merge=True)
    
    session_ref = chatbot_ref.collection("s").document(session_id)
    session_ref.set({
        "session_id": session_id,
        "chatbot_id": chatbot_id,
        "chatbot_name": chatbot_name,
        "session_name": session_name or "New Conversation",
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "last_message_at": datetime.utcnow(),
        "message_count": 0,
        "is_named": False
    })
    
    return session_id


def update_session_name(user_id: str, chatbot_id: str, session_id: str, session_name: str):
    try:
        session_ref = (db.collection("chat_history")
                        .document(user_id)
                        .collection("c")
                        .document(chatbot_id)
                        .collection("s")
                        .document(session_id))
        
        session_ref.update({
            "session_name": session_name,
            "is_named": True
        })
    except Exception:
        pass


def get_user_chat_sessions(user_id: str, chatbot_id: str) -> list:
    sessions_ref = (db.collection("chat_history")
                     .document(user_id)
                     .collection("c")
                     .document(chatbot_id)
                     .collection("s")
                     .stream())
    
    sessions = []
    for session_doc in sessions_ref:
        session_data = session_doc.to_dict()
        
        messages_ref = (db.collection("chat_history")
                        .document(user_id)
                        .collection("c")
                        .document(chatbot_id)
                        .collection("s")
                        .document(session_doc.id)
                        .collection("m")
                        .order_by("timestamp", direction=firestore.Query.ASCENDING)
                        .limit(1))
        
        first_message = None
        for msg in messages_ref.stream():
            msg_data = msg.to_dict()
            if msg_data.get("role") == "user":
                first_message = msg_data.get("content", "")[:100]
                break
        
        sessions.append({
            "session_id": session_data.get("session_id"),
            "chatbot_name": session_data.get("chatbot_name"),
            "session_name": session_data.get("session_name", "New Conversation"),
            "created_at": session_data.get("created_at").isoformat() if session_data.get("created_at") else None,
            "last_message_at": session_data.get("last_message_at").isoformat() if session_data.get("last_message_at") else None,
            "message_count": session_data.get("message_count", 0),
            "preview": first_message or "New conversation"
        })
    
    sessions.sort(key=lambda x: x.get("last_message_at") or "", reverse=True)
    return sessions


def delete_chat_session(user_id: str, chatbot_id: str, session_id: str) -> bool:
    try:
        session_ref = (db.collection("chat_history")
                        .document(user_id)
                        .collection("c")
                        .document(chatbot_id)
                        .collection("s")
                        .document(session_id))
        
        if not session_ref.get().exists:
            return False
        
        messages_ref = session_ref.collection("m")
        batch = db.batch()
        
        for msg in messages_ref.stream():
            batch.delete(msg.reference)
        
        batch.commit()
        session_ref.delete()
        
        return True
    except Exception:
        return False


def save_message(
    user_id: str,
    chatbot_id: str,
    session_id: str,
    role: str,
    content: str,
    citations: list = None,
    context_used: list = None
):
    if not session_id:
        raise ValueError("session_id is required and cannot be empty")
    
    message_data = {
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow()
    }
    
    if citations is not None:
        message_data["citations"] = citations
    
    if context_used is not None:
        message_data["context_used"] = context_used
    
    message_ref = (db.collection("chat_history")
                    .document(user_id)
                    .collection("c")
                    .document(chatbot_id)
                    .collection("s")
                    .document(session_id)
                    .collection("m")
                    .document())
    
    message_ref.set(message_data)
    
    session_ref = (db.collection("chat_history")
                    .document(user_id)
                    .collection("c")
                    .document(chatbot_id)
                    .collection("s")
                    .document(session_id))
    
    session_ref.update({
        "last_message_at": datetime.utcnow(),
        "message_count": firestore.Increment(1)
    })


def get_chat_history(
    user_id: str,
    chatbot_id: str,
    session_id: str,
    limit: int = 50,
    include_metadata: bool = False
) -> list:
    if not session_id:
        raise ValueError("session_id is required")
    
    messages_ref = (db.collection("chat_history")
                     .document(user_id)
                     .collection("c")
                     .document(chatbot_id)
                     .collection("s")
                     .document(session_id)
                     .collection("m")
                     .order_by("timestamp", direction=firestore.Query.ASCENDING)
                     .limit(limit))
    
    history = []
    for doc in messages_ref.stream():
        data = doc.to_dict()
        
        message_obj = {
            "role": data.get("role"),
            "content": data.get("content"),
            "timestamp": data.get("timestamp").isoformat() if data.get("timestamp") else None
        }
        
        if include_metadata:
            if "citations" in data:
                message_obj["citations"] = data.get("citations")
            if "context_used" in data:
                message_obj["context_used"] = data.get("context_used")
        
        history.append(message_obj)
    
    return history


def format_chat_history(history: list, include_citations: bool = False) -> str:
    if not history:
        return ""
    
    formatted = []
    for msg in history:
        role = "Human" if msg["role"] == "user" else "Assistant"
        content = msg['content']
        
        if include_citations and msg.get("citations") and msg["role"] == "assistant":
            citation_sources = [f"{c.get('source')} (p. {c.get('page')})" 
                              for c in msg.get("citations", []) 
                              if c.get('source')]
            if citation_sources:
                content += f"\n[Sources: {', '.join(citation_sources)}]"
        
        formatted.append(f"{role}: {content}")
    
    return "\n".join(formatted)
