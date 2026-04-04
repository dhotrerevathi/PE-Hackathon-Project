from peewee import AutoField, CharField, DateTimeField, ForeignKeyField, TextField

from app.database import BaseModel
from app.models.url import Url
from app.models.user import User


class Event(BaseModel):
    id = AutoField()
    url = ForeignKeyField(Url, backref="events", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="events", null=True, on_delete="SET NULL")
    event_type = CharField(max_length=50)
    timestamp = DateTimeField()
    details = TextField(null=True)

    class Meta:
        table_name = "events"
