if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8200)

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
import openai
from typing import Optional
from io import BytesIO
from PyPDF2 import PdfReader
from docx import Document
#from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def serve_homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

app = FastAPI()

# Add CORS middleware to allow frontend-backend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development. Restrict in production.
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)


def extract_text(file: UploadFile) -> Optional[str]:
    """
    Extract text from uploaded file based on its type.
    Supports TXT, DOCX, and PDF files.
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
        print(f"Error reading file: {str(e)}")
        return None

@app.post("/ask/")
async def ask_question(
    file: UploadFile = File(...),
    question: str = Form(...),
):
    try:
        # Extract text from the uploaded file
        print(f"Received file: {file.filename}")
        text_content = extract_text(file)
        if not text_content:
            print("Failed to extract text or unsupported file type.")
            return {"error": f"Unsupported file type or failed to extract text from {file.filename}"}

        print(f"Extracted text (first 200 characters): {text_content[:200]}")

        # Truncate the content to fit within token limits
        max_characters = 6000  # Approximation to stay within token limits
        if len(text_content) > max_characters:
            print(f"Text content exceeds {max_characters} characters. Truncating...")
            text_content = text_content[:max_characters] + "..."

        # Call OpenAI API
        try:
            import os
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
            print(f"OpenAI API error: {e}")
            return {"error": "Failed to get a response from OpenAI. Please try again later."}

        # Extract and format response content
        raw_answer = openai_response["choices"][0]["message"]["content"]
        print(f"AI Response: {raw_answer}")

        # Call OpenAI again for explanation of the correct answer
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
            print(f"OpenAI API error during explanation: {e}")
            formatted_explanation = "An explanation could not be generated at this time. Please try again later."

        return {
            "answer": f"<div style='font-size: 16px; font-weight: bold; color: #007BFF;'>{raw_answer}</div>",
            "explanation": f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #444; background: #f9f9f9; padding: 10px; border-left: 4px solid #007BFF;'>{formatted_explanation}</div>"
        }

    except Exception as e:
        print(f"Unhandled error: {e}")
        return {"error": f"An unexpected error occurred: {str(e)}"}
