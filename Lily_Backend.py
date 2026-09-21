import base64
import io
import json
import logging
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg2
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
from pydantic import BaseModel
from pypdf import PdfReader
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


@contextmanager
def db_cursor():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def create_access_token(user_id: int) -> str:
    expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")


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
            INSERT INTO otp_codes (user_id, email, purpose, otp, attempts, created_at, expires_at)
            VALUES (%s, %s, %s, %s, 0, NOW(), NOW() + (%s * INTERVAL '1 minute'))
            ON CONFLICT (email, purpose) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                otp = EXCLUDED.otp,
                attempts = 0,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at;
            """,
            (user_id, email, purpose, otp, OTP_EXPIRE_MINUTES),
        )

    return otp


def consume_otp(email: str, data_otp: str, purpose: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, otp, attempts, NOW() > expires_at
            FROM otp_codes
            WHERE email = %s AND purpose = %s;
            """,
            (email, purpose),
        )
        row = cur.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="OTP not found")

        otp_id, user_id, stored_otp, attempts, expired = row

        if expired:
            cur.execute("DELETE FROM otp_codes WHERE id = %s;", (otp_id,))
            raise HTTPException(status_code=400, detail="OTP expired")

        if attempts >= 5:
            cur.execute("DELETE FROM otp_codes WHERE id = %s;", (otp_id,))
            raise HTTPException(status_code=429, detail="Too many invalid attempts")

        if data_otp != stored_otp:
            cur.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s;", (otp_id,))
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


class UserCompanion(BaseModel):
    name: str
    gender: str


class UserStyleProfile(BaseModel):
    text: str | None = None
    image_base64: str | None = None


class GenerateNoteRequest(BaseModel):
    source_id: int
    topic: str


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
    return {
        "message": "Email verified successfully",
        "access_token": access_token,
        "token_type": "bearer",
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
    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
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
    return {
        "message": "Google login successful",
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/companion")
def create_companion(user: UserCompanion, current_user: int = Depends(get_current_user)):
    with db_cursor() as cur:
      cur.execute(
    """
    INSERT INTO companions (user_id, name, gender)
    VALUES (%s, %s, %s)
    ON CONFLICT (user_id)
    DO UPDATE SET
        name = EXCLUDED.name,
        gender = EXCLUDED.gender;
    """,
    (current_user, user.name, user.gender)
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


@app.post("/upload-source")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
async def upload_source(request: Request, file: UploadFile = File(...), current_user: int = Depends(get_current_user)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()

    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a valid PDF")

    extracted_text = ""
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text()
        if page_text:
            extracted_text += f"\n--- PAGE {page_number} ---\n{page_text}"

    extracted_text = extracted_text.strip()
    extraction_method = "pypdf"

    if not extracted_text:
        extraction_method = "claude_vision"
        extracted_text = extract_text_from_scanned_pdf(pdf_bytes)

    if not extracted_text:


        return {
            "message": "Could not extract any text from this PDF",
            "filename": file.filename,
            "pages": len(reader.pages),
            "characters_extracted": 0,
        }

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (user_id, filename, extracted_text)
            VALUES (%s, %s, %s)
            RETURNING id;
            """,
            (current_user, file.filename, extracted_text),
        )
        source_id = cur.fetchone()[0]

    return {
        "message": "Source uploaded successfully",
        "source_id": source_id,
        "user_id": current_user,
        "filename": file.filename,
        "pages": len(reader.pages),
        "characters_extracted": len(extracted_text),
        "extraction_method": extraction_method,
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
    {"type": "formula", "content": "Formula"}
  ]
}
"""


def build_note_prompt(topic: str, text_style, analysed_style, source_text: str) -> str:
    return f"""
You are Lily, a personalized study companion.

The user wants study notes about:

TOPIC:
{topic}

USER-DECLARED STYLE:
{text_style}

ANALYSED STYLE FROM SAMPLE NOTES:
{analysed_style}

SOURCE MATERIAL:
{source_text}

Create study notes about the requested topic using ONLY information
supported by the source material.

IMPORTANT:
- Follow the user's declared style when it is provided.
- Use the analysed style to reproduce the user's actual note-taking patterns.
- Do not invent information that is not present in the source.
- Do not mention the style profile in the generated notes.
- Focus specifically on the requested topic.
- Make the result useful for studying.

Return ONLY valid JSON.
Do not use Markdown.
Do not wrap the JSON in ```json or any code fences.

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
"""


@app.post("/generate-note")
@limiter.limit(CLAUDE_ENDPOINT_RATE_LIMIT)
def generate_note(request: Request, payload: GenerateNoteRequest, current_user: int = Depends(get_current_user)):
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
            raise HTTPException(status_code=404, detail="No style profile found for this user")

        style_profile_id, text_style, analysed_style = style_result

        cur.execute(
            "SELECT id, extracted_text FROM sources WHERE id = %s AND user_id = %s;",
            (payload.source_id, current_user),
        )
        source_result = cur.fetchone()

        if source_result is None:
            raise HTTPException(status_code=404, detail="Source not found for this user")

        source_id, source_text = source_result

    prompt = build_note_prompt(payload.topic, text_style, analysed_style, source_text)

    response = anthropic_client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = "".join(block.text for block in response.content if block.type == "text")

    try:
        generated_content = json.loads(response_text)
    except json.JSONDecodeError:


        return {"message": "Claude returned invalid JSON", "raw_response": response_text}

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO notes (user_id, source_id, style_profile_id, generated_content)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (current_user, source_id, style_profile_id, json.dumps(generated_content)),
        )
        note_id = cur.fetchone()[0]

    return {
        "message": "Note generated successfully",
        "note_id": note_id,
        "user_id": current_user,
        "source_id": source_id,
        "style_profile_id": style_profile_id,
        "generated_content": generated_content,
    }