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
        # Handle TXT files
        if file.filename.endswith(".txt"):
            content = file.file.read().decode("utf-8")
            return content

        # Handle DOCX files
        elif file.filename.endswith(".docx"):
            doc = Document(BytesIO(file.file.read()))
            content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return content

        # Handle PDF files
        elif file.filename.endswith(".pdf"):
            pdf_reader = PdfReader(BytesIO(file.file.read()))
            content = ""
            for page_number, page in enumerate(pdf_reader.pages, start=1):
                content += f"\n[Page {page_number}] {page.extract_text()}"
            return content

        # Unsupported file format
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
        # Extract text from the uploaded file
        logging.info(f"Received file: {file.filename}")
        text_content = extract_text(file)
        if not text_content:
            logging.error("Failed to extract text or unsupported file type.")
            return {"error": f"Unsupported file type or failed to extract text from {file.filename}"}

        # Truncate content to fit within token limits
        max_characters = 6000  # Approximation to stay within token limits
        if len(text_content) > max_characters:
            logging.info(f"Text content exceeds {max_characters} characters. Truncating...")
            text_content = text_content[:max_characters] + "..."

        # Call OpenAI API
        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            openai_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Document content: {text_content}"},
                    {"role": "user", "content": f"Question: {question}"}
                ]
            )
        except Exception as e:
            logging.error(f"OpenAI API error: {e}")
            return {"error": "Failed to get a response from OpenAI. Please try again later."}

        # Extract and format response content
        raw_answer = openai_response["choices"][0]["message"]["content"]
        logging.info(f"AI Response: {raw_answer}")

        # Generate detailed explanation
        try:
            explanation_prompt = (
                "Explain why the answer is correct. "
                "If no options are provided, focus only on explaining the answer in detail."
            )

            explanation_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Document content: {text_content}"},
                    {"role": "user", "content": f"Question: {question}"},
                    {"role": "user", "content": explanation_prompt}
                ]
            )
            detailed_explanation = explanation_response["choices"][0]["message"]["content"]

            # Format explanation for better display
            formatted_explanation = (
                f"<p style='font-size: 15px; line-height: 1.8; color: #555;'>{detailed_explanation.strip()}</p>"
            )

        except Exception as e:
            logging.error(f"OpenAI API error during explanation: {e}")
            formatted_explanation = "An explanation could not be generated at this time. Please try again later."

        return {
            "answer": f"<div style='font-size: 16px; font-weight: bold; color: #007BFF;'>{raw_answer}</div>",
            "explanation": f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #444; background: #f9f9f9; padding: 10px; border-left: 4px solid #007BFF;'>{formatted_explanation}</div>"
        }

    except Exception as e:
        logging.error(f"Unhandled error: {e}")
        return {"error": f"An unexpected error occurred: {str(e)}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
