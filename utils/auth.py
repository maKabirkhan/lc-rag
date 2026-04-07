from fastapi import HTTPException, Header
from firebase_admin import auth


def verify_admin(authorization: str) -> dict:
    """Verify admin authentication and return decoded token"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    id_token = authorization.split("Bearer ")[1]
    decoded_token = auth.verify_id_token(id_token)
    
    if not decoded_token.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: admin privileges required"
        )
    
    return decoded_token


def verify_user(authorization: str):
    """
    Verify user token and check if it has been revoked.
    Returns decoded token if valid.
    """
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header missing")
        
        id_token = authorization.split("Bearer ")[-1]
        
        decoded_token = auth.verify_id_token(id_token, check_revoked=True)
        
        return decoded_token
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except auth.RevokedIdTokenError:
        raise HTTPException(status_code=401, detail="Token has been revoked. Please log in again.")
    except auth.UserNotFoundError:
        raise HTTPException(status_code=401, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
