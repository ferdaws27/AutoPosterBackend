from datetime import datetime
from bson.objectid import ObjectId


class Post:
    """MongoDB Post model for social media posts"""

    collection_name = "posts"

    def __init__(self, user_id, content, platforms=None, status="draft",
                 schedule_date=None, schedule_time=None, engagement=None,
                 content_type=None, content_type_confidence=None,
                 created_at=None, updated_at=None, _id=None):
        self._id = _id or ObjectId()
        self.user_id = user_id
        self.content = content
        self.platforms = platforms or {}
        self.status = status
        self.schedule_date = schedule_date
        self.schedule_time = schedule_time
        self.engagement = engagement or {}
        self.content_type = content_type
        self.content_type_confidence = content_type_confidence
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """Convert to JSON-safe dict (FIX ObjectId + datetime)"""
        return {
            "_id": str(self._id) if self._id else None,
            "user_id": self.user_id,
            "content": self.content,
            "platforms": self.platforms,
            "status": self.status,
            "schedule_date": self.schedule_date,
            "schedule_time": self.schedule_time,
            "engagement": self.engagement,
            "content_type": self.content_type,
            "content_type_confidence": self.content_type_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    @classmethod
    def from_dict(cls, data):
        """Create Post object from MongoDB document"""
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id"),
            content=data.get("content"),
            platforms=data.get("platforms", {}),
            status=data.get("status", "draft"),
            schedule_date=data.get("schedule_date"),
            schedule_time=data.get("schedule_time"),
            engagement=data.get("engagement", {}),
            content_type=data.get("content_type"),
            content_type_confidence=data.get("content_type_confidence"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def update_engagement(self, platform, likes=0, comments=0, shares=0, views=0):
        if platform not in self.engagement:
            self.engagement[platform] = {}

        self.engagement[platform]["likes"] = likes
        self.engagement[platform]["comments"] = comments
        self.engagement[platform]["shares"] = shares
        self.engagement[platform]["views"] = views
        self.updated_at = datetime.utcnow()

    def mark_as_published(self, platform):
        if platform not in self.platforms:
            self.platforms[platform] = True
        self.status = "published"
        self.updated_at = datetime.utcnow()

    def mark_as_scheduled(self, schedule_date, schedule_time):
        self.status = "scheduled"
        self.schedule_date = schedule_date
        self.schedule_time = schedule_time
        self.updated_at = datetime.utcnow()