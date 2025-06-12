from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from pydantic import BaseModel
from PyPDF2 import PdfReader
from utility.ResumeParser import ResumeParser

app = FastAPI()

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
