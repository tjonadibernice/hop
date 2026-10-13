from sqlalchemy import Column, ForeignKey, Table

from app.models.base import Base

# Which topics each page belongs to (a page can have several)
page_topics = Table(
    "page_topics",
    Base.metadata,
    Column("page_id", ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
)

# Which topics each user picked as interests
user_interests = Table(
    "user_interests",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
)
