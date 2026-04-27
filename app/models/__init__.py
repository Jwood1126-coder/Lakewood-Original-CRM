"""All models imported here so Alembic autogenerate sees them."""
from app.models.client import Client  # noqa: F401
from app.models.conversation import Conversation, Message  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.photo import Photo  # noqa: F401
from app.models.property import Property  # noqa: F401
from app.models.setting import Setting  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.visit import Visit  # noqa: F401
