from app.store import fetch_user


def show(user_id):
    return {"name": fetch_user(user_id)}
