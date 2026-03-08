from datetime import datetime
from bson.objectid import ObjectId


class User:
    """MongoDB User model for OAuth authentication"""
    
    collection_name = "users"
    
    def __init__(self, email, password=None, linkedin_id=None, first_name=None, 
                 last_name=None, profile_picture=None, locale=None, 
                 linkedin_data=None, oauth_provider=None, role="FREE", _id=None):
        self._id = _id
        self.email = email
        self.password = password
        self.linkedin_id = linkedin_id
        self.first_name = first_name
        self.last_name = last_name
        self.profile_picture = profile_picture
        self.locale = locale
        self.linkedin_data = linkedin_data
        self.oauth_provider = oauth_provider
        self.role = role
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def to_dict(self):
        """Convert to MongoDB document"""
        data = {
            "email": self.email,
            "password": self.password,
            "linkedin_id": self.linkedin_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "profile_picture": self.profile_picture,
            "locale": self.locale,
            "linkedin_data": self.linkedin_data,
            "oauth_provider": self.oauth_provider,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return data
    
    @classmethod
    def from_dict(cls, data):
        """Create User object from MongoDB document"""
        user = cls(
            email=data.get("email"),
            password=data.get("password"),
            linkedin_id=data.get("linkedin_id"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            profile_picture=data.get("profile_picture"),
            locale=data.get("locale"),
            linkedin_data=data.get("linkedin_data"),
            oauth_provider=data.get("oauth_provider"),
            role=data.get("role", "FREE"),
            _id=data.get("_id")
        )
        if "created_at" in data:
            user.created_at = data["created_at"]
        if "updated_at" in data:
            user.updated_at = data["updated_at"]
        return user
    
    def __repr__(self):
        return f"<User {self.email}>"
    
    def to_author_dict(self):
        """Return author data for use in ugcPost API"""
        return {
            "id": str(self._id) if self._id else None,
            "email": self.email,
            "name": f"{self.first_name or ''} {self.last_name or ''}".strip() or self.email,
            "picture": self.profile_picture,
            "provider": self.oauth_provider,
            "linkedin_id": self.linkedin_id
        }