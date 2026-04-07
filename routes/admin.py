from fastapi import APIRouter, HTTPException, Header, status
from firebase_admin import auth, firestore
import firebase_admin._auth_utils
from models.admin import CreateAdminRequest, UpdateRoleRequest, DeleteUserRequest, UpdateUsernameRequest, InviteUserRequest, SendEmailRequest
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet
import base64
import os
import logging
from datetime import datetime, timezone
from utils.auth import verify_admin, verify_user
from dotenv import load_dotenv
load_dotenv()

router = APIRouter()
db = firestore.client()


SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise Exception("Missing ENCRYPTION_KEY in environment variables")

fernet = Fernet(ENCRYPTION_KEY)

try:
    fernet = Fernet(ENCRYPTION_KEY)
except Exception:
    raise RuntimeError("Invalid Fernet key format — generate a new one using Fernet.generate_key()")


@router.post("/create")
async def create_admin(request: CreateAdminRequest):
    """
    Creates a new admin account and assigns admin privileges.
    """
    try:
        user = auth.create_user(
            email=request.email,
            password=request.password,
            display_name=request.full_name
        )

        auth.set_custom_user_claims(user.uid, {"admin": True})

        return {
            "message": "Admin account created successfully",
            "uid": user.uid,
            "email": user.email,
            "full_name": user.display_name,
            "is_admin": True
        }

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="Email already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users")
async def get_all_users(authorization: str = Header(...)):
    """
    Returns all users except the current admin.
    Only accessible to admins.
    Includes created_at, last_login, and admin status.
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)

        if not decoded_token.get("admin"):
            raise HTTPException(status_code=403, detail="Access forbidden: admin privileges required")

        current_admin_uid = decoded_token.get("uid")

        users = []
        page = auth.list_users()
        while page:
            for user in page.users:
                if user.uid == current_admin_uid:
                    continue

                users.append({
                    "uid": user.uid,
                    "email": user.email,
                    "display_name": user.display_name,
                    "email_verified": user.email_verified,
                    "disabled": user.disabled,
                    "is_admin": bool(user.custom_claims and user.custom_claims.get("admin", False)),
                    "created_at": (
                        datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000).isoformat()
                        if user.user_metadata.creation_timestamp else None
                    ),
                    "last_login": (
                        datetime.fromtimestamp(user.user_metadata.last_sign_in_timestamp / 1000).isoformat()
                        if user.user_metadata.last_sign_in_timestamp else None
                    ),
                })
            page = page.get_next_page()

        users.sort(key=lambda x: x["last_login"] or "", reverse=True)

        return {"total_users": len(users), "users": users}

    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update-role")
async def update_user_role(request: UpdateRoleRequest, authorization: str = Header(...)):
    """
    Allows an admin to update another user's role.
    - If user is not an admin, make them admin.
    - If user is already an admin, revoke admin rights.
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)

        if not decoded_token.get("admin"):
            raise HTTPException(status_code=403, detail="Access forbidden: admin privileges required")

        if decoded_token.get("uid") == request.uid:
            raise HTTPException(status_code=400, detail="You cannot modify your own role")

        target_user = auth.get_user(request.uid)
        current_claims = target_user.custom_claims or {}

        if current_claims.get("admin", False):
            auth.set_custom_user_claims(request.uid, {})
            new_role = "user"
        else:
            auth.set_custom_user_claims(request.uid, {"admin": True})
            new_role = "admin"

        return {
            "message": f"User role updated successfully. New role: {new_role}",
            "uid": request.uid,
            "email": target_user.email,
            "new_role": new_role
        }

    except auth.UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete-user")
async def delete_user(request: DeleteUserRequest, authorization: str = Header(...)):
    """
    Allows an admin to delete any user's account.
    Admin cannot delete their own account.
    Revokes all tokens before deletion to prevent continued access.
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)

        if not decoded_token.get("admin"):
            raise HTTPException(status_code=403, detail="Access forbidden: admin privileges required")

        if decoded_token.get("uid") == request.uid:
            raise HTTPException(status_code=400, detail="You cannot delete your own admin account")

        user = auth.get_user(request.uid)

        auth.revoke_refresh_tokens(request.uid)

        auth.delete_user(request.uid)

        return {
            "message": "User deleted successfully and all tokens revoked",
            "uid": user.uid,
            "email": user.email,
            "display_name": user.display_name
        }

    except auth.UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update-username")
async def update_username(request: UpdateUsernameRequest, authorization: str = Header(...)):
    """
    Allows an admin to update a user's display name.
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)

        if not decoded_token.get("admin"):
            raise HTTPException(status_code=403, detail="Access forbidden: admin privileges required")

        user = auth.get_user(request.uid)

        updated_user = auth.update_user(
            request.uid,
            display_name=request.new_name
        )

        return {
            "message": "User name updated successfully",
            "uid": updated_user.uid,
            "email": updated_user.email,
            "new_name": updated_user.display_name
        }

    except auth.UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invite-user")
async def invite_user(request: InviteUserRequest, authorization: str = Header(...)):
    """
    Allows an admin to invite a user via email with a secure, encrypted invite link.
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)

        if not decoded_token.get("admin"):
            raise HTTPException(status_code=403, detail="Access forbidden: admin privileges required")

        data_to_encrypt = f"{request.email}|{request.role}"
        encrypted_data = fernet.encrypt(data_to_encrypt.encode()).decode()
        safe_token = base64.urlsafe_b64encode(encrypted_data.encode()).decode()

        invite_link = f"http://localhost:3000/register?token={safe_token}"

        subject = "You're Invited to Join the Finance Analytics"
        html_content = f"""
        <html>
            <body>
                <h2>You've been invited to join our project!</h2>
                <p>Hello,</p>
                <p>You’ve been invited to join our platform as a <strong>{request.role}</strong>.</p>
                <p>Click the link below to login and get started:</p>
                <a href="{invite_link}" target="_blank" style="background-color:#4CAF50;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;">Join Now</a>
                <br><br>
                <p>If the button doesn’t work, copy and paste this URL into your browser:</p>
                <p>{invite_link}</p>
                <p>Best regards,<br>Team</p>
            </body>
        </html>
        """
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = SENDER_EMAIL
        message["To"] = request.email
        message.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, request.email, message.as_string())

        return {"message": "Invitation email sent successfully", "to": request.email, "role": request.role}

    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_platform_stats(authorization: str = Header(...)):
    try:
        decoded_token = verify_user(authorization)
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed Authorization header")

        id_token = authorization.split("Bearer ")[-1].strip()

        try:
            decoded_token = auth.verify_id_token(id_token)
        except auth.InvalidIdTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        except auth.ExpiredIdTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
        except auth.RevokedIdTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Failed to verify authentication token")

        is_admin = decoded_token.get("admin", False)

        try:
            total_users = 0
            page = auth.list_users()
            while page:
                total_users += len(page.users)
                page = page.get_next_page()
        except Exception as e:
            logging.error(f"Error listing users: {e}")
            total_users = 0  
        try:
            chatbots_ref = db.collection("chatbots")
            if is_admin:
                chatbots_query = chatbots_ref.where("status", "==", "active")
            else:
                chatbots_query = chatbots_ref.where("status", "==", "active").where("is_visible", "==", True)
            total_chatbots = len(list(chatbots_query.stream()))
        except Exception as e:
            logging.error(f"Error fetching chatbots: {e}")
            total_chatbots = 0

        try:
            dashboards_ref = db.collection("dashboards")
            if is_admin:
                dashboards_query = dashboards_ref.where("status", "==", "active")
            else:
                dashboards_query = dashboards_ref.where("status", "==", "active").where("is_visible", "==", True)
            total_dashboards = len(list(dashboards_query.stream()))
        except Exception as e:
            logging.error(f"Error fetching dashboards: {e}")
            total_dashboards = 0

        return {
            "success": True,
            "total_users": total_users,
            "total_chatbots": total_chatbots,
            "total_dashboards": total_dashboards,
            "is_admin": is_admin
        }

    except HTTPException as http_ex:
        raise http_ex 
    except Exception as e:
        logging.exception("Unexpected server error in /stats endpoint")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.get("/recent-activity")
async def get_recent_activity(
    authorization: str = Header(...),
    limit: int = 20
):
    try:
        decoded_token = verify_admin(authorization)
        token = verify_user(authorization)
        if limit < 1 or limit > 100:
            limit = 20
        
        activities = []
        users_list = []
        page = auth.list_users()
        while page:
            for user in page.users:
                if user.user_metadata.creation_timestamp:
                    users_list.append({
                        "type": "user_created",
                        "timestamp": datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000, tz=timezone.utc),
                        "user_email": user.email,
                        "user_name": user.display_name or "N/A",
                        "uid": user.uid
                    })
            page = page.get_next_page()
        
        activities.extend(users_list)

        chatbots_created = db.collection("chatbots").where("status", "==", "active").stream()
        for doc in chatbots_created:
            data = doc.to_dict()
            if data.get("created_at"):
                ts = data["created_at"]
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                activities.append({
                    "type": "chatbot_created",
                    "timestamp": ts,
                    "chatbot_id": data.get("chatbot_id"),
                    "chatbot_name": data.get("name"),
                    "created_by": data.get("created_by"),
                    "is_visible": data.get("is_visible", False)
                })

        chatbots_updated = db.collection("chatbots").where("status", "==", "active").stream()
        for doc in chatbots_updated:
            data = doc.to_dict()
            if data.get("updated_at") and data.get("updated_at") != data.get("created_at"):
                ts = data["updated_at"]
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                activities.append({
                    "type": "chatbot_updated",
                    "timestamp": ts,
                    "chatbot_id": data.get("chatbot_id"),
                    "chatbot_name": data.get("name"),
                    "updated_by": data.get("updated_by", data.get("created_by")),
                    "is_visible": data.get("is_visible", False)
                })

        dashboards_created = db.collection("dashboards").where("status", "==", "active").stream()
        for doc in dashboards_created:
            data = doc.to_dict()
            if data.get("created_at"):
                ts = data["created_at"]
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                activities.append({
                    "type": "dashboard_created",
                    "timestamp": ts,
                    "dashboard_id": data.get("dashboard_id"),
                    "dashboard_name": data.get("name"),
                    "created_by": data.get("created_by"),
                    "is_visible": data.get("is_visible", False)
                })

        dashboards_updated = db.collection("dashboards").where("status", "==", "active").stream()
        for doc in dashboards_updated:
            data = doc.to_dict()
            if data.get("updated_at") and data.get("updated_at") != data.get("created_at"):
                ts = data["updated_at"]
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                activities.append({
                    "type": "dashboard_updated",
                    "timestamp": ts,
                    "dashboard_id": data.get("dashboard_id"),
                    "dashboard_name": data.get("name"),
                    "updated_by": data.get("updated_by", data.get("created_by")),
                    "is_visible": data.get("is_visible", False)
                })

        # Ensure consistent UTC-aware sorting
        activities.sort(key=lambda x: x["timestamp"].astimezone(timezone.utc), reverse=True)
        activities = activities[:limit]

        def get_time_ago(timestamp):
            if not isinstance(timestamp, datetime):
                return "Unknown"
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = now - timestamp
            seconds = diff.total_seconds()
            if seconds < 60:
                return "just now"
            elif seconds < 3600:
                minutes = int(seconds / 60)
                return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            elif seconds < 2592000:
                days = int(seconds / 86400)
                return f"{days} day{'s' if days != 1 else ''} ago"
            elif seconds < 31536000:
                months = int(seconds / 2592000)
                return f"{months} month{'s' if months != 1 else ''} ago"
            else:
                years = int(seconds / 31536000)
                return f"{years} year{'s' if years != 1 else ''} ago"
        
        for activity in activities:
            activity["time_ago"] = get_time_ago(activity["timestamp"])
            if isinstance(activity["timestamp"], datetime):
                activity["timestamp"] = activity["timestamp"].astimezone(timezone.utc).isoformat()
        
        return {
            "success": True,
            "total_activities": len(activities),
            "limit": limit,
            "activities": activities
        }

    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/send-email")
async def send_email(
    request: SendEmailRequest,
    authorization: str = Header(...)
):
    """
    Sends an email to lucrieffel8@gmail.com
    Only accessible to authenticated users.
    """
    try:
        decoded_token = verify_user(authorization)
        
        if not all([SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD]):
            raise HTTPException(
                status_code=500, 
                detail="Email server not configured properly"
            )
        
        message = MIMEMultipart()
        message["From"] = request.from_email
        message["To"] = "m.abdulkabirkhan@gmail.com"
        message["Subject"] = request.subject
        
        message.attach(MIMEText(request.body, "plain"))
        
        with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT)) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(message)
        
        logging.info(f"Email sent from {request.from_email} to lucrieffel8@gmail.com by user {decoded_token.get('uid')}")
        
        return {
            "message": "Email sent successfully",
            "to": "lucrieffel8@gmail.com",
            "subject": request.subject,
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
    
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired ID token")
    except Exception as e:
        logging.error(f"Email send error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))