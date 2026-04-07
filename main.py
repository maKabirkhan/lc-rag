from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, profile, admin, chatbot, dashboard
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="LC-RAG",
    description="Firebase Authentication + User Management API",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "LC-RAG API is running successfully."}

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/profile", tags=["Profile"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(chatbot.router, prefix="/admin", tags=["Chatbot"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
