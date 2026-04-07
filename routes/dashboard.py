from fastapi import APIRouter, HTTPException, Header
from firebase_admin import auth, firestore
from typing import Optional
from datetime import datetime
import uuid
from utils.auth import verify_admin, verify_user
from models.dashboard import CreateDashboardRequest, UpdateDashboardRequest

router = APIRouter()
db = firestore.client()

@router.post("/")
async def create_dashboard(
    request: CreateDashboardRequest,
    authorization: str = Header(...)
):
    """
    Create a new dashboard (ADMIN ONLY)
    Dashboards are hidden by default
    """
    try:
        token = verify_user(authorization)
        decoded_token = verify_admin(authorization)
        
        dashboard_id = str(uuid.uuid4())
        
        dashboard_data = {
            "dashboard_id": dashboard_id,
            "name": request.name,
            "description": request.description,
            "category": request.category,
            "dashboard_link": str(request.dashboard_link),
            "is_visible": False,  # Hidden by default
            "created_by": decoded_token.get("email"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "status": "active"
        }
        
        db.collection("dashboards").document(dashboard_id).set(dashboard_data)
        
        return {
            "success": True,
            "message": "Dashboard created successfully (hidden by default)",
            "dashboard_id": dashboard_id,
            "is_visible": False,
            "dashboard": dashboard_data
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/")
async def get_all_dashboards(authorization: str = Header(...)):
    """
    Get all dashboards
    - Admins: See all dashboards (visible and hidden)
    - Users: See only visible dashboards
    """
    try:
        decoded_token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)
        
        is_admin = decoded_token.get("admin", False)
        
        dashboards_ref = db.collection("dashboards")
        
        if is_admin:
            # Admin sees all dashboards
            query = dashboards_ref.where("status", "==", "active")
        else:
            # Users see only visible dashboards
            query = dashboards_ref.where("status", "==", "active").where("is_visible", "==", True)
        
        docs = query.stream()
        
        dashboards = []
        for doc in docs:
            dashboard_data = doc.to_dict()
            dashboards.append(dashboard_data)
        
        dashboards.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
        
        return {
            "success": True,
            "total_dashboards": len(dashboards),
            "is_admin": is_admin,
            "dashboards": dashboards
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch("/{dashboard_id}/visibility")
async def toggle_dashboard_visibility(
    dashboard_id: str,
    authorization: str = Header(...)
):
    """
    Toggle dashboard visibility (ADMIN ONLY)
    If visible, makes it hidden
    If hidden, makes it visible
    """
    try:
        token = verify_user(authorization)
        decoded_token = verify_admin(authorization)
        
        dashboard_ref = db.collection("dashboards").document(dashboard_id)
        dashboard_doc = dashboard_ref.get()
        
        if not dashboard_doc.exists:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        dashboard_data = dashboard_doc.to_dict()
        
        if dashboard_data.get("status") != "active":
            raise HTTPException(status_code=400, detail="Cannot modify inactive dashboard")
        
        # Toggle visibility
        current_visibility = dashboard_data.get("is_visible", False)
        new_visibility = not current_visibility
        
        dashboard_ref.update({
            "is_visible": new_visibility,
            "updated_at": datetime.utcnow(),
            "updated_by": decoded_token.get("email")
        })
        
        return {
            "success": True,
            "message": f"Dashboard visibility updated to {'visible' if new_visibility else 'hidden'}",
            "dashboard_id": dashboard_id,
            "visibility": new_visibility
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    request: UpdateDashboardRequest,
    authorization: str = Header(...)
):
    """
    Update dashboard details (ADMIN ONLY)
    Only provided fields will be updated
    """
    try:
        token = verify_user(authorization)
        decoded_token = verify_admin(authorization)
        
        dashboard_ref = db.collection("dashboards").document(dashboard_id)
        dashboard_doc = dashboard_ref.get()
        
        if not dashboard_doc.exists:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        dashboard_data = dashboard_doc.to_dict()
        
        if dashboard_data.get("status") != "active":
            raise HTTPException(status_code=400, detail="Cannot update inactive dashboard")
        
        # Build update dictionary with only provided fields
        update_data = {
            "updated_at": datetime.utcnow(),
            "updated_by": decoded_token.get("email")
        }
        
        if request.name is not None:
            update_data["name"] = request.name
        
        if request.description is not None:
            update_data["description"] = request.description
        
        if request.category is not None:
            update_data["category"] = request.category
        
        if request.dashboard_link is not None:
            update_data["dashboard_link"] = str(request.dashboard_link)
        
        dashboard_ref.update(update_data)
        
        # Get updated dashboard
        updated_dashboard = dashboard_ref.get().to_dict()
        
        return {
            "success": True,
            "message": "Dashboard updated successfully",
            "dashboard_id": dashboard_id,
            "updated_fields": list(update_data.keys()),
            "dashboard": updated_dashboard
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: str,
    authorization: str = Header(...)
):
    """
    Delete a dashboard (ADMIN ONLY)
    Performs soft delete by setting status to 'deleted'
    """
    try:
        token = verify_user(authorization)
        decoded_token = verify_admin(authorization)
        
        dashboard_ref = db.collection("dashboards").document(dashboard_id)
        dashboard_doc = dashboard_ref.get()
        
        if not dashboard_doc.exists:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        dashboard_data = dashboard_doc.to_dict()
        
        if dashboard_data.get("status") == "deleted":
            raise HTTPException(status_code=400, detail="Dashboard already deleted")
        
        # Soft delete
        dashboard_ref.update({
            "status": "deleted",
            "deleted_at": datetime.utcnow(),
            "deleted_by": decoded_token.get("email")
        })
        
        return {
            "success": True,
            "message": "Dashboard deleted successfully",
            "dashboard_id": dashboard_id,
            "deleted_at": datetime.utcnow().isoformat()
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    authorization: str = Header(...)
):
    """
    Get a single dashboard by ID
    - Admins: Can view any dashboard
    - Users: Can only view visible dashboards
    """
    try:
        token = verify_user(authorization)
        id_token = authorization.split("Bearer ")[-1]
        decoded_token = auth.verify_id_token(id_token)
        
        is_admin = decoded_token.get("admin", False)
        
        dashboard_ref = db.collection("dashboards").document(dashboard_id)
        dashboard_doc = dashboard_ref.get()
        
        if not dashboard_doc.exists:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        dashboard_data = dashboard_doc.to_dict()
        
        if dashboard_data.get("status") != "active":
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        # Check visibility permissions
        if not is_admin and not dashboard_data.get("is_visible", False):
            raise HTTPException(status_code=403, detail="Access forbidden: dashboard is hidden")
        
        return {
            "success": True,
            "dashboard": dashboard_data
        }
    
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")