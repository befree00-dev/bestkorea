from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "글쓰기·댓글·추천은 로그인 후 이용할 수 있습니다."
login_manager.login_message_category = "info"
csrf = CSRFProtect()
