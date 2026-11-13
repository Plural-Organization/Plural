import app.store as data


def nightly():
    return [data.fetch_user(key) for key in data.USERS]
