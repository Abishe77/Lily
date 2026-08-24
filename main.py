import psycopg2 #The actual package to make a connection bw my DB and Backend
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from passlib.context import CryptContext
from anthropic import Anthropic
import base64
from fastapi import UploadFile, File
from pypdf import PdfReader
import io


app = FastAPI()

load_dotenv()

anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")) #For claude responses

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") #Hashing the password because we need to protect user privacy

class UserRegister(BaseModel): #Class to actually store a register with valid credentials
    name: str
    year_of_birth: int
    email: str
    password: str

class UserLogin(BaseModel): #class to verify original pass with hashed pass
    email : str
    password : str

class UserCompanion(BaseModel): #For creating a companion end to end connection
    user_id : int
    name : str
    gender : str    

class UserStyleProfile(BaseModel): #For storing the style profile of the user
     user_id: int
     text: str | None = None
     image_base64: str | None = None

class GenerateNoteRequest(BaseModel):
    user_id: int
    source_id: int
    topic: str


def get_db_connection():
    conn = psycopg2.connect(
        dbname = os.environ.get("DB_NAME"),
        user = os.environ.get("DB_USER"),
        password = os.environ.get("DB_PASSWORD"),
        host = os.environ.get("DB_HOST"),
        port = os.environ.get("DB_PORT")
    )
    return conn

@app.get("/")
def read_root():
    return {"Message": "LILY backend is alive"}

@app.get("/users")
def get_users():
    conn = get_db_connection() #Creating a connection between database and fastapi
    cur = conn.cursor()
    cur.execute("SELECT * from users;") #The command executes on web server more precisely gets executed at db and results ar eseen in web
    rows = cur.fetchall() #Takes all rows from the users table
    conn.close() #after fetching closing the connection between my db and backend
    return {"users" : rows} #the actual display command in JSON object form

@app.post("/register")
def register_user(user: UserRegister):
    hashed_password = pwd_context.hash(user.password)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (name, year_of_birth, email, hashed_pass) VALUES (%s, %s, %s, %s);",
        (user.name, user.year_of_birth, user.email, hashed_password)
    )
    conn.commit()
    conn.close()
    return {"message": "User registered successfully"}

@app.post("/login")
def login_user(user: UserLogin):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, hashed_pass FROM users WHERE email = %s;", (user.email,))
    result = cur.fetchone()
    conn.close()
    
    if result is None:
        return {"message": "Invalid mail or password"}  
    
    user_id, stored_hash = result
    
    if pwd_context.verify(user.password, stored_hash):
        return {"message": "Login Successful", "User id": user_id } #If done just give the user id not the email
    else:
        return {"message": "Invalid mail or password"}  
    
'''Now for checking the password with mail ( note it wont return the pass but returns the mail we actually don't know
the real password of the user) so there are 2 cases after verifying a pass either no such mail exists for that password
or either the password is wrong but leaking any one of the information will be helpful for attackers so we should not
reveal that info so what we do is just display "Invalid mail or pass" for both cases so they can't identify whether the 
pass is wrong or no such mail exists for that pass , This is what we did ABOVE
'''

'''
Now creating a companion for our users - they are gonna set a name for their companion and gender either male or female 
so the thing we need to store in this endpoint is user_id , name , gender because we need to know which user's 
companion is this 
'''
@app.post("/companion")
def create_companion (user : UserCompanion):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute ("INSERT into companions(user_id, name , gender) VALUES (%s,%s,%s);",
                (user.user_id ,user.name , user.gender))
    conn.commit()
    conn.close()
    return {"Message" :" Hi I'm your friend"}

''' Storing the style profile of the user here are two cases 
1. If the user manually types her/his style on the text box then that text is stored in sample_notes_txt and that is 
copied to style_description (creates redundancy but we'll take of care it later and marked as a thing to care)

2.If the user uploads a image or pdf or any kind of file for their notes and whether it has handwritten notes or 
anything what we do is instead of storing it in sample_notes_txt(because it will occupy a huge memory) so we will
directly send those files via claude API and we send that with a prompt so that claude can analyse and it will return
a text description about that style and that text is stored in style_description , here sample_notes_txt remains NULL 
and we don't care 

To make case 2 happen , store that in disk and just send the filepath directly to claude that will make it 
efficient 

'''


class UserStyleProfile(BaseModel):
    user_id: int
    text: str | None = None
    image_base64: str | None = None


@app.post("/style-profile")
def create_style_profile(profile: UserStyleProfile):

    if profile.text and profile.text.strip():
        description = profile.text.strip()

    elif profile.image_base64:

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
                                "data": profile.image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": """
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
                        }
                    ]
                }
            ]
        )

        description = response.content[0].text

        print(repr(description))
        print("Length:", len(description))

        with open("claude_debug.txt", "w", encoding="utf-8") as f:
            f.write(description)

    else:
        return {
            "message": "No text or image provided"
        }

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO style_profiles
            (user_id, style_description)
            VALUES (%s, %s)
            RETURNING id;
            """,
            (profile.user_id, description)
        )

        style_profile_id = cur.fetchone()[0]
        conn.commit()

    except Exception as e:
        conn.rollback()
        return {
            "message": "Failed to save style profile",
            "error": str(e)
        }

    finally:
        cur.close()
        conn.close()

    return {
        "message": "Style profile saved",
        "style_profile_id": style_profile_id,
        "user_id": profile.user_id,
        "style_description": description,
        "characters": len(description)
    }

def extract_text_from_scanned_pdf(pdf_bytes):

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
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": """
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
                        }
                    ]
                }
            ]
        )

        page_text = ""

        for block in response.content:
            if block.type == "text":
                page_text += block.text

        extracted_text += f"\n--- PAGE {page_number} ---\n"
        extracted_text += page_text

    document.close()

    return extracted_text.strip()


@app.post("/upload-source")
async def upload_source(user_id: int, file: UploadFile = File(...)):

    pdf_bytes = await file.read()

    reader = PdfReader(io.BytesIO(pdf_bytes))

    extracted_text = ""

    for page_number, page in enumerate(reader.pages, start=1):

        page_text = page.extract_text()

        if page_text:
            extracted_text += f"\n--- PAGE {page_number} ---\n"
            extracted_text += page_text

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
            "characters_extracted": 0
        }

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        cur.execute(
            """
            INSERT INTO sources
            (user_id, filename, extracted_text)
            VALUES (%s, %s, %s)
            RETURNING id;
            """,
            (
                user_id,
                file.filename,
                extracted_text
            )
        )

        source_id = cur.fetchone()[0]

        conn.commit()

    except Exception as e:

        conn.rollback()

        return {
            "message": "Failed to save source",
            "error": str(e)
        }

    finally:

        cur.close()
        conn.close()

    return {
        "message": "Source uploaded successfully",
        "source_id": source_id,
        "user_id": user_id,
        "filename": file.filename,
        "pages": len(reader.pages),
        "characters_extracted": len(extracted_text),
        "extraction_method": extraction_method
    }
@app.post("/generate-note")
def generate_note(request: GenerateNoteRequest):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, style_description
        FROM style_profiles
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        (request.user_id,)
    )

    style_result = cur.fetchone()

    if style_result is None:
        cur.close()
        conn.close()
        return {"message": "No style profile found for this user"}

    style_profile_id, style_description = style_result

    cur.execute(
        """
        SELECT id, extracted_text
        FROM sources
        WHERE id = %s AND user_id = %s;
        """,
        (request.source_id, request.user_id)
    )

    source_result = cur.fetchone()

    if source_result is None:
        cur.close()
        conn.close()
        return {"message": "Source not found for this user"}

    source_id, source_text = source_result

    cur.close()
    conn.close()

    prompt = f"""
You are Lily, a personalized study companion.

The user wants study notes about:

TOPIC:
{request.topic}

Here is the user's personal note-taking style profile:

STYLE PROFILE:
{style_description}

Here is the source material:

SOURCE MATERIAL:
{source_text}

Create study notes about the requested topic using ONLY information
supported by the source material.

IMPORTANT:
- Follow the user's note-taking style as closely as possible.
- Preserve the user's preferred organization and formatting patterns.
- Do not invent information that is not present in the source.
- Do not mention the style profile in the generated notes.
- Focus specifically on the requested topic.
- Make the result useful for studying.
"""

    response = anthropic_client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    generated_text = ""

    for block in response.content:
        if block.type == "text":
            generated_text += block.text

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO notes
        (user_id, source_id, style_profile_id, generated_text)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (
            request.user_id,
            source_id,
            style_profile_id,
            generated_text
        )
    )

    note_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    conn.close()

    return {
        "message": "Note generated successfully",
        "note_id": note_id,
        "user_id": request.user_id,
        "source_id": source_id,
        "style_profile_id": style_profile_id,
        "generated_text": generated_text
    }