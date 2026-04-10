from datetime import datetime
from bson.objectid import ObjectId


class Interaction:
    """MongoDB Interaction model for post engagement"""

    collection_name = "interactions"

    def __init__(self, post_id, user_id, interaction_type,
                 content=None, created_at=None, _id=None):

        self._id = _id or ObjectId()
        self.post_id = ObjectId(post_id) if not isinstance(post_id, ObjectId) else post_id
        self.user_id = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        self.type = interaction_type  # like / comment / share
        self.content = content  # فقط للـ comments
        self.created_at = created_at or datetime.utcnow()

    # 🔹 تحويل لـ JSON (important لل frontend)
    def to_dict(self):
        return {
            "_id": str(self._id),
            "post_id": str(self.post_id),
            "user_id": str(self.user_id),
            "type": self.type,
            "content": self.content,
            "created_at": self.created_at.isoformat()
        }

    # 🔹 من MongoDB document → object
    @classmethod
    def from_dict(cls, data):
        return cls(
            _id=data.get("_id"),
            post_id=data.get("post_id"),
            user_id=data.get("user_id"),
            interaction_type=data.get("type"),
            content=data.get("content"),
            created_at=data.get("created_at")
        )