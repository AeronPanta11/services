from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from pydantic import BaseModel
from PyPDF2 import PdfReader
from utility.ResumeParser import ResumeParser
from fastapi import FastAPI
from huggingface_hub import snapshot_download
import shutil
import os
import logging

app = FastAPI()

BASE_DIR = "./model"
REPO_ID = "Aeronpanta/resumeparser"

def download_model_repo():
    if os.path.exists(BASE_DIR) and os.path.isdir(BASE_DIR):
        logging.info("Model already downloaded.")
        return
    snapshot_path = snapshot_download(repo_id=REPO_ID)
    os.makedirs(BASE_DIR, exist_ok=True)
    shutil.copytree(snapshot_path, BASE_DIR, dirs_exist_ok=True)
    logging.info("Model downloaded and copied to base directory.")

@app.on_event("startup")
async def startup_event():
    download_model_repo()

class ParsedResumeOut(BaseModel):
    parsed_text: str
    entities: list

def extract_text_from_pdf(pdf_file: UploadFile) -> str:
    try:
        pdf_file.file.seek(0)
        reader = PdfReader(pdf_file.file)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text += page_text
        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading PDF: {str(e)}")

@app.post("/parse_resume", response_model=ParsedResumeOut)
async def parse_resume(file: UploadFile = File(...)):
    if file.content_type != 'application/pdf':
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    pdf_text = extract_text_from_pdf(file)
    if not pdf_text:
        raise HTTPException(status_code=400, detail="No text found in the PDF")
    parser = ResumeParser()
    result = parser.parse_resume(pdf_text)
    entities = []
    if "entities" in result and result["entities"]:
        entities = [ent[0] if isinstance(ent, (list, tuple)) else str(ent) for ent in result["entities"]]
    return ParsedResumeOut(parsed_text=result.get("parsed_text", ""), entities=entities)


@app.get("/")
async def root():
    return {"message": "Welcome to the Resume Parser API. Use /parse_resume to parse a PDF resume."}
# Ensure the utility module is in the Python path