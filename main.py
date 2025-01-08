import asyncio
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import openai
import os
from typing import Optional
from io import BytesIO
from PyPDF2 import PdfReader
from docx import Document
import logging

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Initialize FastAPI app
app = FastAPI()

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

# Serve the homepage
@app.get("/", response_class=HTMLResponse)
async def serve_homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def extract_text(file: UploadFile) -> Optional[str]:
    """
    Extract text from uploaded files (TXT, DOCX, PDF).
    """
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


async def call_openai(api_key: str, content: str, question: str) -> Optional[dict]:
    """
    Call OpenAI API for the main answer and explanation concurrently.
    """
    try:
        tasks = [
            asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Document content: {content}"},
                    {"role": "user", "content": f"Question: {question}"}
                ],
                max_tokens=500,  # Limit tokens to control response size
                temperature=0.7,  # Balance creativity and speed
            ),
            asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Document content: {content}"},
                    {"role": "user", "content": f"Question: {question}"},
                    {"role": "user", "content": "Explain why the answer is correct."}
                ],
                max_tokens=300,  # Limit tokens for explanation
                temperature=0.5,
            ),
        ]
        responses = await asyncio.gather(*tasks)
        return {
            "answer": responses[0].choices[0].message.content.strip(),
            "explanation": responses[1].choices[0].message.content.strip(),
        }
    except Exception as e:
        logging.error(f"OpenAI API error: {e}")
        return None


@app.post("/ask/")
async def ask_question(
    file: UploadFile = File(...),
    question: str = Form(...),
):
    try:
        # Extract text from the uploaded file
        text_content = await asyncio.to_thread(extract_text, file)
        if not text_content:
            return {"error": f"Unsupported file type or failed to extract text from {file.filename}"}

        # Truncate content efficiently
        max_characters = 6000
        text_content = text_content[:max_characters] + "..." if len(text_content) > max_characters else text_content

        # Call OpenAI API
        openai.api_key = os.getenv("OPENAI_API_KEY")
        response = await call_openai(openai.api_key, text_content, question)
        if not response:
            return {"error": "Failed to get a response from OpenAI."}

        # Format answer and explanation
        formatted_answer = "".join(
            f"<p>{line.strip()}</p>" if not line.startswith("-") else f"<li>{line[1:].strip()}</li>"
            for line in response["answer"].split("\n")
        )
        formatted_answer = f"<ul>{formatted_answer}</ul>" if "<li" in formatted_answer else formatted_answer

        return {
            "answer": f"<div style='font-size: 16px; font-weight: bold; color: #007BFF;'>{formatted_answer}</div>",
            "explanation": f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #444;'>{response['explanation']}</div>",
        }
    except Exception as e:
        logging.error(f"Unhandled error: {e}")
        return {"error": "An unexpected error occurred."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
