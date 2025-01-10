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
    token = request.query_params.get("access_token")
    if token:
        try:
            user = await get_current_user(token)
            return templates.TemplateResponse("index.html", {"request": request, "user": user})
        except HTTPException:
            return templates.TemplateResponse("index.html", {"request": request, "error": "Invalid token"})
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
        f"&redirect_uri=https://efiway.onrender.com/google-auth/callback"
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
            "redirect_uri": "https://efiway.onrender.com/google-auth/callback",
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
        redirect_url = f"https://efiway.onrender.com/?access_token={access_token}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logging.error(f"Google authentication error: {str(e)}")
        raise HTTPException(status_code=400, detail="Google Authentication failed")
