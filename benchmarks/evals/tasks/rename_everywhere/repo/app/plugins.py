from app import store

HANDLERS = {"user": "fetch_user"}


def call(kind, value):
    return getattr(store, HANDLERS[kind])(value)
