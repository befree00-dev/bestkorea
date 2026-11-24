import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, TextAreaField, URLField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, URL, ValidationError

from .constants import BOARDS, COUNTRIES
from .models import User


class SignupForm(FlaskForm):
    username = StringField("닉네임", validators=[DataRequired(), Length(2, 20)])
    email = StringField("이메일", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("비밀번호", validators=[DataRequired(), Length(8, 128)])
    password2 = PasswordField(
        "비밀번호 확인", validators=[DataRequired(), EqualTo("password", "비밀번호가 일치하지 않습니다.")]
    )
    agree = BooleanField("이용약관 및 개인정보처리방침에 동의합니다", validators=[DataRequired("약관에 동의해 주세요.")])

    def validate_username(self, field):
        if not re.fullmatch(r"[0-9A-Za-z가-힣_]+", field.data):
            raise ValidationError("닉네임은 한글·영문·숫자·밑줄(_)만 사용할 수 있습니다.")
        if User.query.filter(User.username.ilike(field.data)).first():
            raise ValidationError("이미 사용 중인 닉네임입니다.")

    def validate_email(self, field):
        if User.query.filter(User.email.ilike(field.data.strip())).first():
            raise ValidationError("이미 가입된 이메일입니다.")


class LoginForm(FlaskForm):
    email = StringField("이메일", validators=[DataRequired(), Email()])
    password = PasswordField("비밀번호", validators=[DataRequired()])
    remember = BooleanField("로그인 유지")


class PostForm(FlaskForm):
    board = SelectField("게시판", choices=[(k, v[0]) for k, v in BOARDS.items()])
    title = StringField("제목", validators=[DataRequired(), Length(2, 200)])
    body = TextAreaField("내용", validators=[DataRequired(), Length(2, 20000)])
    source_url = URLField("원문 링크 (해외 뉴스 제보 시)", validators=[Optional(), URL(), Length(max=1000)])
    country = SelectField(
        "국가/출처", choices=[("", "선택 안 함")] + [(k, f"{v[1]} {v[0]}") for k, v in COUNTRIES.items()],
        validators=[Optional()],
    )


class CommentForm(FlaskForm):
    body = TextAreaField("댓글", validators=[DataRequired(), Length(1, 2000)])
