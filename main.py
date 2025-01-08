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
import hashlib
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

# Cache to store extracted text for reusing uploaded files
file_cache = {}

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

@app.post("/ask/")
async def ask_question(
    file: UploadFile = File(...),
    question: str = Form(...),
):
    try:
        # Generate a hash of the file content to use as a cache key
        file_content = file.file.read()
        file_hash = hashlib.md5(file_content).hexdigest()

        # Check if the file has already been uploaded and extracted
        if file_hash in file_cache:
            logging.info("Reusing cached file content.")
            text_content = file_cache[file_hash]
        else:
            logging.info("Extracting text from new file.")
            text_content = extract_text(UploadFile(filename=file.filename, file=BytesIO(file_content)))
            if not text_content:
                return {"error": f"Unsupported file type or failed to extract text from {file.filename}"}
            file_cache[file_hash] = text_content  # Cache the extracted text

        # Truncate content to fit within token limits
        max_characters = 6000
        text_content = text_content[:max_characters] + "..." if len(text_content) > max_characters else text_content

        # Call OpenAI API using GPT-3.5
        try:
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
        except Exception as e:
            logging.error(f"OpenAI API error: {e}")
            return {"error": "Failed to get a response from OpenAI. Please try again later."}

        # Extract and format response content
        raw_answer = openai_response.choices[0].message.content.strip()
        explanation = explanation_response.choices[0].message.content.strip()

        formatted_answer = "".join(
            f"<p>{line.strip()}</p>" if not line.startswith("-") else f"<li>{line[1:].strip()}</li>"
            for line in raw_answer.split("\n")
        )
        formatted_answer = f"<ul>{formatted_answer}</ul>" if "<li" in formatted_answer else formatted_answer

        formatted_explanation = f"<p style='font-size: 15px; line-height: 1.8; color: #555;'>{explanation}</p>"

        return {
            "answer": f"<div style='font-size: 16px; font-weight: bold; color: #007BFF;'>{formatted_answer}</div>",
            "explanation": f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #444;'>{formatted_explanation}</div>"
        }

    except Exception as e:
        logging.error(f"Unhandled error: {e}")
        return {"error": "An unexpected error occurred."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
