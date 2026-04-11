"""Utility functions for LinkedIn user management"""
from app.models.user import User
from flask import current_app
from bson.objectid import ObjectId


def get_user_by_email(email):
    """Retrieve user from MongoDB by email"""
    try:
        collection = current_app.mongo["autoposter"]["users"]
        user_doc = collection.find_one({"email": email})
        if user_doc:
            return User.from_dict(user_doc)
        return None
    except Exception as e:
        print(f"Error retrieving user from MongoDB: {str(e)}")
        return None


def get_user_by_id(user_id):
    """Retrieve user from MongoDB by ID"""
    try:
        collection = current_app.mongo["autoposter"]["users"]
        # Try ObjectId first, then fall back to string ID
        try:
            user_doc = collection.find_one({"_id": ObjectId(user_id)})
        except:
            user_doc = collection.find_one({"_id": user_id})
        if user_doc:
            return User.from_dict(user_doc)
        return None
    except Exception as e:
        print(f"Error retrieving user from MongoDB: {str(e)}")
        return None


def get_author_data(user_or_email):
    """
    Get author data for use in ugcPost API and other content operations.
    
    Args:
        user_or_email: Either a User object or email string
        
    Returns:
        dict: Author data containing id, email, name, picture, etc.
    """
    if isinstance(user_or_email, str):
        user = get_user_by_email(user_or_email)
        if not user:
            return None
    else:
        user = user_or_email
    
    return user.to_author_dict() if user else None


def get_author_data_by_identity(identity):
    """
    Get author data from JWT identity (typically email).
    Useful in route handlers where identity comes from JWT claims.
    
    Args:
        identity: JWT identity (usually email)
        
    Returns:
        dict: Author data or None if user not found
    """
    return get_author_data(identity)
