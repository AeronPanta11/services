from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Depends
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from PyPDF2 import PdfReader
from utility.ResumeParser import ResumeParser
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import logging
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file

# Configuration
MONGO_URI = os.getenv("MONGO_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "test")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "parsed_resumes")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 10 * 1024 * 1024))  # 10MB default

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is not set in .env")

# Global variables for database connection
client = None
database = None
parsed_collection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global client, database, parsed_collection
    try:
        # MongoDB Atlas connection with SSL settings
        client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsAllowInvalidCertificates=True,  # For development - remove in production
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000
        )
        database = client[DATABASE_NAME]
        parsed_collection = database[COLLECTION_NAME]
        
        # Test the connection
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        # Create indexes for better performance
        parsed_collection.create_index("userId")
        logger.info("Database indexes created")
        
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise RuntimeError(f"Database connection failed: {e}")
    
    yield
    
    # Shutdown
    if client:
        client.close()
        logger.info("MongoDB connection closed")

app = FastAPI(
    title="Resume Parser API",
    description="API for parsing PDF resumes and extracting entities",
    version="1.0.0",
    lifespan=lifespan
)

# --- Pydantic Models ---
class ParsedResumeOut(BaseModel):
    id: str
    parsed_text: str
    entities: List[str]
    userId: str

class HealthCheck(BaseModel):
    status: str
    database_connected: bool

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

# --- Dependencies ---
def get_database():
    if database is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return database

def get_parsed_collection():
    if parsed_collection is None:
        raise HTTPException(status_code=503, detail="Database collection not available")
    return parsed_collection

# --- Utility Functions ---
def validate_file_size(file: UploadFile) -> None:
    """Validate file size"""
    if hasattr(file, 'size') and file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File size ({file.size} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes)"
        )

def validate_file_type(file: UploadFile) -> None:
    """Validate file type"""
    if file.content_type != 'application/pdf':
        raise HTTPException(
            status_code=400, 
            detail="Only PDF files are accepted"
        )

def validate_user_id(userId: str) -> ObjectId:
    """Validate and convert userId to ObjectId"""
    try:
        return ObjectId(userId)
    except Exception:
        raise HTTPException(
            status_code=400, 
            detail="Invalid userId format. Must be a valid ObjectId"
        )

def extract_text_from_pdf(pdf_file: UploadFile) -> str:
    """Extract text from PDF file"""
    try:
        # Reset file pointer to beginning
        pdf_file.file.seek(0)
        reader = PdfReader(pdf_file.file)
        
        if len(reader.pages) == 0:
            raise HTTPException(status_code=400, detail="PDF file has no pages")
        
        text = ""
        for page_num, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
                text += page_text
            except Exception as e:
                logger.warning(f"Failed to extract text from page {page_num + 1}: {e}")
                continue
        
        return text.strip()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to extract text from PDF")
        raise HTTPException(
            status_code=400, 
            detail=f"Error reading PDF: {str(e)}"
        )
    finally:
        # Reset file pointer
        try:
            pdf_file.file.seek(0)
        except:
            pass

def parse_resume_text(text: str) -> dict:
    """Parse resume text using ResumeParser"""
    if not text.strip():
        raise HTTPException(
            status_code=400, 
            detail="No text found in the PDF"
        )
    
    parser = ResumeParser()
    try:
        result = parser.parse_resume(text)
        if not result or "parsed_text" not in result:
            raise HTTPException(
                status_code=500, 
                detail="Invalid response from resume parser"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Resume parsing failed")
        raise HTTPException(
            status_code=500, 
            detail=f"Error parsing resume: {str(e)}"
        )

# --- API Endpoints ---
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "message": "Resume Parser API", 
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health", response_model=HealthCheck, tags=["Health"])
async def health_check():
    """Health check endpoint"""
    database_connected = False
    try:
        if client:
            client.admin.command('ping')
            database_connected = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    
    return HealthCheck(
        status="healthy" if database_connected else "degraded",
        database_connected=database_connected
    )

@app.post("/upload_and_save/", response_model=ParsedResumeOut, tags=["Resume"])
async def upload_and_save(
    file: UploadFile = File(..., description="PDF file to parse"),
    userId: str = Form(..., description="User ID (ObjectId format)"),
    collection=Depends(get_parsed_collection)
):
    """
    Upload and parse a PDF resume, then save to database
    
    - **file**: PDF file to parse (max 10MB)
    - **userId**: User ID in ObjectId format
    """
    
    # Validate inputs
    validate_file_size(file)
    validate_file_type(file)
    user_obj_id = validate_user_id(userId)
    
    # Extract text from PDF
    pdf_text = extract_text_from_pdf(file)
    
    # Parse resume
    result = parse_resume_text(pdf_text)
    
    # Prepare data for database
    entities = []
    if "entities" in result and result["entities"]:
        entities = [ent[0] if isinstance(ent, (list, tuple)) else str(ent) 
                   for ent in result["entities"]]
    
    doc = {
        "parsed_text": result["parsed_text"],
        "entities": entities,
        "userId": user_obj_id,
        "created_at": None,  # MongoDB will auto-generate if needed
        "file_name": file.filename,
        "file_size": getattr(file, 'size', None),
        "content_type": file.content_type
    }
    
    # Save to MongoDB
    try:
        insert_result = collection.insert_one(doc)
        if not insert_result.inserted_id:
            raise HTTPException(
                status_code=500, 
                detail="Failed to save document to database"
            )
        
        logger.info(f"Successfully saved parsed resume with ID: {insert_result.inserted_id}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to save parsed data to MongoDB")
        raise HTTPException(
            status_code=500, 
            detail=f"Database error: {str(e)}"
        )
    
    return ParsedResumeOut(
        id=str(insert_result.inserted_id),
        parsed_text=result["parsed_text"],
        entities=entities,
        userId=userId
    )

@app.get("/resume/{resume_id}", response_model=ParsedResumeOut, tags=["Resume"])
async def get_resume(
    resume_id: str,
    collection=Depends(get_parsed_collection)
):
    """Get a parsed resume by ID"""
    try:
        obj_id = ObjectId(resume_id)
    except Exception:
        raise HTTPException(
            status_code=400, 
            detail="Invalid resume ID format"
        )
    
    try:
        doc = collection.find_one({"_id": obj_id})
        if not doc:
            raise HTTPException(
                status_code=404, 
                detail="Resume not found"
            )
        
        return ParsedResumeOut(
            id=str(doc["_id"]),
            parsed_text=doc["parsed_text"],
            entities=doc.get("entities", []),
            userId=str(doc["userId"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to retrieve resume from database")
        raise HTTPException(
            status_code=500, 
            detail="Database error"
        )

@app.get("/resumes/user/{user_id}", response_model=List[ParsedResumeOut], tags=["Resume"])
async def get_user_resumes(
    user_id: str,
    collection=Depends(get_parsed_collection)
):
    """Get all parsed resumes for a specific user"""
    user_obj_id = validate_user_id(user_id)
    
    try:
        cursor = collection.find({"userId": user_obj_id})
        resumes = []
        
        for doc in cursor:
            resumes.append(ParsedResumeOut(
                id=str(doc["_id"]),
                parsed_text=doc["parsed_text"],
                entities=doc.get("entities", []),
                userId=str(doc["userId"])
            ))
        
        return resumes
        
    except Exception as e:
        logger.exception("Failed to retrieve user resumes from database")
        raise HTTPException(
            status_code=500, 
            detail="Database error"
        )

# --- Exception Handlers ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return {
        "detail": exc.detail,
        "status_code": exc.status_code,
        "error_code": getattr(exc, 'error_code', None)
    }

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.exception("Unhandled exception occurred")
    return {
        "detail": "Internal server error",
        "status_code": 500,
        "error_code": "INTERNAL_ERROR"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )