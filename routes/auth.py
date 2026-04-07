from fastapi import APIRouter, HTTPException
import requests
import firebase_admin._auth_utils
from firebase_admin import auth
from config.firebase import FIREBASE_APIKEY
from models.auth import SignUpRequest, SigninRequest, ForgotPasswordRequest, RefreshTokenRequest

router = APIRouter()

@router.post("/signup")
async def sign_up(request: SignUpRequest):
    """
    Create a new user with email/password or Google Sign-In.
    - For email: provide full_name, email, password, confirm_password, is_google=False
    - For Google: provide email, is_google=True
    """
    try:
        if request.is_google:
            try:
                # Check if user already exists
                try:
                    existing_user = auth.get_user_by_email(request.email)
                    custom_claims = existing_user.custom_claims or {}
                    
                    # If user exists with password provider
                    if custom_claims.get("provider") == "password":
                        raise HTTPException(
                            status_code=400, 
                            detail="This email is already registered with email/password. Please sign in with email/password."
                        )
                    
                    # If user exists with Google provider
                    if custom_claims.get("provider") == "google":
                        raise HTTPException(status_code=400, detail="User already exists with Google. Please sign in.")
                    
                    # User exists but no provider set, update their claims
                    is_admin = request.role.lower() == "admin"
                    auth.set_custom_user_claims(existing_user.uid, {"admin": is_admin, "provider": "google"})
                    user = existing_user
                    
                except auth.UserNotFoundError:
                    # User doesn't exist, create new user
                    user = auth.create_user(
                        email=request.email,
                        display_name=request.full_name or request.email.split('@')[0],
                        email_verified=True  # Google emails are verified
                    )
                    
                    is_admin = request.role.lower() == "admin"
                    auth.set_custom_user_claims(user.uid, {"admin": is_admin, "provider": "google"})
                
                # Generate custom token for authentication
                custom_token = auth.create_custom_token(user.uid)
                
                # Exchange custom token for ID token
                url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_APIKEY}"
                payload = {
                    "token": custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token,
                    "returnSecureToken": True
                }
                
                response = requests.post(url, json=payload)
                data = response.json()
                
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=data.get("error", {}).get("message", "Failed to authenticate")
                    )
                
                return {
                    "message": "User created successfully with Google",
                    "uid": user.uid,
                    "email": user.email,
                    "full_name": user.display_name,
                    "role": "admin" if is_admin else "user",
                    "id_token": data.get("idToken"),
                    "refresh_token": data.get("refreshToken")
                }
                
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise e
                raise HTTPException(status_code=500, detail=str(e))
        
        else:
            # Email/Password Sign-Up
            if not request.full_name:
                raise HTTPException(status_code=400, detail="Full name is required for email sign-up")
            
            if not request.password or not request.confirm_password:
                raise HTTPException(status_code=400, detail="Password is required for email sign-up")
            
            if request.password != request.confirm_password:
                raise HTTPException(status_code=400, detail="Passwords do not match")
            
            # Check if email exists with Google provider
            try:
                user_by_email = auth.get_user_by_email(request.email)
                custom_claims = user_by_email.custom_claims or {}
                if custom_claims.get("provider") == "google":
                    raise HTTPException(
                        status_code=400, 
                        detail="This email is already registered with Google. Please sign in with Google."
                    )
            except auth.UserNotFoundError:
                pass
            
            user = auth.create_user(
                display_name=request.full_name,
                email=request.email,
                password=request.password
            )

            is_admin = request.role.lower() == "admin"
            auth.set_custom_user_claims(user.uid, {"admin": is_admin, "provider": "password"})

            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_APIKEY}"
            payload = {
                "email": request.email,
                "password": request.password,
                "returnSecureToken": True
            }
            response = requests.post(url, json=payload)
            data = response.json()

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=data.get("error", {}).get("message", "Failed to sign in")
                )

            return {
                "message": "User created successfully",
                "uid": user.uid,
                "email": user.email,
                "full_name": user.display_name,
                "role": "admin" if is_admin else "user",
                "id_token": data.get("idToken"),
                "refresh_token": data.get("refreshToken")
            }

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="Email already exists")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/signin")
async def login(request: SigninRequest):
    """
    Sign in with email/password or Google Sign-In.
    - For email: provide email, password, is_google=False
    - For Google: provide email, is_google=True
    """
    try:
        if request.is_google:
            try:
                user = auth.get_user_by_email(request.email)
                custom_claims = user.custom_claims or {}
                
                if custom_claims.get("provider") == "password":
                    raise HTTPException(
                        status_code=400, 
                        detail="This email is registered with email/password. Please sign in with email/password."
                    )
                
                is_admin = custom_claims.get("admin", False)
                
                custom_token = auth.create_custom_token(user.uid)
                
                url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_APIKEY}"
                payload = {
                    "token": custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token,
                    "returnSecureToken": True
                }
                
                response = requests.post(url, json=payload)
                data = response.json()
                
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=data.get("error", {}).get("message", "Failed to authenticate")
                    )
                
                return {
                    "message": "User signed in successfully with Google",
                    "idToken": data.get("idToken"),
                    "refreshToken": data.get("refreshToken"),
                    "expiresIn": data.get("expiresIn"),
                    "localId": user.uid,
                    "email": user.email,
                    "full_name": user.display_name,
                    "role": "admin" if is_admin else "user"
                }
                
            except auth.UserNotFoundError:
                raise HTTPException(status_code=404, detail="User not found. Please sign up first.")
        
        else:
            if not request.password:
                raise HTTPException(status_code=400, detail="Password is required")
            
            try:
                user_check = auth.get_user_by_email(request.email)
                custom_claims = user_check.custom_claims or {}
                if custom_claims.get("provider") == "google":
                    raise HTTPException(
                        status_code=400, 
                        detail="This email is registered with Google. Please sign in with Google."
                    )
            except auth.UserNotFoundError:
                raise HTTPException(status_code=404, detail="Email not found")
            
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_APIKEY}"
            payload = {
                "email": request.email,
                "password": request.password,
                "returnSecureToken": True
            }
            response = requests.post(url, json=payload)
            data = response.json()

            if response.status_code == 200:
                user = auth.get_user(data["localId"])
                custom_claims = user.custom_claims or {}
                is_admin = custom_claims.get("admin", False)
                
                return {
                    "message": "User signed in successfully",
                    "idToken": data["idToken"],
                    "refreshToken": data["refreshToken"],
                    "expiresIn": data["expiresIn"],
                    "localId": data["localId"],
                    "email": user.email,
                    "full_name": user.display_name,
                    "role": "admin" if is_admin else "user"
                }

            error_message = data.get("error", {}).get("message", "")
            if error_message == "EMAIL_NOT_FOUND":
                raise HTTPException(status_code=404, detail="Email not found")
            elif error_message == "INVALID_PASSWORD":
                raise HTTPException(status_code=400, detail="Invalid password")
            else:
                raise HTTPException(status_code=500, detail=f"Firebase error: {error_message}")
    
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
       
@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest):
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_APIKEY}"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": request.refresh
    }

    response = requests.post(url, data=payload)
    data = response.json()

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=data.get("error", {}).get("message", "Failed to refresh token"))

    return {
        "id_token": data["id_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data["expires_in"],
        "user_id": data["user_id"]
    }

@router.post("/forgot")
async def forgot_password(request: ForgotPasswordRequest):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={FIREBASE_APIKEY}"
    payload = {
        "requestType": "PASSWORD_RESET",
        "email": request.email
    }

    response = requests.post(url, json=payload)
    data = response.json()

    if response.status_code == 200:
        return {"message": "Password reset email sent successfully"}
    elif data.get("error", {}).get("message") == "EMAIL_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Email not found")
    else:
        raise HTTPException(status_code=500, detail=f"Firebase error: {data.get('error', {}).get('message')}")
