from peewee import AutoField, CharField, DateTimeField

from app.database import BaseModel


class User(BaseModel):
    id = AutoField()
    username = CharField(unique=True, max_length=100)
    email = CharField(unique=True, max_length=255)
    created_at = DateTimeField()

    class Meta:
        table_name = "users"
