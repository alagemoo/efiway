from fastapi import FastAPI, File, UploadFile, Form, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import openai
from databases import Database
from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import logging
from typing import Optional
from io import BytesIO
from PyPDF2 import PdfReader
from docx import Document
import hashlib
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import requests
from fastapi.responses import RedirectResponse

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Initialize FastAPI app
app = FastAPI()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")
database = Database(DATABASE_URL)

# Mount static files for serving CSS, JS, etc.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure template rendering for HTML files
templates = Jinja2Templates(directory="templates")

# Add CORS middleware for frontend-backend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development. Restrict in production.
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Authentication setup
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key_here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Cache for file extraction
file_cache = {}

# Google OAuth settings
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# Connect to database on startup and disconnect on shutdown
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Helper functions for user authentication
async def get_user_by_username(username: str):
    query = "SELECT * FROM users WHERE username = :username"
    return await database.fetch_one(query, {"username": username})

async def get_user_by_email(email: str):
    query = "SELECT * FROM users WHERE email = :email"
    return await database.fetch_one(query, {"email": email})

async def create_user(username: str, email: str, hashed_password: str):
    query = """
    INSERT INTO users (username, email, hashed_password)
    VALUES (:username, :email, :hashed_password)
    RETURNING id
    """
    values = {"username": username, "email": email, "hashed_password": hashed_password}
    return await database.execute(query, values)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def authenticate_user(username: str, password: str):
    user = await get_user_by_username(username)
    if user and pwd_context.verify(password, user["hashed_password"]):
        return user
    return False

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = await get_user_by_username(username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Routes
@app.get("/", response_class=HTMLResponse)
async def serve_homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/register/")
async def register_user(username: str, email: str, password: str):
    existing_user = await get_user_by_username(username) or await get_user_by_email(email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")
    
    hashed_password = pwd_context.hash(password)
    user_id = await create_user(username, email, hashed_password)
    return {"msg": "User registered successfully", "user_id": user_id}

@app.post("/token/")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me/")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {"username": current_user["username"], "email": current_user["email"]}

@app.get("/google-login/")
async def google_login():
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri=http://127.0.0.1:8000/google-auth/callback"
        f"&response_type=code&scope=openid email profile"
    )
    return {"url": google_auth_url}

@app.get("/google-auth/callback/")
async def google_auth_callback(code: str):
    try:
        # Exchange code for access token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": "http://127.0.0.1:8000/google-auth/callback",
            "grant_type": "authorization_code",
        }
        token_response = requests.post(token_url, data=token_data).json()

        if "id_token" not in token_response:
            raise HTTPException(status_code=400, detail="Failed to fetch ID token from Google")

        id_token_value = token_response["id_token"]
        id_info = id_token.verify_oauth2_token(id_token_value, GoogleRequest(), GOOGLE_CLIENT_ID)

        email = id_info["email"]
        username = id_info.get("name", email.split("@")[0])

        # Check if user exists, otherwise create a new user
        user = await get_user_by_email(email)
        if not user:
            hashed_password = pwd_context.hash("google_oauth_dummy_password")
            await create_user(username, email, hashed_password)

        # Generate JWT for the user
        access_token = create_access_token(data={"sub": email})

        # Redirect to front-end with the token
        redirect_url = f"http://127.0.0.1:8000/?access_token={access_token}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logging.error(f"Google authentication error: {str(e)}")
        raise HTTPException(status_code=400, detail="Google Authentication failed")

# File handling
def extract_text(file: UploadFile) -> Optional[str]:
    try:
        if file.filename.endswith(".txt"):
            return file.file.read().decode("utf-8")
        elif file.filename.endswith(".docx"):
            doc = Document(BytesIO(file.file.read()))
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        elif file.filename.endswith(".pdf"):
            pdf_reader = PdfReader(BytesIO(file.file.read()))
            return "".join(page.extract_text() for page in pdf_reader.pages)
        else:
            return None
    except Exception as e:
        logging.error(f"Error reading file: {str(e)}")
        return None

@app.post("/ask/")
async def ask_question(
    file: UploadFile = File(...),
    question: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        file_content = file.file.read()
        file_hash = hashlib.md5(file_content).hexdigest()

        if file_hash in file_cache:
            text_content = file_cache[file_hash]
        else:
            text_content = extract_text(UploadFile(filename=file.filename, file=BytesIO(file_content)))
            if not text_content:
                return {"error": f"Unsupported file type or failed to extract text from {file.filename}"}
            file_cache[file_hash] = text_content

        max_characters = 6000
        text_content = text_content[:max_characters] + "..." if len(text_content) > max_characters else text_content

        openai.api_key = os.getenv("OPENAI_API_KEY")
        openai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Document content: {text_content}"},
                {"role": "user", "content": f"Question: {question}"}
            ],
            max_tokens=500,
            temperature=0.7
        )

        explanation_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Document content: {text_content}"},
                {"role": "user", "content": f"Question: {question}"},
                {"role": "user", "content": "Explain why the answer is correct."}
            ],
            max_tokens=300,
            temperature=0.7
        )

        raw_answer = openai_response.choices[0].message.content.strip()
        explanation = explanation_response.choices[0].message.content.strip()

        formatted_answer = "".join(
            f"<p>{line.strip()}</p>" if not line.startswith("-") else f"<li>{line[1:].strip()}</li>"
            for line in raw_answer.split("\n")
        )
        formatted_answer = f"<ul>{formatted_answer}</ul>" if "<li" in formatted_answer else formatted_answer

        formatted_explanation = "".join(
            f"<p>{line.strip()}</p>" if not line.startswith("-") else f"<li>{line[1:].strip()}</li>"
            for line in explanation.split("\n")
        )
        formatted_explanation = f"<ul>{formatted_explanation}</ul>" if "<li" in formatted_explanation else formatted_explanation

        return {
            "answer": f"<div style='font-size: 16px; font-weight: bold; color: #007BFF;'>{formatted_answer}</div>",
            "explanation": f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #444;'>{formatted_explanation}</div>"
        }

    except Exception as e:
        logging.error(f"Unhandled error: {e}")
        return {"error": "An unexpected error occurred."}

@app.get("/google-login/")
async def google_login():
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri=http://127.0.0.1:8000/google-auth/callback"
        f"&response_type=code&scope=openid email profile"
    )
    return {"url": google_auth_url}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
