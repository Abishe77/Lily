import base64
import io
import json
import logging
import re
import secrets
import hashlib
import hmac
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta , timezone

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel , Field , ValidationError , ConfigDict
from typing import Any , Literal
from pypdf import PdfReader
from docx import Document
from pptx import Presentation
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import os
import resend


load_dotenv()
logger = logging.getLogger("lily")
logging.basicConfig(level=logging.INFO)

app = FastAPI()
security = HTTPBearer()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
OTP_EXPIRE_MINUTES = 5
OTP_RESEND_COOLDOWN_SECONDS = 45
OAUTH_STATE_EXPIRE_MINUTES = 10
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

REGISTER_RATE_LIMIT = "5/minute"
LOGIN_RATE_LIMIT = "10/minute"
OTP_VERIFY_RATE_LIMIT = "10/minute"
OAUTH_RATE_LIMIT = "20/minute"
CLAUDE_ENDPOINT_RATE_LIMIT = "10/minute"

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not configured")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    logger.warning(
        "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured — "
        "Google login endpoints will fail if used."
    )

GOOGLE_REDIRECT_URI = "http://127.0.0.1:8000/auth/google/callback"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
LILY_EMAIL_FROM = os.getenv("LILY_EMAIL_FROM")

if not RESEND_API_KEY:
    raise RuntimeError("RESEND_API_KEY is not configured")

resend.api_key = RESEND_API_KEY

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db_connection():
    return psycopg2.connect(
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT"),
    )

db_pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    dbname=os.environ.get("DB_NAME"),
    user=os.environ.get("DB_USER"),
    password=os.environ.get("DB_PASSWORD"),
    host=os.environ.get("DB_HOST"),
    port=os.environ.get("DB_PORT"),
)


@contextmanager
def db_cursor():
    conn = db_pool.getconn()
    cur = conn.cursor()

    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        db_pool.putconn(conn)


def create_access_token(user_id: int) -> str:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT auth_version
            FROM users
            WHERE id = %s;
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=401,
            detail="User account not found"
        )

    auth_version = row[0]

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "user_id": user_id,
        "auth_version": auth_version,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)

def hash_refresh_token( token : str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_refresh_session(user_id : int) -> str:
    refresh_token = create_refresh_token()
    token_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)


    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO refresh_sessions
            (user_id , token_hash , expires_at)
            VALUES (%s , %s , %s)
            """,
            (user_id , token_hash, expires_at)
        )

    return refresh_token    


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("user_id")
        token_auth_version = payload.get("auth_version")

        if user_id is None or token_auth_version is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

        with db_cursor() as cur:
            cur.execute(
                """
                SELECT auth_version
                FROM users
                WHERE id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise HTTPException(
                status_code=401,
                detail="User account not found"
            )

        current_auth_version = row[0]

        if token_auth_version != current_auth_version:
            raise HTTPException(
                status_code=401,
                detail="Authentication session is no longer valid"
            )

        return user_id

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )


def validate_password(password: str):
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain an uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain a lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain a number"
    if not any(not c.isalnum() for c in password):
        return False, "Password must contain a special character"
    return True, None


def generate_otp() -> str:
    return str(secrets.randbelow(900000) + 100000)

def hash_otp(otp : str) -> str:
    return hmac.new(
        SECRET_KEY.encode(),
        otp.encode(),
        hashlib.sha256
    ).hexdigest()


def validate_email_format(email: str):
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=422, detail="Invalid email format")


def check_login_lockout(email: str):
    with db_cursor() as cur:
        cur.execute("SELECT locked_until FROM login_attempts WHERE email = %s;", (email,))
        row = cur.fetchone()

        if row is None or row[0] is None:
            return

        locked_until = row[0]
        cur.execute("SELECT NOW() < %s;", (locked_until,))
        still_locked = cur.fetchone()[0]

        if still_locked:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again after {locked_until.strftime('%H:%M:%S')}",
            )

        cur.execute("DELETE FROM login_attempts WHERE email = %s;", (email,))


def record_failed_login(email: str):
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO login_attempts (email, attempts, locked_until)
            VALUES (%s, 1, NULL)
            ON CONFLICT (email) DO UPDATE SET
                attempts = login_attempts.attempts + 1,
                locked_until = CASE
                    WHEN login_attempts.attempts + 1 >= %s
                    THEN NOW() + (%s * INTERVAL '1 minute')
                    ELSE login_attempts.locked_until
                END;
            """,
            (email, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES),
        )


def clear_login_attempts(email: str):
    with db_cursor() as cur:
        cur.execute("DELETE FROM login_attempts WHERE email = %s;", (email,))


def store_otp(email: str, user_id: int, purpose: str) -> str:
    otp = generate_otp()
    otp_hash = hash_otp(otp)

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT EXTRACT(EPOCH FROM (NOW() - created_at))
            FROM otp_codes
            WHERE email = %s AND purpose = %s;
            """,
            (email, purpose),
        )
        row = cur.fetchone()

        if row is not None and row[0] is not None and row[0] < OTP_RESEND_COOLDOWN_SECONDS:
            wait_seconds = int(OTP_RESEND_COOLDOWN_SECONDS - row[0])
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait_seconds} seconds before requesting another OTP",
            )

        cur.execute(
            """
            INSERT INTO otp_codes (user_id, email, purpose, otp_hash, attempts, created_at, expires_at)
            VALUES (%s, %s, %s, %s, 0, NOW(), NOW() + (%s * INTERVAL '1 minute'))
            ON CONFLICT (email, purpose) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                otp_hash = EXCLUDED.otp_hash,
                attempts = 0,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at;
            """,
            (user_id, email, purpose, otp_hash, OTP_EXPIRE_MINUTES),
        )

    return otp


def consume_otp(email: str, data_otp: str, purpose: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, otp_hash, attempts, NOW() > expires_at
            FROM otp_codes
            WHERE email = %s AND purpose = %s;
            """,
            (email, purpose),
        )
        row = cur.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="OTP not found")

        otp_id, user_id, stored_otp_hash, attempts, expired = row

        if expired:
            cur.execute("DELETE FROM otp_codes WHERE id = %s;", (otp_id,))
            raise HTTPException(status_code=400, detail="OTP expired")

        if attempts >= 5:
            cur.execute("DELETE FROM otp_codes WHERE id = %s;", (otp_id,))
            raise HTTPException(status_code=429, detail="Too many invalid attempts")

        data_otp_hash = hash_otp(data_otp)

        if not hmac.compare_digest(data_otp_hash, stored_otp_hash):
            cur.execute(
                "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s;",
                  (otp_id,))
            raise HTTPException(status_code=400, detail="Invalid OTP")

        cur.execute("DELETE FROM otp_codes WHERE id = %s;", (otp_id,))

    return user_id

def send_otp_email(email: str, otp: str):
    try:
        resend.Emails.send({
            "from": LILY_EMAIL_FROM,
            "to": [email],
            "subject": "Your Lily verification code",
            "html": f"""
                <h2>Your Lily verification code</h2>
                <p>Your verification code is:</p>
                <h1>{otp}</h1>
                <p>This code expires in 5 minutes.</p>
                <p>If you did not request this code, you can ignore this email.</p>
            """
        })
    except Exception:
        logger.exception("Failed to send OTP email")
        raise HTTPException(
            status_code=502,
            detail="Failed to send verification email"
        )

def send_password_reset_email(email: str, otp: str):
    try:
        resend.Emails.send({
            "from": LILY_EMAIL_FROM,
            "to": [email],
            "subject": "Reset your Lily password",
            "html": f"""
                <h2>Reset your Lily password</h2>
                <p>Your password reset code is:</p>
                <h1>{otp}</h1>
                <p>This code expires in 5 minutes.</p>
                <p>If you did not request a password reset, you can ignore this email.</p>
            """
        })
    except Exception:
        logger.exception("Failed to send password reset email")
        raise HTTPException(
            status_code=502,
            detail="Failed to send password reset email"
        )    


class UserRegister(BaseModel):
    name: str
    email: str
    password: str


class VerifyRegistrationOTP(BaseModel):
    email: str
    otp: str


class UserLogin(BaseModel):
    email: str
    password: str


class VerifyLoginOTP(BaseModel):
    email: str
    otp: str

class ForgotPasswordRequest(BaseModel):
    email : str

class ResetPasswordRequest(BaseModel):  
    email : str
    otp : str
    new_password : str      


class UserCompanion(BaseModel):
    name: str
    gender: str
    personality_mode : str = "funny_sarcastic"


class UserStyleProfile(BaseModel):
    text: str | None = None
    image_base64: str | None = None


class GenerateNoteRequest(BaseModel):
    source_id: int
    topic: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str 

class NoteBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal[
        "heading",
        "text",
        "bullet_list",
        "numbered_list",
        "highlight",
        "example",
        "formula",
        "correction",
        "verification_note",
    ]
    content: object
    source_reference: str | None = None


class GeneratedNote(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    blocks: list[NoteBlock]     


@app.get("/")
def read_root():
    return {"message": "LILY backend is alive"}


@app.post("/register")
@limiter.limit(REGISTER_RATE_LIMIT)
def register_user(request: Request, user: UserRegister):
    email = user.email.strip().lower()
    validate_email_format(email)

    valid, error_message = validate_password(user.password)
    if not valid:
        return {"message": error_message}

    hashed_password = pwd_context.hash(user.password)

    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (name, email, hashed_pass, email_verified)
                VALUES (%s, %s, %s, FALSE)
                RETURNING id;
                """,
                (user.name.strip(), email, hashed_password),
            )
            user_id = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        return {"message": "Email already registered"}

    otp = store_otp(email, user_id, "registration")
    send_otp_email(email, otp)
   

    return {"message": "Registration successful. OTP sent."}


@app.post("/verify-registration-otp")
@limiter.limit(OTP_VERIFY_RATE_LIMIT)
def verify_registration_otp(request: Request, data: VerifyRegistrationOTP):
    email = data.email.strip().lower()
    user_id = consume_otp(email, data.otp, "registration")

    with db_cursor() as cur:
        cur.execute("UPDATE users SET email_verified = TRUE WHERE id = %s;", (user_id,))

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_session(user_id)
    return {
        "message": "Email verified successfully",
        "access_token": access_token,
        "refresh_token" : refresh_token,
        "token_type": "bearer"
    }

@app.post("/refresh")
@limiter.limit("20/minute")
def refresh_access_token(
    request: Request,
    data: RefreshTokenRequest
):
    token_hash = hash_refresh_token(data.refresh_token)

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE refresh_sessions
            SET revoked_at = NOW(),
                last_used_at = NOW()
            WHERE token_hash = %s
              AND revoked_at IS NULL
              AND expires_at > NOW()
            RETURNING id, user_id
            """,
            (token_hash,)
        )

        session = cur.fetchone()

        if not session:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired refresh token"
            )

        session_id, user_id = session

    new_access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_session(user_id)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@app.post("/logout")
@limiter.limit("20/minute")
def logout(
    request: Request,
    data: RefreshTokenRequest
):
    token_hash = hash_refresh_token(data.refresh_token)

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE refresh_sessions
            SET revoked_at = NOW(),
                last_used_at = NOW()
            WHERE token_hash = %s
              AND revoked_at IS NULL
            """,
            (token_hash,)
        )

    return {
        "message": "Logged out successfully"
    }
         



@app.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
def login_user(request: Request, user: UserLogin):
    email = user.email.strip().lower()
    check_login_lockout(email)

    with db_cursor() as cur:
        cur.execute(
            "SELECT id, hashed_pass, email_verified FROM users WHERE email = %s;",
            (email,),
        )
        result = cur.fetchone()

    if result is None:
        record_failed_login(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id, stored_hash, email_verified = result

    if stored_hash is None or not pwd_context.verify(user.password, stored_hash):
        record_failed_login(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")

    clear_login_attempts(email)
    otp = store_otp(email, user_id, "login")
    send_otp_email(email, otp)


    return {"message": "OTP sent successfully"}


@app.post("/verify-login-otp")
@limiter.limit(OTP_VERIFY_RATE_LIMIT)
def verify_login_otp(request: Request, data: VerifyLoginOTP):


    email = data.email.strip().lower()
    user_id = consume_otp(email, data.otp, "login")

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_session(user_id)
    return {
        "message": "Login successful",
        "access_token": access_token,
          "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@app.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest
):
    email = data.email.strip().lower()
    validate_email_format(email)

    with db_cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE email = %s;",
            (email,)
        )
        user = cur.fetchone()

    if user is not None:
        user_id = user[0]

        otp = store_otp(
            email,
            user_id,
            "password_reset"
        )

        send_password_reset_email(email, otp)

    return {
        "message": "If an account exists for this email, a password reset code has been sent."
    }

@app.post("/reset-password")
@limiter.limit("10/minute")
def reset_password(
    request: Request,
    data: ResetPasswordRequest
):
    email = data.email.strip().lower()
    validate_email_format(email)

    valid, error_message = validate_password(data.new_password)

    if not valid:
        raise HTTPException(
            status_code=400,
            detail=error_message
        )

    user_id = consume_otp(
        email,
        data.otp,
        "password_reset"
    )

    hashed_password = pwd_context.hash(data.new_password)

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET hashed_pass = %s,
            auth_version = auth_version + 1
            WHERE id = %s;
            """,
            (hashed_password, user_id)
        )

        cur.execute(
            """
            UPDATE refresh_sessions
            SET revoked_at = NOW(),
                last_used_at = NOW()
            WHERE user_id = %s
              AND revoked_at IS NULL;
            """,
            (user_id,)
        )

    clear_login_attempts(email)

    return {
        "message": "Password reset successfully"
    }


def build_google_flow() -> Flow:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


@app.get("/auth/google")
@limiter.limit(OAUTH_RATE_LIMIT)
def google_login(request: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google login is not configured on this server")

    flow = build_google_flow()

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )

    with db_cursor() as cur:
       cur.execute(
    """
    INSERT INTO oauth_states (state, code_verifier, expires_at)
    VALUES (%s, %s, NOW() + (%s * INTERVAL '1 minute'));
    """,
    (state, flow.code_verifier, OAUTH_STATE_EXPIRE_MINUTES),
)

    return RedirectResponse(authorization_url)


@app.get("/auth/google/callback")
@limiter.limit(OAUTH_RATE_LIMIT)
def google_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code missing")
    if not state:
        raise HTTPException(status_code=400, detail="OAuth state missing")

    with db_cursor() as cur:
        cur.execute(
    """
    SELECT code_verifier, NOW() < expires_at
    FROM oauth_states
    WHERE state = %s;
    """,
    (state,),
)
        row = cur.fetchone()

        if row is None or not row[1]:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth session")

        code_verifier = row[0]

        cur.execute("DELETE FROM oauth_states WHERE state = %s;", (state,))

    flow = build_google_flow()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code) 
    credentials = flow.credentials

    google_user = id_token.verify_oauth2_token(
        credentials.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
    )

    google_id = google_user["sub"]
    google_email = google_user["email"]
    google_name = google_user.get("name")

    if google_user.get("email_verified") is not True: raise HTTPException( status_code=403, detail="Google account email is not verified" )

    with db_cursor() as cur:
        cur.execute(
            "SELECT user_id FROM auth_accounts WHERE provider = %s AND provider_user_id = %s",
            ("google", google_id),
        )
        auth_account = cur.fetchone()

        if auth_account:
            user_id = auth_account[0]
        else:
            cur.execute("SELECT id FROM users WHERE email = %s", (google_email,))
            user = cur.fetchone()

            if user:
                user_id = user[0]
                cur.execute(
                    "UPDATE users SET email_verified = TRUE WHERE id = %s", (user_id,)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO users (name, email, hashed_pass, email_verified)
                    VALUES (%s, %s, NULL, TRUE)
                    RETURNING id
                    """,
                    (google_name, google_email),
                )
                user_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO auth_accounts (user_id, provider, provider_user_id)
                VALUES (%s, %s, %s)
                """,
                (user_id, "google", google_id),
            )

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_session(user_id)
    return {
        "message": "Google login successful",
        "access_token": access_token,
        "refresh_token" : refresh_token,
        "token_type": "bearer"
    }


@app.post("/companion")
def create_companion(user: UserCompanion, current_user: int = Depends(get_current_user)):
    with db_cursor() as cur:
      cur.execute(
    """
    INSERT INTO companions (user_id, name, gender, personality_mode)
    VALUES (%s, %s, %s , %s)
    ON CONFLICT (user_id)
    DO UPDATE SET
        name = EXCLUDED.name,
        gender = EXCLUDED.gender,
        personality_mode = EXCLUDED.personality_mode;
    """,
    (current_user, user.name, user.gender,user.personality_mode)
)
    return {"message": "Companion saved successfully"}


STYLE_ANALYSIS_PROMPT = """
Analyze the handwritten study notes in this image and create
a structural style profile for the student.

Focus on:
1. Heading style
2. Heading hierarchy
3. Bullet usage
4. Numbered lists
5. Sentence length
6. Fragments vs complete sentences
7. Abbreviations
8. Bold, underlined, or emphasized words
9. Diagrams
10. Arrows and symbols
11. Mnemonics
12. Examples
13. Whitespace
14. Information density
15. Overall organization
16. Recurring formatting patterns

Do not summarize the academic content.
Focus on HOW the student writes and organizes information.

Return a detailed textual description of the student's
note-taking style.
"""


@app.post("/style-profile")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
def create_style_profile(request: Request, profile: UserStyleProfile, current_user: int = Depends(get_current_user)):
    text_style = None
    analysed_style = None


    sample_notes_txt = None

    if profile.text and profile.text.strip():
        text_style = profile.text.strip()

    if profile.image_base64:
        try:
            response = anthropic_client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": profile.image_base64,
                                },
                            },
                            {"type": "text", "text": STYLE_ANALYSIS_PROMPT},
                        ],
                    }
                ],
            )
            analysed_style = response.content[0].text.strip()
        except Exception as e:
            logger.exception("Style image analysis failed")
            raise HTTPException(status_code=502, detail=f"Failed to analyze image: {e}")

    if text_style is None and analysed_style is None:
        raise HTTPException(status_code=400, detail="No text or image provided")

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO style_profiles (user_id, sample_notes_txt, text_style, analysed_style)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                sample_notes_txt = EXCLUDED.sample_notes_txt,
                text_style = EXCLUDED.text_style,
                analysed_style = EXCLUDED.analysed_style
            RETURNING id;
            """,
            (current_user, sample_notes_txt, text_style, analysed_style),
        )
        style_profile_id = cur.fetchone()[0]

    return {
        "message": "Style profile saved",
        "style_profile_id": style_profile_id,
        "user_id": current_user,
        "text_style": text_style,
        "analysed_style": analysed_style,
    }


SCANNED_PAGE_TRANSCRIPTION_PROMPT = """
Transcribe all handwritten and printed text visible in this page.

Return only the text itself.

Preserve:
- headings
- bullet points
- numbered lists
- equations
- important symbols
- line breaks where they are meaningful

Do not summarize.
Do not explain.
Do not add information that is not visible.
"""


def extract_text_from_scanned_pdf(pdf_bytes: bytes) -> str:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = ""

    for page_number, page in enumerate(document, start=1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        image_bytes = pixmap.tobytes("jpeg")
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        response = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64,
                            },
                        },
                        {"type": "text", "text": SCANNED_PAGE_TRANSCRIPTION_PROMPT},
                    ],
                }
            ],
        )

        page_text = "".join(block.text for block in response.content if block.type == "text")
        extracted_text += f"\n--- PAGE {page_number} ---\n{page_text}"

    document.close()
    return extracted_text.strip()

def extract_pdf_source(pdf_bytes: bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))

    page_texts = []

    for page in reader.pages:
        text = page.extract_text() or ""
        page_texts.append(text.strip())

    combined_text = "\n\n".join(
        text for text in page_texts if text
    ).strip()

    if combined_text:
        return {
            "text": combined_text,
            "pages": len(reader.pages),
            "extraction_method": "pypdf"
        }

    scanned_text = extract_text_from_scanned_pdf(pdf_bytes)

    return {
        "text": scanned_text,
        "pages": len(reader.pages),
        "extraction_method": "claude_vision"
    }

def extract_docx_source(file_bytes : bytes):
    document = Document(io.BytesIO(file_bytes))

    paragraphs = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            paragraphs.append(text)

    extracted_text = "\n\n".join(paragraphs)

    return{
        "text" : extracted_text,
        "pages" : None,
        "extraction_method" : "python_docx"
    } 

def extract_pptx_source(file_bytes: bytes):
    presentation = Presentation(io.BytesIO(file_bytes))

    slides_text = []

    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_parts = []

        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text = shape.text.strip()

                if text:
                    slide_parts.append(text)

        if slide_parts:
            slide_text = "\n\n".join(slide_parts)
            slides_text.append(
                f"--- SLIDE {slide_number} ---\n{slide_text}"
            )

    extracted_text = "\n\n".join(slides_text)

    return {
        "text": extracted_text,
        "pages": len(presentation.slides),
        "extraction_method": "python_pptx"
    }

def extract_text_source(file_bytes: bytes):
    extracted_text = file_bytes.decode("utf-8")

    return {
        "text": extracted_text,
        "pages": None,
        "extraction_method": "utf8"
    }

def extract_image_source(file_bytes: bytes, media_type: str):
    image_base64 = base64.b64encode(file_bytes).decode("utf-8")

    response = anthropic_client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": SCANNED_PAGE_TRANSCRIPTION_PROMPT,
                    },
                ],
            }
        ],
    )

    extracted_text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    ).strip()

    return {
        "text": extracted_text,
        "pages": None,
        "extraction_method": "claude_vision"
    }



@app.post("/upload-source")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    current_user: int = Depends(get_current_user)
):
    pdf_bytes = await file.read()

    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    filename = file.filename.lower()

    if filename.endswith(".pdf"):
        result = extract_pdf_source(pdf_bytes)
 
    elif filename.endswith(".docx"):
       result = extract_docx_source(pdf_bytes)

    elif filename.endswith(".pptx"):
      result = extract_pptx_source(pdf_bytes)

    elif filename.endswith(".txt") or filename.endswith(".md"):
        result = extract_text_source(pdf_bytes) 

    elif filename.endswith((".jpeg" , ".jpg", ".png" ,".webp")):
        result = extract_image_source(pdf_bytes,
             file.content_type)     
    else:
      raise HTTPException(
        status_code=400,
        detail="Unsupported file format"
    )

    extracted_text = result["text"]

    if not extracted_text:
        return {
            "message": "Could not extract any text from this PDF",
            "filename": file.filename,
            "pages": result["pages"],
            "characters_extracted": 0,
            "extraction_method": result["extraction_method"],
        }

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (user_id, filename, extracted_text ,
            characters_extracted, extraction_type)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (current_user, file.filename, extracted_text,
             len(extracted_text), result["extraction_method"]),
        )

        source_id = cur.fetchone()[0]

    return {
        "message": "Source uploaded successfully",
        "source_id": source_id,
        "user_id": current_user,
        "filename": file.filename,
        "pages": result["pages"],
        "characters_extracted": len(extracted_text),
        "extraction_method": result["extraction_method"],
    }



NOTE_BLOCK_SCHEMA_EXAMPLE = """
{
  "title": "Note title",
  "blocks": [
    {"type": "heading", "content": "Heading text"},
    {"type": "text", "content": "Text content"},
    {"type": "bullet_list", "content": ["Point 1", "Point 2"]},
    {"type": "numbered_list", "content": ["Step 1", "Step 2"]},
    {"type": "highlight", "content": "Important point"},
    {"type": "example", "content": "Example content"},
    {"type": "formula", "content": "Formula"},
    {
      "type": "correction",
      "content": "The source statement is incorrect. Corrected explanation...",
      "source_reference": "Page 2",
      "source_claim": "Original statement from the source",
      "issue": "Why the statement is incorrect",
      "corrected_content": "Corrected statement or explanation"
    },
    {
      "type": "verification_note",
      "content": "This source claim could not be confidently verified.",
      "source_reference": "Page 3",
      "claim": "Claim requiring verification",
      "note": "Reason it could not be confidently verified"
    }
  ]
}
"""


def build_note_prompt(topic: str, text_style, analysed_style, source_text: str) -> str:
    return f"""
You are Lily, a personalized AI study companion.

Your task is to transform the provided source material into accurate,
student-friendly study notes while preserving academic correctness.

You have THREE responsibilities:

1. Understand the source material.
2. Verify important factual, mathematical, logical, and technical claims.
3. Generate personalized study notes based on the verified information.

TOPIC:
{topic}

USER-DECLARED STYLE:
{text_style}

ANALYSED STYLE FROM SAMPLE NOTES:
{analysed_style}

SOURCE MATERIAL:
{source_text}


==================================================
1. SOURCE AND KNOWLEDGE BOUNDARY
==================================================

The source material is the primary reference for what the notes are about.

Use information from the source whenever it is available.

DO NOT invent:
- facts
- definitions
- formulas
- equations
- numerical values
- examples
- proofs
- algorithms
- conclusions
- historical claims
- technical explanations
- assumptions

Do not add outside information merely to make the notes sound more complete.

However, source material itself may contain mistakes.

Therefore:

SOURCE CONTENT IS NOT AUTOMATICALLY CORRECT.

You must independently verify important claims before presenting them
as established facts.


==================================================
2. CLAIM VERIFICATION
==================================================

Before generating the final notes, internally examine important claims
in the source.

Pay particular attention to:

- mathematical statements
- equations and formulas
- numerical calculations
- definitions
- theorem statements
- proofs
- logical arguments
- algorithm descriptions
- examples
- counterexamples
- conclusions
- cause-and-effect claims
- technical terminology

For mathematical or logical examples, actually test the reasoning.

If the source claims that an example demonstrates a particular property,
check whether the example actually satisfies the relevant definition.

Do NOT accept an argument merely because it sounds convincing.


==================================================
3. SOURCE ERROR DETECTION
==================================================

If a source statement is demonstrably incorrect, DO NOT silently reproduce it.

Instead:

1. Identify the incorrect statement.
2. Explain briefly why it is incorrect.
3. Provide the corrected statement.
4. Explain the correction in a student-friendly way.
5. Mark the generated block as a source correction.
6. Preserve a reference to the relevant source location when one can
   genuinely be identified.

IMPORTANT:

Never invent a source error.

Only mark something as incorrect when the contradiction can be established
with high confidence.

If a statement is unusual but potentially valid, do not correct it merely
because it differs from your expectations.


==================================================
4. UNCERTAINTY
==================================================

If you cannot confidently determine whether an important source statement
is correct, DO NOT guess.

Do not manufacture a correction.

Instead, create a verification_note block explaining that the statement
could not be reliably verified.

The student must be able to distinguish between:

- verified source information
- verified corrections
- claims requiring further verification


==================================================
5. MATHEMATICAL AND TECHNICAL SAFETY
==================================================

For mathematics, computer science, engineering, physics, statistics,
machine learning, and other technical subjects:

- preserve mathematical meaning
- preserve equations correctly
- preserve variable relationships
- preserve numerical values unless demonstrably wrong
- verify examples against the definitions they demonstrate
- verify conclusions against the preceding reasoning
- do not change notation merely for stylistic reasons
- do not simplify expressions in a way that changes their meaning

If a worked example contains an incorrect calculation, correct it only
after independently checking the calculation.

If a proof contains a logical error, identify the error rather than
pretending that the proof is valid.

If a theorem or definition is stated incorrectly, clearly distinguish
the source statement from the corrected version.


==================================================
6. SOURCE REFERENCES
==================================================

Whenever possible, associate important content with its location in
the source.

If the source contains page numbers or clearly identifiable sections,
preserve those references.

DO NOT invent page numbers or source references.

If an exact source location cannot be determined, omit the reference.


==================================================
7. PERSONALIZED NOTE STYLE
==================================================

The user's declared and analysed writing style should affect ONLY
presentation.

You may personalize:

- sentence length
- organization
- amount of explanation
- use of bullets
- use of headings
- emphasis
- visual structure
- concise versus detailed explanations

STYLE MUST NEVER OVERRIDE CORRECTNESS.

Do not intentionally introduce incorrect, incomplete, or ambiguous
explanations because they resemble the user's notes.

Do not mention the style profile in the generated notes.


==================================================
8. TOPIC RELEVANCE
==================================================

Focus on:

{topic}

Prefer information directly relevant to the requested topic.

Do not fill the notes with unrelated material merely because it appears
somewhere in the source.

Include prerequisite information only when it is necessary to understand
the requested topic.


==================================================
9. TRANSPARENT CORRECTIONS
==================================================

Never silently replace an incorrect source statement with a corrected one.

When Lily corrects the source, explicitly communicate that a correction
was made.

The student should be able to understand:

SOURCE CLAIM
→ VERIFICATION
→ PROBLEM
→ CORRECTED CLAIM
→ EXPLANATION


==================================================
10. OUTPUT BLOCK TYPES
==================================================

Use only these block types:

heading
text
bullet_list
numbered_list
highlight
example
formula
correction
verification_note


==================================================
11. BLOCK RULES
==================================================

heading:
Used for section titles.

text:
Used for normal explanations.

bullet_list:
Used for grouped points.

numbered_list:
Used for ordered procedures, conditions, or steps.

highlight:
Used for important verified facts or conclusions.

example:
Used for examples supported by the source or examples necessary to
explain a verified correction.

formula:
Used for mathematical or technical expressions.

correction:
Used ONLY when Lily has identified a demonstrably incorrect source claim
and verified the correction.

verification_note:
Used when an important source claim cannot be confidently verified.


==================================================
12. CORRECTION BLOCK
==================================================

Every correction block must communicate:

- what the source claimed
- why the claim is incorrect
- the corrected explanation

Use the correction structure defined in the JSON schema below.

Do not create a correction merely because the source explanation could
be clearer.

A correction means the original claim is actually wrong.


==================================================
13. VERIFICATION NOTE
==================================================

Use the verification_note structure defined in the JSON schema below.

Only use it when an important source claim cannot be confidently verified.

Do not use verification_note for ordinary stylistic issues.


==================================================
14. NO HALLUCINATED EXAMPLES
==================================================

Do not create new worked examples merely to make the notes look better.

If the source already contains an example, preserve its meaning.

If the source example is incorrect and Lily can verify the correction,
correct it explicitly.

Do not create new mathematical, technical, scientific, or algorithmic
examples that are not present in the source.

If a source example is incorrect and Lily can verify the correction,
correct the existing example explicitly.

When explaining a correction, use reasoning and explanation rather than
inventing a new worked example.


==================================================
15. FINAL INTERNAL AUDIT
==================================================

Before producing the JSON, internally check every generated block.

Check:

1. Is it relevant to the requested topic?
2. Is it supported by the source or explicitly marked as a correction?
3. Is the mathematics correct?
4. Are formulas preserved correctly?
5. Are examples actually valid?
6. Do conclusions follow from the reasoning?
7. Did personalization change only presentation?
8. Did Lily accidentally invent information?
9. Did Lily silently modify a source claim?
10. If a correction was made, is it explicitly marked?
11. If something cannot be verified, is it marked as uncertain?
12. Are source references genuine?

If a block fails these checks, revise or remove it before returning JSON.


==================================================
16. INSUFFICIENT SOURCE INFORMATION
==================================================

If the source does not contain enough reliable information to generate
a complete note about the requested topic:

DO NOT fill the missing information using guesses.

Instead, generate a concise verification_note explaining that the source
does not contain enough reliable information for that part of the topic.

A shorter correct note is better than a longer hallucinated note.


==================================================
17. JSON OUTPUT
==================================================

Return ONLY valid JSON.

Do NOT use Markdown.

Do NOT wrap the JSON in code fences.

Use exactly this structure:

{NOTE_BLOCK_SCHEMA_EXAMPLE}

Allowed block types:

heading
text
bullet_list
numbered_list
highlight
example
formula
correction
verification_note

The JSON must contain no additional top-level fields beyond those defined
by the schema.

FINAL RULE:

Accuracy is more important than completeness.
"""


@app.post("/generate-note")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
def generate_note(
    request: Request,
    payload: GenerateNoteRequest,
    current_user: int = Depends(get_current_user)
):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, text_style, analysed_style
            FROM style_profiles
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (current_user,),
        )

        style_result = cur.fetchone()

        if style_result is None:
            raise HTTPException(
                status_code=404,
                detail="No style profile found for this user"
            )

        style_profile_id, text_style, analysed_style = style_result

        cur.execute(
            """
            SELECT id, extracted_text
            FROM sources
            WHERE id = %s AND user_id = %s;
            """,
            (payload.source_id, current_user),
        )

        source_result = cur.fetchone()

        if source_result is None:
            raise HTTPException(
                status_code=404,
                detail="Source not found for this user"
            )

        source_id, source_text = source_result

    prompt = build_note_prompt(
        payload.topic,
        text_style,
        analysed_style,
        source_text
    )

    try:
        response = anthropic_client.messages.create(
            model = "claude-sonnet-5",
            max_tokens= 8192,
            thinking={"type" :"adaptive"},
            output_config={"effort" : "medium"},
            messages = [
                {
                    "role" : "user",
                    "content" : prompt
                }
            ],
        )
    except Exception:
        logger.exception("Claude API request failed")
        raise HTTPException(
            status_code = 502,
            detail= "AI service temporarily unavailable"
        )    

    response_text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

    try:
        generated_content = json.loads(response_text)
        validated_note = GeneratedNote.model_validate(
            generated_content
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="Claude returned invalid JSON"
        )

    except ValidationError:
        logger.exception(
            "Claude returned invalid note structure"
        )
        raise HTTPException(
            status_code=502,
            detail="Claude returned an invalid note structure"
        )

    generated_content = validated_note.model_dump()

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes (
                user_id,
                source_id,
                style_profile_id,
                generated_content
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (
                current_user,
                source_id,
                style_profile_id,
                json.dumps(generated_content),
            ),
        )

        note_id = cur.fetchone()[0]

        blocks = generated_content["blocks"]

        for order_index, block in enumerate(blocks):
            block_type = block["type"]
            content = block["content"]

            metadata = {
                key: value
                for key, value in block.items()
                if key not in {
                    "type",
                    "content",
                    "source_reference"
                }
            }

            source_reference = block.get("source_reference")

            cur.execute(
                """
                INSERT INTO note_blocks (
                    note_id,
                    block_type,
                    content,
                    source_reference,
                    metadata,
                    order_index
                )
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    note_id,
                    block_type,
                    json.dumps(content),
                    source_reference,
                    json.dumps(metadata) if metadata else None,
                    order_index,
                ),
            )

    return {
        "message": "Note generated successfully",
        "note_id": note_id,
        "user_id": current_user,
        "source_id": source_id,
        "style_profile_id": style_profile_id,
        "generated_content": generated_content,
    }
