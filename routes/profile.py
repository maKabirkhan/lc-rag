from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from firebase_admin import auth, exceptions
import firebase_admin._auth_utils
from config.firebase import db, FIREBASE_APIKEY
from utils.verify_token import verify_token
from models.auth import UpdateRequest, UpdatePasswordRequest
import base64, requests

router = APIRouter()

@router.get("/")
async def get_profile(userData: dict = Depends(verify_token)):
    try:
        user = auth.get_user(userData["uid"])
        doc = db.collection("users").document(userData["uid"]).get()
        profile_image = doc.to_dict().get("profile_image") if doc.exists else None
        return {"email": user.email, "full_name": user.display_name, "profile_image": profile_image}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/")
async def update_profile(request: UpdateRequest, userData: dict = Depends(verify_token)):
    update_data = {}
    if request.full_name:
        update_data["display_name"] = request.full_name
    if request.email:
        update_data["email"] = request.email
    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")

    try:
        user = auth.update_user(userData["uid"], **update_data)
        return {
            "message": "Profile updated successfully",
            "email": user.email,
            "full_name": user.display_name
        }

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="The provided email is already in use by another account.")
    except firebase_admin._auth_utils.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid ID token.")
    except firebase_admin._auth_utils.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="ID token has expired.")
    except exceptions.FirebaseError as e:
        raise HTTPException(status_code=500, detail=f"Firebase error: {e.code} - {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update")
async def update_password(request: UpdatePasswordRequest, userData: dict = Depends(verify_token)):
    if request.new_password != request.confirm_new_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")

    user = auth.get_user(userData["uid"])
    email = user.email

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_APIKEY}"
    payload = {"email": email, "password": request.current_password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    data = response.json()

    if response.status_code != 200:
        error_message = data.get("error", {}).get("message", "")
        if error_message == "INVALID_PASSWORD":
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        raise HTTPException(status_code=500, detail=error_message)

    auth.update_user(userData["uid"], password=request.new_password)
    return {"message": "Password updated successfully"}

@router.put("/image")
async def upload_image(file: UploadFile = File(...), userData: dict = Depends(verify_token)):
    try:
        image_bytes = await file.read()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        db.collection("users").document(userData["uid"]).set({"profile_image": image_base64}, merge=True)
        return {"message": "Profile image uploaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading image: {str(e)}")
