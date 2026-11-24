import pytest

from app import create_app
from app.extensions import db
from app.models import User
from config import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user(app):
    u = User(username="tester", email="t@example.com")
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email="t@example.com", password="password123"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)
