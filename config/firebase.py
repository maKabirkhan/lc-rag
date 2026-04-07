import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import os
from firebase_admin import storage

load_dotenv()

cred = credentials.Certificate("firebase_config.json")

firebase_admin.initialize_app(cred, {
    'storageBucket': 'internalworkspace-e6e03.firebasestorage.app'
})

db = firestore.client()
FIREBASE_APIKEY = os.getenv("FIREBASE_APIKEY")
bucket = storage.bucket()