from fastapi import Header, HTTPException
from firebase_admin import auth, exceptions
import firebase_admin._auth_utils

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    id_token = authorization.split(" ")[1]
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except firebase_admin._auth_utils.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid ID token")
    except firebase_admin._auth_utils.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="ID token has expired")
    except exceptions.FirebaseError as e:
        raise HTTPException(status_code=500, detail=f"Firebase error: {e.code} - {e.message}")
