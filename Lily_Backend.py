import base64
import json
import logging
import re
import secrets
import hashlib
import hmac
import os
import time

from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import psycopg2
import resend

from anthropic import Anthropic
from dotenv import load_dotenv
from psycopg2.pool import ThreadedConnectionPool

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from source_engine.storage.source_storage import (
    calculate_file_hash,
    build_storage_key,
    save_source_file,
    delete_source_file,
    read_source_file,
)

from source_engine.discovery.persistence import (
    persist_discovery,
)

from source_engine.discovery.source_discovery import (
    discover_source as run_source_discovery,
)

from source_engine.knowledge.source_knowledge_tool import (
    get_source_knowledge,
)

from source_engine.embeddings.discovery_embedding_pipeline import (
    embed_source_units,
)

from source_engine.embeddings.source_embedding_pipeline import (
    embed_source,
)

import requests

from source_engine.knowledge.user_source_knowledge import (
    get_user_source_knowledge,
)


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


LILY_BRAIN_URL = "http://127.0.0.1:8082/v1/chat/completions"
LILY_BRAIN_MODEL = "Qwen/Qwen3-4B-GGUF:Q4_K_M"

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



class TeachingProfileUpdate(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)   


class GenerateNoteRequest(BaseModel):
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

class ChatRequest(BaseModel):
    message: str
    conversation_id : int | None = None         


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
            cur.execute(
                """
                INSERT INTO teaching_profiles (user_id)
                VALUES (%s);
                """,
                (user_id,),
            )
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
                    INSERT INTO teaching_profiles (user_id)
                    VALUES (%s)
                    """,
                    (user_id,),
                )

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
async def create_style_profile(
    request: Request,
    text: str | None = None,
    image: UploadFile | None = File(None),
    current_user: int = Depends(get_current_user),
):
    text_style = text.strip() if text and text.strip() else None
    analysed_style = None


    if text_style is None and image is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of text or image must be provided"
        )

    if image is not None:
        allowed_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        if image.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Unsupported image type. Use JPEG, PNG, or WEBP."
            )

        image_bytes = await image.read()

        if not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded image is empty"
            )

        # Convert image bytes to Base64 for Claude
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

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
                                    "media_type": image.content_type,
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": STYLE_ANALYSIS_PROMPT,
                            },
                        ],
                    }
                ],
            )

            analysed_style = response.content[0].text.strip()

        except Exception as e:
            logger.exception("Style image analysis failed")
            raise HTTPException(
                status_code=502,
                detail=f"Failed to analyze image: {e}"
            )

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO style_profiles
                (user_id, sample_notes_txt, text_style, analysed_style)
            VALUES
                (%s, %s, %s, %s)

            ON CONFLICT (user_id) DO UPDATE SET

                text_style = COALESCE(
                    EXCLUDED.text_style,
                    style_profiles.text_style
                ),

                analysed_style = COALESCE(
                    EXCLUDED.analysed_style,
                    style_profiles.analysed_style
                )

            RETURNING
                id,
                text_style,
                analysed_style;
            """,
            (
                current_user,
                None,
                text_style,
                analysed_style,
            ),
        )

        row = cur.fetchone()


    return {
        "message": "Style profile saved",
        "style_profile_id": row[0],
        "user_id": current_user,
        "text_style": row[1],
        "analysed_style": row[2],
    }


@app.get("/teaching-profile")
def get_teaching_profile(current_user : int = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT preferences, evidence, confidence, user_override
            FROM teaching_profiles
            WHERE user_id = %s
            """,
            (current_user,)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(
            status_code= 404,
            detail = "Teaching profile not found"
        )

    return {
        "preferences" : row[0],
        "evidence" : row[1],
        "confidence" : row[2],
        "user_override" : row[3]
    }  

@app.put("/teaching-profile")
def update_teaching_profile(
    data: TeachingProfileUpdate,
    current_user: int = Depends(get_current_user)
):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT preferences, user_override
            FROM teaching_profiles
            WHERE user_id = %s
            """,
            (current_user,)
        )

        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Teaching profile not found"
            )

        current_preferences = row[0] or {}
        current_overrides = row[1] or {}

        # Merge only the fields explicitly changed by the user
        current_preferences.update(data.preferences)
        current_overrides.update(data.preferences)

        cur.execute(
            """
            UPDATE teaching_profiles
            SET
                preferences = %s,
                user_override = %s,
                updated_at = NOW()
            WHERE user_id = %s
            RETURNING preferences, evidence, confidence, user_override
            """,
            (
                json.dumps(current_preferences),
                json.dumps(current_overrides),
                current_user
            )
        )

        updated_row = cur.fetchone()

    return {
        "preferences": updated_row[0],
        "evidence": updated_row[1],
        "confidence": updated_row[2],
        "user_override": updated_row[3]
    }

def run_lightweight_discovery(
    source_id: int,
    user_id: int,
) -> dict:

    with db_cursor() as cur:

        cur.execute(
            """
            SELECT
                id,
                user_id,
                filename,
                source_type,
                storage_key,
                discovery_status
            FROM sources
            WHERE id = %s
              AND user_id = %s;
            """,
            (
                source_id,
                user_id,
            ),
        )

        source = cur.fetchone()

        if source is None:
            raise ValueError(
                f"Source {source_id} not found for user {user_id}"
            )

        (
            source_id,
            user_id,
            filename,
            source_type,
            storage_key,
            discovery_status,
        ) = source

        cur.execute(
            """
            UPDATE sources
            SET discovery_status = 'discovering'
            WHERE id = %s;
            """,
            (source_id,),
        )

    try:

        file_bytes = read_source_file(
            storage_key
        )

        result = run_source_discovery(
            file_bytes=file_bytes,
            source_type=source_type,
            file_name=filename,
        )

        with db_cursor() as cur:

            summary = persist_discovery(
                cur=cur,
                source_id=source_id,
                result=result,
            )

            embeddings_written = embed_source_units(
                cur=cur,
                source_id=source_id,
            )

            source_embedding_written = embed_source(
                cur=cur,
                source_id=source_id,
            )

            print(
                f"[DISCOVERY] source={source_id} "
                f"unit_embeddings={embeddings_written} "
                f"source_embedding={source_embedding_written}"
            )

            print(
                f"[DISCOVERY] source={source_id} "
                f"lightweight pipeline finished"
            )

            cur.execute(
                """
                UPDATE sources
                SET discovery_status = 'discovered'
                WHERE id = %s;
                """,
                (source_id,),
            )

            print(
                f"[DISCOVERY] source={source_id} "
                f"status=discovered"
            )

        return {
            "source_id": source_id,
            "filename": filename,
            "source_type": source_type,
            "discovery_embeddings_written": embeddings_written,
            "source_embedding_written": source_embedding_written,
            **summary,
        }

    except Exception as exc:

        print("\n" + "=" * 70)
        print(
            f"[DISCOVERY FAILED] source_id={source_id}"
        )
        print(
            f"[DISCOVERY ERROR] "
            f"{type(exc).__name__}: {exc}"
        )
        print("=" * 70)

        logger.exception(
            "Lightweight discovery failed for source %s",
            source_id,
        )

        with db_cursor() as cur:
            cur.execute(
                """
                UPDATE sources
                SET discovery_status = 'failed'
                WHERE id = %s;
                """,
                (source_id,),
            )

        raise


@app.post("/discover-source/{source_id}")
def discover_source(
    source_id: int,
    current_user: int = Depends(get_current_user),
):
    try:
        summary = run_lightweight_discovery(
            source_id=source_id,
            user_id=current_user,
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Source not found",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Source discovery failed: {exc}",
        )

    return {
        "message": "Source discovery completed",
        **summary,
    }


@app.post("/upload-source")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
async def upload_source(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: int = Depends(get_current_user),
):

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required",
        )

    original_filename = file.filename

    extension = Path(
        original_filename.lower()
    ).suffix

    allowed_extensions = {
        ".pdf",
        ".docx",
        ".pptx",
        ".txt",
        ".md",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format",
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File too large. Maximum size is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB"
            ),
        )

    source_type_map = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".pptx": "pptx",
        ".txt": "txt",
        ".md": "md",
        ".jpeg": "image",
        ".jpg": "image",
        ".png": "image",
        ".webp": "image",
    }

    source_type = source_type_map[extension]

    file_hash = calculate_file_hash(
        file_bytes
    )

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                filename,
                storage_key,
                discovery_status
            FROM sources
            WHERE user_id = %s
              AND file_hash = %s
            ORDER BY id
            LIMIT 1;
            """,
            (
                current_user,
                file_hash,
            ),
        )

        existing_source = cur.fetchone()

    if existing_source:

        existing_source_id = existing_source[0]
        existing_filename = existing_source[1]
        existing_storage_key = existing_source[2]
        existing_status = str(
            existing_source[3]
        )

        if existing_status != "failed":
            return {
                "message": "Source already registered",
                "source_id": existing_source_id,
                "user_id": current_user,
                "filename": existing_filename,
                "storage_key": existing_storage_key,
                "source_type": source_type,
                "discovery_status": existing_status,
                "reused": True,
            }

        try:
            save_source_file(
                file_bytes=file_bytes,
                storage_key=existing_storage_key,
            )

        except Exception:
            logger.exception(
                "Failed to store retry source"
            )

            raise HTTPException(
                status_code=500,
                detail="Failed to store source",
            )

        with db_cursor() as cur:
            cur.execute(
                """
                UPDATE sources
                SET
                    filename = %s,
                    source_type = %s,
                    discovery_status = 'pending',
                    source_metadata = %s::jsonb
                WHERE id = %s
                  AND user_id = %s;
                """,
                (
                    original_filename,
                    source_type,
                    json.dumps({
                        "size_bytes": len(file_bytes),
                        "extension": extension,
                    }),
                    existing_source_id,
                    current_user,
                ),
            )

        background_tasks.add_task(
            run_lightweight_discovery,
            existing_source_id,
            current_user,
        )

        return {
            "message": "Failed source retry started",
            "source_id": existing_source_id,
            "user_id": current_user,
            "filename": original_filename,
            "source_type": source_type,
            "storage_key": existing_storage_key,
            "discovery_status": "pending",
            "size_bytes": len(file_bytes),
            "reused": True,
            "retry": True,
        }

    storage_key = build_storage_key(
        user_id=current_user,
        file_hash=file_hash,
        filename=original_filename,
    )

    try:
        save_source_file(
            file_bytes=file_bytes,
            storage_key=storage_key,
        )

    except Exception:
        logger.exception(
            "Failed to store original source"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to store source",
        )

    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO sources (
                    user_id,
                    filename,
                    source_type,
                    file_hash,
                    storage_key,
                    discovery_status,
                    source_metadata
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'pending',
                    %s::jsonb
                )
                RETURNING id;
                """,
                (
                    current_user,
                    original_filename,
                    source_type,
                    file_hash,
                    storage_key,
                    json.dumps({
                        "size_bytes": len(file_bytes),
                        "extension": extension,
                    }),
                ),
            )

            source_id = cur.fetchone()[0]

    except Exception:
        logger.exception(
            "Failed to register source"
        )

        try:
            delete_source_file(
                storage_key
            )

        except Exception:
            logger.exception(
                "Failed to clean orphaned source file"
            )

        raise HTTPException(
            status_code=500,
            detail="Failed to register source",
        )

    background_tasks.add_task(
        run_lightweight_discovery,
        source_id,
        current_user,
    )

    return {
        "message": "Source uploaded successfully",
        "source_id": source_id,
        "user_id": current_user,
        "filename": original_filename,
        "source_type": source_type,
        "storage_key": storage_key,
        "discovery_status": "pending",
        "size_bytes": len(file_bytes),
        "reused": False,
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


1. SOURCE AND KNOWLEDGE BOUNDARY


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



2. CLAIM VERIFICATION


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



3. SOURCE ERROR DETECTION


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



4. UNCERTAINTY


If you cannot confidently determine whether an important source statement
is correct, DO NOT guess.

Do not manufacture a correction.

Instead, create a verification_note block explaining that the statement
could not be reliably verified.

The student must be able to distinguish between:

- verified source information
- verified corrections
- claims requiring further verification



5. MATHEMATICAL AND TECHNICAL SAFETY


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


6. SOURCE REFERENCES


Whenever possible, associate important content with its location in
the source.

If the source contains page numbers or clearly identifiable sections,
preserve those references.

DO NOT invent page numbers or source references.

If an exact source location cannot be determined, omit the reference.



7. PERSONALIZED NOTE STYLE


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



8. TOPIC RELEVANCE


Focus on:

{topic}

Prefer information directly relevant to the requested topic.

Do not fill the notes with unrelated material merely because it appears
somewhere in the source.

Include prerequisite information only when it is necessary to understand
the requested topic.



9. TRANSPARENT CORRECTIONS


Never silently replace an incorrect source statement with a corrected one.

When Lily corrects the source, explicitly communicate that a correction
was made.

The student should be able to understand:

SOURCE CLAIM
→ VERIFICATION
→ PROBLEM
→ CORRECTED CLAIM
→ EXPLANATION



10. OUTPUT BLOCK TYPES


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



11. BLOCK RULES


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



12. CORRECTION BLOCK


Every correction block must communicate:

- what the source claimed
- why the claim is incorrect
- the corrected explanation

Use the correction structure defined in the JSON schema below.

Do not create a correction merely because the source explanation could
be clearer.

A correction means the original claim is actually wrong.



13. VERIFICATION NOTE


Use the verification_note structure defined in the JSON schema below.

Only use it when an important source claim cannot be confidently verified.

Do not use verification_note for ordinary stylistic issues.



14. NO HALLUCINATED EXAMPLES


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



15. FINAL INTERNAL AUDIT


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



16. INSUFFICIENT SOURCE INFORMATION


If the source does not contain enough reliable information to generate
a complete note about the requested topic:

DO NOT fill the missing information using guesses.

Instead, generate a concise verification_note explaining that the source
does not contain enough reliable information for that part of the topic.

A shorter correct note is better than a longer hallucinated note.



17. JSON OUTPUT


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

def build_note_source_context(
    chunks: list[dict],
) -> str:
    """
    Convert retrieved Source Engine chunks into grounded context
    for note generation.
    """

    parts = []

    for index, chunk in enumerate(
        chunks,
        start=1,
    ):
        retrieval_text = chunk.get(
            "retrieval_text",
            ""
        )

        if not isinstance(
            retrieval_text,
            str,
        ):
            continue

        retrieval_text = retrieval_text.strip()

        if not retrieval_text:
            continue

        unit_index = chunk.get(
            "unit_index"
        )

        chunk_index = chunk.get(
            "chunk_index"
        )

        reference_parts = []

        if unit_index is not None:
            reference_parts.append(
                f"unit {unit_index}"
            )

        if chunk_index is not None:
            reference_parts.append(
                f"chunk {chunk_index}"
            )

        if reference_parts:
            reference = " | ".join(
                reference_parts
            )
        else:
            reference = f"retrieved result {index}"

        parts.append(
            f"[Source evidence: {reference}]\n"
            f"{retrieval_text}"
        )

    return "\n\n".join(parts).strip()


@app.post("/generate-note")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
def generate_note(
    request: Request,
    payload: GenerateNoteRequest,
    current_user: int = Depends(get_current_user),
):
    topic = payload.topic.strip()

    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty")

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, text_style, analysed_style
            FROM style_profiles
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1;
        """, (current_user,))

        style_result = cur.fetchone()

        if style_result is None:
            raise HTTPException(
                status_code=404,
                detail="No style profile found for this user"
            )

        style_profile_id, text_style, analysed_style = style_result

        try:
            knowledge = get_user_source_knowledge(
                cur=cur,
                user_id=current_user,
                query=topic,
                source_top_k=3,
                chunk_top_k=8,
                allow_targeted_ingestion=True,
            )
        except Exception:
            logger.exception("Source knowledge retrieval failed")
            raise HTTPException(
                status_code=502,
                detail="Failed to retrieve source knowledge"
            )

        source_chunks = knowledge.get("chunks", [])

        if not source_chunks:
            raise HTTPException(
                status_code=422,
                detail="No relevant source knowledge was found for the requested topic"
            )

        source_text = build_note_source_context(source_chunks)

        if not source_text:
            raise HTTPException(
                status_code=422,
                detail="No usable source evidence was found for the requested topic"
            )

        primary_source_id = source_chunks[0].get("source_id")

        if primary_source_id is None:
            raise HTTPException(
                status_code=502,
                detail="Retrieved source evidence is missing source information"
            )

        cur.execute("""
            SELECT filename
            FROM sources
            WHERE id = %s
              AND user_id = %s;
        """, (primary_source_id, current_user))

        source_result = cur.fetchone()

        if source_result is None:
            raise HTTPException(
                status_code=502,
                detail="Primary source could not be resolved"
            )

        source_filename = source_result[0]

    prompt = build_note_prompt(
        topic,
        text_style,
        analysed_style,
        source_text,
    )

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )
    except Exception:
        logger.exception("Claude API request failed")
        raise HTTPException(
            status_code=502,
            detail="AI service temporarily unavailable"
        )

    response_text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

    try:
        generated_content = json.loads(response_text)
        validated_note = GeneratedNote.model_validate(generated_content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="Claude returned invalid JSON"
        )
    except ValidationError:
        logger.exception("Claude returned invalid note structure")
        raise HTTPException(
            status_code=502,
            detail="Claude returned an invalid note structure"
        )

    generated_content = validated_note.model_dump()

    evidence_map = {}

    for index, chunk in enumerate(source_chunks, start=1):
        source_chunk_id = chunk.get("source_chunk_id", chunk.get("id"))

        if source_chunk_id is not None:
            evidence_map[f"EVIDENCE_{index}"] = source_chunk_id

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO notes (
                user_id,
                source_id,
                style_profile_id,
                generated_content
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (
            current_user,
            primary_source_id,
            style_profile_id,
            json.dumps(generated_content),
        ))

        note_id = cur.fetchone()[0]

        for order_index, block in enumerate(generated_content["blocks"]):
            block_type = block["type"]
            content = block["content"]

            metadata = {
                key: value
                for key, value in block.items()
                if key not in {
                    "type",
                    "content",
                    "source_reference",
                }
            }

            source_reference = block.get("source_reference")

            cur.execute("""
                INSERT INTO note_blocks (
                    note_id,
                    block_type,
                    content,
                    source_reference,
                    metadata,
                    order_index
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                note_id,
                block_type,
                json.dumps(content),
                source_reference,
                json.dumps(metadata) if metadata else None,
                order_index,
            ))

            note_block_id = cur.fetchone()[0]

            if source_reference:
                evidence_ids = [
                    part.strip()
                    for part in source_reference.split(",")
                ]

                for evidence_id in evidence_ids:
                    source_chunk_id = evidence_map.get(evidence_id)

                    if source_chunk_id is None:
                        continue

                    cur.execute("""
                        INSERT INTO note_block_sources (
                            note_block_id,
                            source_chunk_id
                        )
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING;
                    """, (
                        note_block_id,
                        source_chunk_id,
                    ))

    return {
        "message": "Note generated successfully",
        "note_id": note_id,
        "user_id": current_user,
        "source_id": primary_source_id,
        "source_filename": source_filename,
        "style_profile_id": style_profile_id,
        "source_cache_status": [
            source.get("cache_status")
            for source in knowledge.get("sources", [])
        ],
        "generated_content": generated_content,
    }

LILY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_source_knowledge",
            "description": (
                "Search the student's uploaded learning sources for "
                "information relevant to their request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The semantic search query describing the "
                            "knowledge needed from the student's sources."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    }
]


def call_brain(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> dict:
    payload = {
        "model": LILY_BRAIN_MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    if tools is not None:
        payload["tools"] = tools

    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    response = requests.post(
        LILY_BRAIN_URL,
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        print("Brain HTTP error")
        print("status: ", response.status_code)
        print("response: ", response.text)

    response.raise_for_status()

    return response.json()


def compact_brain_knowledge(
    knowledge: dict,
    *,
    max_chunks: int = 5,
    max_chars_per_chunk: int = 2500,
    max_total_chars: int = 9000,
) -> dict:
    compact_chunks = []
    total_chars = 0

    chunks = knowledge.get("chunks", [])

    for chunk in chunks[:max_chunks]:
        retrieval_text = chunk.get(
            "retrieval_text",
            "",
        )

        if not isinstance(retrieval_text, str):
            continue

        retrieval_text = retrieval_text.strip()

        if not retrieval_text:
            continue

        remaining_chars = (
            max_total_chars - total_chars
        )

        if remaining_chars <= 0:
            break

        allowed_chars = min(
            max_chars_per_chunk,
            remaining_chars,
        )

        retrieval_text = retrieval_text[
            :allowed_chars
        ]

        compact_chunk = {
            "source_id": chunk.get("source_id"),
            "source_filename": chunk.get(
                "source_filename"
            ),
            "unit_index": chunk.get("unit_index"),
            "chunk_index": chunk.get("chunk_index"),
            "similarity": chunk.get("similarity"),
            "retrieval_text": retrieval_text,
        }

        compact_chunks.append(compact_chunk)

        total_chars += len(retrieval_text)

    return {
        "query": knowledge.get("query"),
        "knowledge_available": bool(compact_chunks),
        "chunks": compact_chunks,
    }


def build_lily_system_prompt(
    *,
    user_name: str,
    companion_name: str | None,
    gender: str | None,
    personality_mode: str | None,
    teaching_preferences: dict | None,
    teaching_override: dict | None,
) -> str:

    companion_name = companion_name or "your learning companion"
    personality_mode = (
        personality_mode or "friendly_encouraging"
    )

    teaching_preferences = (
        teaching_preferences or {}
    )

    teaching_override = (
        teaching_override or {}
    )

    personality_instructions = {
        "funny_sarcastic": (
    "Be casual, witty, playful, and lightly sarcastic when it fits. "
    "Talk naturally and keep the humor spontaneous. "
    "Do not force jokes or sarcasm into every response."
),
        "friendly_encouraging": (
            "Be warm, friendly, encouraging, and conversational. "
            "Celebrate progress naturally without sounding artificial."
        ),
        "strict_disciplined": (
            "Be focused, disciplined, and direct. Keep the student "
            "accountable while remaining respectful and supportive."
        ),
        "professional": (
            "Be clear, composed, precise, and professional while "
            "remaining approachable."
        ),
        "calm_gentle": (
            "Be calm, patient, gentle, and reassuring. Explain things "
            "without pressure or unnecessary intensity."
        ),
    }

    personality_instruction = (
        personality_instructions.get(
            personality_mode,
            personality_instructions[
                "friendly_encouraging"
            ],
        )
    )

    return f"""
You are {companion_name}.

You are the student's companion inside Lily.

The student can talk to you about anything.
The student's name is {user_name}.

Your current personality mode is:
{personality_mode}

Personality behavior:
{personality_instruction}

CONVERSATION PRIORITY:

You are a companion first.

The student can talk to you about anything: random thoughts, jokes,
food, hobbies, daily life, opinions, stories, nonsense, or studying.

Follow the current message, not the student's overall academic profile.

If the current message is casual, remain casual.

If the current message is random, be random.

If the current message is a joke, joke back.

If the current message is about everyday life, talk about everyday life.

If the current message is academic, then switch naturally into teaching.

NEVER redirect a casual conversation toward studying, machine learning,
school, exams, or learning unless the student brings those topics up.

NEVER mention that you are "here to help them learn" during casual
conversation.

Conversation history gives you continuity and familiarity. It does not
determine the subject of the current conversation.

Previous academic conversations must not influence a new casual
conversation unless the student explicitly connects the topics.

NATURAL CONVERSATION:

Respond to what the student actually said.

Do not turn every request into a list of options.

Do not manufacture a question at the end of every response.

Do not repeatedly say that you are available to chat, help, listen,
or do something else.

Do not explain your personality. Express it through your responses.

Do not announce that you are an AI unless the student directly asks
about that.

When the student asks for something random, funny, or casual, actually
give them something appropriate instead of explaining the interaction.

If the student's joke or comment is weak, you may tease them lightly.
If your own joke fails, you can acknowledge the failure naturally
instead of becoming overly apologetic or switching into assistant mode.

Keep responses proportional to the student's message.

GENERAL BEHAVIOR:

Talk like a normal person having an ongoing conversation.

Keep casual messages casual. Do not turn short conversational messages
into long explanations.

Do not repeatedly introduce yourself, describe your role, describe the
Lily application, or explain that you are an AI.

Do not repeatedly mention the student's name.

Do not add a question merely to keep the conversation going.

Only ask a question when a natural conversational response genuinely
calls for one.

Conversation history provides context, but do not force the current
conversation back toward previously discussed topics.

Treat each new user message according to its current intent.

If the student changes topic, follow the new topic naturally.

Do not bring up previous subjects unless:
- the student refers to them,
- they are directly relevant,
- or remembering them is necessary to answer the current message.

Do not assume every message is related to studying.
The student may casually chat, joke, ask random questions, or change
topics completely.

Do not use generic assistant phrases such as:
"How may I assist you?"
"Feel free to ask."
"I'm here to help."
"What's on your mind?"
"Let's dive in."
"Let's get started."

Do not narrate your own personality or behavior. Just behave naturally.

When the student says something casual, respond conversationally rather
than converting it into a learning session.

When the student asks to change your conversational style, adapt
quietly and demonstrate the change instead of explaining how you will
change.

Be truthful, but do not volunteer technical disclaimers about being an AI
unless the distinction is directly relevant to the user's question.

For ordinary social or casual questions, answer naturally without explaining
your artificial nature, limitations, or how you process information.

You may have conversational preferences and fictional everyday favorites
for the purpose of casual conversation. Do not present these as real
physical experiences or memories.

TEACHING PROFILE:

Learned teaching preferences:
{json.dumps(teaching_preferences, ensure_ascii=False)}

Explicit student teaching preferences:
{json.dumps(teaching_override, ensure_ascii=False)}

Use these preferences as flexible guidance for how you teach the
student, not as a rigid script.

When relevant, adapt:
- the order of intuition, examples, formal definitions, and mathematics
- explanation depth and amount of detail
- pacing and step size
- the kinds of examples or analogies used
- mathematical detail
- how often you check the student's understanding

Prefer explicit student teaching preferences over learned preferences
when they conflict.

The student's current request always has highest priority. For example,
if the teaching profile prefers detailed step-by-step explanations but
the student asks for only a formula, answer with only what they asked
for.

Do not mechanically repeat the same teaching structure for every
question. Adapt naturally to the concept and conversation.

Do not mention the teaching profile, preference database, confidence
scores, or internal personalization system unless the student
specifically asks about them.

SOURCE-GROUNDING RULES:

You may receive evidence retrieved from the student's uploaded
learning materials.

When source knowledge is returned, treat it as evidence from the
student's material, not as something you are free to reconstruct.

For requests asking about the exact contents of uploaded material:

1. Preserve the source's terminology, notation, values, examples,
   equations, and structure as faithfully as the returned evidence
   allows.

2. NEVER silently correct, reconcile, normalize, simplify, or replace
   conflicting source readings.

3. If the returned evidence contains uncertainty, OCR/VLM mistakes,
   conflicting readings, missing symbols, or ambiguous notation,
   explicitly say that the evidence is unclear.

4. NEVER invent missing symbols, numbers, exponents, strings,
   decompositions, conditions, or intermediate steps.

5. Do not replace the student's example with a standard textbook
   example merely because the source appears incorrect.

6. Separate these two things clearly:
   - What the student's material appears to say.
   - Whether that material is mathematically or factually correct.

7. If the source appears mathematically incorrect, faithfully report
   what the source says first, then explain the error separately using
   clearly identified reasoning.

8. Do not combine two conflicting readings into a new statement.

9. Never infer what the student "must have meant" from mathematical
   context. If the exact source cannot be determined, say that it
   cannot be determined from the available evidence.

When source knowledge is NOT returned, do not pretend that you accessed
the student's material.

Your job is to be faithful to the student's material first, and
mathematically helpful second.
""".strip()

def get_lily_personalization(
    cur,
    user_id: int,
) -> dict:

    cur.execute(
        """
        SELECT
            u.name,
            c.name,
            c.gender,
            c.personality_mode,
            tp.preferences,
            tp.user_override
        FROM users u
        LEFT JOIN companions c
            ON c.user_id = u.id
        LEFT JOIN teaching_profiles tp
            ON tp.user_id = u.id
        WHERE u.id = %s;
        """,
        (user_id,),
    )

    row = cur.fetchone()

    if not row:
        raise ValueError(
            f"User {user_id} not found."
        )

    return {
        "user_name": row[0],
        "companion_name": row[1],
        "gender": row[2],
        "personality_mode": (
            str(row[3]) if row[3] else None
        ),
        "teaching_preferences": row[4] or {},
        "teaching_override": row[5] or {},
    }

def create_conversation(
        cur,
        user_id: int,
) -> int:
    cur.execute(
        """
        INSERT INTO conversations (user_id)
        VALUES (%s)
        RETURNING id;
        """,
        (user_id,),
    )
    return cur.fetchone()[0]

def get_recent_conversation_messages(
        cur,
        conversation_id: int,
        user_id : int,
        limit: int = 20,
) -> list[dict]:

    cur.execute(
        """
        SELECT
          cm.role,
          cm.content
        FROM conversation_messages cm
        JOIN conversations c
          ON c.id = cm.conversation_id
        WHERE cm.conversation_id = %s
          AND c.user_id = %s
        ORDER BY cm.created_at DESC
        LIMIT %s;
        """,(
            conversation_id,
            user_id,
            limit,
        ),
    )
    rows = cur.fetchall()
    rows.reverse()
    return[
        {
            "role" : row[0],
            "content" : row[1],
        }
        for row in rows
    ]

def save_conversation_message(
    cur,
    conversation_id: int,
    role: str,
    content: str,
) -> None:
    cur.execute(
        """
        INSERT INTO conversation_messages (
            conversation_id,
            role,
            content
        )
        VALUES (%s, %s, %s);
        """,
        (
            conversation_id,
            role,
            content,
        ),
    )


def update_conversation_timestamp(
    cur,
    conversation_id: int,
) -> None:
    cur.execute(
        """
        UPDATE conversations
        SET updated_at = NOW()
        WHERE id = %s;
        """,
        (conversation_id,),
    )



SOURCE_ROUTER_PROMPT = """
You are a routing classifier for a personalized learning companion.

Your only task is to decide whether the student's request depends on
information from the student's own learning materials.

Return exactly one word:

SOURCE
or
DIRECT

Choose SOURCE if answering the request requires knowing, retrieving,
remembering, locating, explaining, summarizing, or using information
from material belonging to the student.

The student may refer to their material naturally and indirectly.
They do not need to explicitly say "uploaded", "PDF", "notes", or
"file".

Examples:

Student: hi
Decision: DIRECT

Student: explain pumping lemma
Decision: DIRECT

Student: what is a transformer?
Decision: DIRECT

Student: shall we play a game?
Decision: DIRECT

Student: teach me pumping lemma sum from the material
Decision: SOURCE

Student: explain the pumping lemma example from my material
Decision: SOURCE

Student: what did my notes say about Bayes theorem?
Decision: SOURCE

Student: explain that example I uploaded earlier
Decision: SOURCE

Student: summarize my presentation
Decision: SOURCE

Student: what equation was there in the material?
Decision: SOURCE

Student: teach this according to what I gave you
Decision: SOURCE

Important distinction:

If the student is asking about a topic itself, choose DIRECT.

If the student wants that topic, example, explanation, equation,
question, diagram, or information FROM THEIR OWN MATERIAL, choose
SOURCE.

The words "the material" refer to the student's available learning
material when the student asks to teach, explain, find, recall, or use
something from it.

Do not answer the student's request.
Do not explain the classification.
Do not call any tools.
Return only SOURCE or DIRECT.
""".strip()

def decide_source_route(
    user_message: str,
) -> str:
    router_response = call_brain(
        [
            {
                "role": "system",
                "content": SOURCE_ROUTER_PROMPT,
            },
            {
                "role": "user",
                "content": user_message,
            },
        ],
        temperature=0,
        max_tokens=8,
        timeout=120,
    )

    router_message = (
        router_response["choices"][0]["message"]
    )

    print(
    "[SOURCE ROUTER RAW]",
    json.dumps(
        router_message,
        indent=2,
        ensure_ascii=False,
    ),
)

    decision = str(
        router_message.get(
            "content",
            "",
        )
    ).strip().upper()

    if "SOURCE" in decision:
        return "SOURCE"

    if "DIRECT" in decision:
        return "DIRECT"

    print(
        "[SOURCE ROUTER] invalid response:",
        repr(decision),
    )

    return "DIRECT"


@app.post("/chat")
def chat_with_lily(
    payload: ChatRequest,
    current_user: int = Depends(get_current_user)
):
    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty",
        )

    with db_cursor() as cur:
        if payload.conversation_id is None:
            conversation_id = create_conversation(
                cur,
                current_user,
            )
        else:
            conversation_id = payload.conversation_id

        conversation_history = get_recent_conversation_messages(
            cur,
            conversation_id,
            current_user,
            limit=20,
        )
    

    print("\n===== ENTERED LILY CHAT =====")
    print("payload:", payload)
    print("current_user:", current_user)

    try:
        with db_cursor() as cur:
            personalization = get_lily_personalization(
                cur,
                current_user,
            )

        lily_system_prompt = build_lily_system_prompt(
            **personalization
        )

        print(
            "[CHAT] companion=",
            personalization.get(
                "companion_name"
            ),
        )

        print(
            "[CHAT] personality=",
            personalization.get(
                "personality_mode"
            ),
        )

    except Exception:
        logger.exception(
            "Failed to load Lily personalization"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to load Lily personalization"
            ),
        )

    try:
        router_start = time.perf_counter()

        route = decide_source_route(
            user_message
        )

        print(
            f"[CHAT] router_seconds="
            f"{time.perf_counter() - router_start:.2f}"
        )

        print(
            f"[CHAT] route={route}"
        )

    except Exception:
        logger.exception(
            "Lily source router failed"
        )

        raise HTTPException(
            status_code=502,
            detail="Lily routing is unavailable",
        )

    messages = [
        {
            "role": "system",
            "content": lily_system_prompt,
        },
        *conversation_history,
        {
            "role": "user",
            "content": user_message,
        },
    ]
    with db_cursor() as cur:
        save_conversation_message(
            cur,
            conversation_id,
            "user",
            user_message,
        )
        update_conversation_timestamp(
            cur,
            conversation_id,
        )

    if route == "DIRECT":
        try:
            direct_start = time.perf_counter()

            print("\n===== DIRECT MESSAGES =====")
            for message in messages:
                print(f"\n[{message['role'].upper()}]")
                print(message["content"])
                print("===== END DIRECT MESSAGES =====\n")

            direct_response = call_brain(
                messages,
                temperature=0.3,
                max_tokens=384,
                timeout=120,
            )

            print(
                f"[CHAT] direct_qwen_seconds="
                f"{time.perf_counter() - direct_start:.2f}"
            )

        except Exception:
            logger.exception(
                "Lily direct brain request failed"
            )

            raise HTTPException(
                status_code=502,
                detail="Lily brain is unavailable",
            )

        direct_message = (
            direct_response["choices"][0]["message"]
        )

        print("Direct qwen response")
        print(
            json.dumps(
                direct_message,
                indent=2,
                ensure_ascii=False,
            )
        )

        direct_content = direct_message.get(
            "content",
            "",
        )

        with db_cursor() as cur:
            save_conversation_message(
                cur,
                conversation_id,
                "assistant",
                direct_content,
            )

            update_conversation_timestamp(
                cur,
                conversation_id,
            )

        return {
    "message": direct_content,
    "used_tools": [],
    "conversation_id": conversation_id,
}

    try:
        first_qwen_start = time.perf_counter()

        brain_response = call_brain(
            messages,
            tools=LILY_TOOLS,
            tool_choice="required",
            temperature=0,
            max_tokens=256,
            timeout=120,
        )

        print(
            f"[CHAT] source_query_qwen_seconds="
            f"{time.perf_counter() - first_qwen_start:.2f}"
        )

    except Exception:
        logger.exception(
            "Lily source-query brain request failed"
        )

        raise HTTPException(
            status_code=502,
            detail="Lily brain is unavailable",
        )

    assistant_message = (
        brain_response["choices"][0]["message"]
    )

    print("Source query qwen response")
    print(
        json.dumps(
            assistant_message,
            indent=2,
            ensure_ascii=False,
        )
    )

    tool_calls = (
        assistant_message.get("tool_calls") or []
    )

    print("tool_calls:", tool_calls)

    if not tool_calls:
        raise HTTPException(
            status_code=502,
            detail=(
                "Lily selected source routing but "
                "did not produce a source tool call"
            ),
        )

    tool_call = tool_calls[0]

    function_data = tool_call.get(
        "function",
        {},
    )

    tool_name = function_data.get("name")

    if tool_name != "search_source_knowledge":
        raise HTTPException(
            status_code=502,
            detail=(
                "Lily requested unsupported tool: "
                f"{tool_name}"
            ),
        )

    try:
        arguments = json.loads(
            function_data.get(
                "arguments",
                "{}",
            )
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail=(
                "Lily produced invalid tool arguments"
            ),
        )

    query = str(
        arguments.get(
            "query",
            "",
        )
    ).strip()

    if not query:
        raise HTTPException(
            status_code=502,
            detail=(
                "Lily requested source search "
                "without a query"
            ),
        )

    print("tool:", tool_name)
    print("query:", query)

    try:
        source_tool_start = time.perf_counter()

        with db_cursor() as cur:
            knowledge = get_user_source_knowledge(
                cur=cur,
                user_id=current_user,
                query=query,
                source_top_k=3,
                chunk_top_k=5,
                allow_targeted_ingestion=True,
            )

        print(
            f"[CHAT] source_tool_seconds="
            f"{time.perf_counter() - source_tool_start:.2f}"
        )

    except Exception:
        logger.exception(
            "Lily source knowledge tool failed"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to search source knowledge"
            ),
        )

    print("Source tool call")
    print(
        "Knowledge_available:",
        knowledge.get(
            "knowledge_available",
            False,
        ),
    )

    brain_knowledge = compact_brain_knowledge(
        knowledge
    )

    print(
        "[CHAT] retrieved_chunks=",
        len(
            knowledge.get(
                "chunks",
                [],
            )
        ),
    )

    print(
        "[CHAT] brain_chunks=",
        len(
            brain_knowledge.get(
                "chunks",
                [],
            )
        ),
    )

    print(
        "[CHAT] brain_evidence_chars=",
        sum(
            len(
                chunk.get(
                    "retrieval_text",
                    "",
                )
            )
            for chunk in brain_knowledge.get(
                "chunks",
                [],
            )
        ),
    )

    messages.append(
        assistant_message
    )

    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps(
                brain_knowledge,
                ensure_ascii=False,
                default=str,
            ),
        }
    )

    try:
        final_qwen_start = time.perf_counter()

        final_data = call_brain(
            messages,
            tools=LILY_TOOLS,
            tool_choice="none",
            temperature=0,
            max_tokens=384,
            timeout=120,
        )

        print(
            f"[CHAT] final_qwen_seconds="
            f"{time.perf_counter() - final_qwen_start:.2f}"
        )

    except Exception:
        print("\n===== FINAL QWEN ERROR =====")

        logger.exception(
            "Lily brain final response failed"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Lily failed to generate "
                "a final response"
            ),
        )

    final_message = (
        final_data["choices"][0]["message"]
    )

    print("Final qwen response")
    print(
        json.dumps(
            final_message,
            indent=2,
            ensure_ascii=False,
        )
    )

    final_content = final_message.get(
        "content",
        "",
    )

    with db_cursor() as cur:
        save_conversation_message(
            cur,
            conversation_id,
            "assistant",
            final_content,
        )

        update_conversation_timestamp(
            cur,
            conversation_id,
        )

    return {
    "message": final_content,
    "used_tools": [
        {
            "name": "search_source_knowledge",
            "query": query,
        }
    ],
    "knowledge_available": knowledge.get(
        "knowledge_available",
        False,
    ),
    "conversation_id": conversation_id,
}  




    

