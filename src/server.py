"""
MCP Skills Server v2.1.0 - Mit Multipart File Upload Support
============================================================

Das Problem: OpenWebUI sendet keine echten Base64-Daten bei Tool-Aufrufen!
Die Lösung: Multipart File Upload über /merge_pdfs_upload

Dieser Server unterstützt:
1. Base64-JSON (für direkte API-Clients)
2. Multipart File Upload (für OpenWebUI und Browser)
"""

import os
import uuid
import base64
import shutil
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import json
import yaml
import io

from starlette.applications import Starlette
from starlette.responses import JSONResponse, HTMLResponse, FileResponse, Response
from starlette.routing import Route
from starlette.requests import Request
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# ============ LOGGING SETUP ============
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ KONFIGURATION ============

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "./skills-data"))
FILES_DIR = Path(os.getenv("FILES_DIR", "./files"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8001/files")

FILES_DIR.mkdir(parents=True, exist_ok=True)

FILE_METADATA: dict[str, dict] = {}
METADATA_FILE = FILES_DIR / ".metadata.json"

def load_metadata():
    global FILE_METADATA
    if METADATA_FILE.exists():
        try:
            FILE_METADATA = json.loads(METADATA_FILE.read_text())
        except:
            FILE_METADATA = {}

def save_metadata():
    METADATA_FILE.write_text(json.dumps(FILE_METADATA, default=str))

load_metadata()


# ============ BASE64 HELPER ============

def clean_base64(content_b64: str, filename: str = "unknown") -> bytes:
    """Bereinigt und dekodiert Base64 mit ausführlichem Logging."""
    if not content_b64:
        raise ValueError("Leerer Base64-String")
    
    original_length = len(content_b64)
    logger.debug(f"[{filename}] Original Base64 Länge: {original_length}")
    
    # Prüfe auf Platzhalter
    if content_b64.startswith('<') or 'base64-encoded' in content_b64.lower():
        raise ValueError(f"Platzhalter statt Base64-Daten erhalten! OpenWebUI sendet keine echten Dateiinhalte. Nutze stattdessen /merge_pdfs_upload mit Multipart-Upload.")
    
    # Entferne Data-URL-Präfix
    if ',' in content_b64 and content_b64.startswith('data:'):
        content_b64 = content_b64.split(',', 1)[1]
    
    # Bereinige
    content_b64 = ''.join(content_b64.split())
    content_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', content_b64)
    
    # Padding korrigieren
    missing_padding = len(content_b64) % 4
    if missing_padding:
        content_b64 += '=' * (4 - missing_padding)
    
    # Dekodiere
    decoded = base64.b64decode(content_b64)
    logger.info(f"[{filename}] Dekodiert: {len(decoded)} Bytes")
    
    # Validiere PDF-Header
    if not decoded[:4] == b'%PDF':
        logger.error(f"[{filename}] KEIN PDF! Header: {decoded[:20]}")
        raise ValueError(f"Keine gültigen PDF-Daten. Header: {decoded[:20]}")
    
    return decoded


# ============ FILE STORAGE ============

def store_file(content: bytes, filename: str, mime_type: str = "application/octet-stream") -> dict:
    """Speichert Datei und gibt Metadaten zurück."""
    file_id = str(uuid.uuid4())
    ext = Path(filename).suffix or ""
    stored_filename = f"{file_id}{ext}"
    file_path = FILES_DIR / stored_filename
    
    file_path.write_bytes(content)
    
    metadata = {
        "id": file_id,
        "original_filename": filename,
        "stored_filename": stored_filename,
        "mime_type": mime_type,
        "size": len(content),
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(),
        "download_url": f"{PUBLIC_BASE_URL}/{file_id}/{filename}"
    }
    
    FILE_METADATA[file_id] = metadata
    save_metadata()
    return metadata


def get_file_metadata(file_id: str) -> Optional[dict]:
    return FILE_METADATA.get(file_id)


def get_file_path(file_id: str) -> Optional[Path]:
    metadata = get_file_metadata(file_id)
    if not metadata:
        return None
    file_path = FILES_DIR / metadata["stored_filename"]
    return file_path if file_path.exists() else None


def cleanup_expired_files():
    now = datetime.now()
    expired = [fid for fid, meta in FILE_METADATA.items() 
               if now > datetime.fromisoformat(meta["expires_at"])]
    for file_id in expired:
        meta = FILE_METADATA.pop(file_id, None)
        if meta:
            file_path = FILES_DIR / meta["stored_filename"]
            if file_path.exists():
                file_path.unlink()
    if expired:
        save_metadata()


# ============ SKILL FUNKTIONEN ============

def load_skill_content(skill_name: str) -> dict | None:
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    meta_path = SKILLS_DIR / skill_name / "meta.yaml"
    
    if not skill_path.exists():
        return None
    
    result = {
        "name": skill_name,
        "content": skill_path.read_text(encoding="utf-8"),
        "meta": {}
    }
    
    if meta_path.exists():
        try:
            result["meta"] = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except:
            pass
    
    return result


def list_available_skills() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    return sorted([d.name for d in SKILLS_DIR.iterdir() 
                   if d.is_dir() and (d / "SKILL.md").exists() and not d.name.startswith("_")])


def tool_list_skills() -> str:
    skills = list_available_skills()
    if not skills:
        return "Keine Skills verfügbar."
    result = "# Verfügbare Skills\n\n"
    for skill_name in skills:
        skill = load_skill_content(skill_name)
        if skill:
            description = skill.get("meta", {}).get("description", "Keine Beschreibung")
            result += f"- **{skill_name}**: {description}\n"
    return result


def tool_get_skill(skill_name: str) -> str:
    skill = load_skill_content(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' nicht gefunden. Verfügbare: {', '.join(list_available_skills())}"
    return skill["content"]


def tool_search_skills(query: str) -> str:
    query_lower = query.lower()
    matches = [name for name in list_available_skills() 
               if query_lower in f"{name} {load_skill_content(name) or {}}".lower()]
    if not matches:
        return f"Keine Skills gefunden für '{query}'."
    return f"Skills mit '{query}': {', '.join(matches)}"


# ============ PDF TOOLS ============

def merge_pdfs_from_bytes(pdf_list: list[tuple[str, bytes]]) -> dict:
    """
    Fügt PDFs zusammen aus einer Liste von (filename, bytes) Tupeln.
    Wird sowohl von Base64-JSON als auch Multipart-Upload verwendet.
    """
    try:
        from pypdf import PdfWriter, PdfReader
        
        if not pdf_list:
            return {"success": False, "message": "Keine PDF-Dateien übergeben"}
        
        writer = PdfWriter()
        
        for filename, pdf_bytes in pdf_list:
            logger.info(f"Verarbeite {filename}: {len(pdf_bytes)} Bytes")
            
            # Validiere PDF-Header
            if not pdf_bytes[:4] == b'%PDF':
                return {
                    "success": False, 
                    "message": f"Datei {filename} ist kein gültiges PDF. Header: {pdf_bytes[:20]}"
                }
            
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                logger.info(f"{filename}: {len(reader.pages)} Seiten")
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                return {"success": False, "message": f"Fehler beim Lesen von {filename}: {str(e)}"}
        
        # Schreibe Ergebnis
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        result_filename = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        metadata = store_file(output.read(), result_filename, "application/pdf")
        
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": result_filename,
            "size": metadata["size"],
            "pages_total": len(writer.pages),
            "message": f"✓ {len(pdf_list)} PDFs zusammengefügt ({len(writer.pages)} Seiten). Download: {metadata['download_url']}"
        }
        
    except ImportError:
        return {"success": False, "message": "pypdf ist nicht installiert"}
    except Exception as e:
        logger.exception("Fehler beim PDF-Merge")
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_merge_pdfs(pdf_files_base64: list[dict]) -> dict:
    """Fügt PDFs aus Base64-JSON zusammen."""
    pdf_list = []
    for pdf_data in pdf_files_base64:
        filename = pdf_data.get("filename", "unknown.pdf")
        content_b64 = pdf_data.get("content", "")
        
        try:
            pdf_bytes = clean_base64(content_b64, filename)
            pdf_list.append((filename, pdf_bytes))
        except Exception as e:
            return {"success": False, "message": f"Fehler beim Lesen von {filename}: {str(e)}"}
    
    return merge_pdfs_from_bytes(pdf_list)


def tool_split_pdf(pdf_base64: str, filename: str, pages: str) -> dict:
    """Extrahiert Seiten aus PDF."""
    try:
        from pypdf import PdfWriter, PdfReader
        
        pdf_bytes = clean_base64(pdf_base64, filename)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        
        page_indices = []
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-")
                page_indices.extend(range(int(start) - 1, min(int(end), total_pages)))
            else:
                idx = int(part) - 1
                if 0 <= idx < total_pages:
                    page_indices.append(idx)
        
        if not page_indices:
            return {"success": False, "message": "Keine gültigen Seiten"}
        
        writer = PdfWriter()
        for idx in page_indices:
            writer.add_page(reader.pages[idx])
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        base_name = Path(filename).stem
        result_filename = f"{base_name}_pages_{pages.replace(',', '_').replace('-', 'to')}.pdf"
        metadata = store_file(output.read(), result_filename, "application/pdf")
        
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": result_filename,
            "pages_extracted": len(page_indices),
            "message": f"Seiten extrahiert. Download: {metadata['download_url']}"
        }
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_pdf_to_images(pdf_base64: str, filename: str, dpi: int = 150) -> dict:
    """Konvertiert PDF zu Bildern."""
    try:
        from pdf2image import convert_from_bytes
        
        pdf_bytes = clean_base64(pdf_base64, filename)
        images = convert_from_bytes(pdf_bytes, dpi=dpi)
        
        base_name = Path(filename).stem
        results = []
        
        for i, image in enumerate(images):
            img_buffer = io.BytesIO()
            image.save(img_buffer, format="PNG")
            img_buffer.seek(0)
            
            img_filename = f"{base_name}_page_{i+1}.png"
            metadata = store_file(img_buffer.read(), img_filename, "image/png")
            results.append({
                "page": i + 1,
                "download_url": metadata["download_url"],
                "filename": img_filename
            })
        
        return {
            "success": True,
            "images": results,
            "total_pages": len(results),
            "message": f"{len(results)} Seiten exportiert."
        }
    except ImportError:
        return {"success": False, "message": "pdf2image nicht installiert"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_create_text_pdf(text: str, filename: str = "document.pdf") -> dict:
    """Erstellt PDF aus Text."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        
        story = []
        for para in text.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.replace("\n", "<br/>"), styles['Normal']))
                story.append(Spacer(1, 12))
        
        doc.build(story)
        buffer.seek(0)
        
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        
        metadata = store_file(buffer.read(), filename, "application/pdf")
        
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": filename,
            "message": f"PDF erstellt. Download: {metadata['download_url']}"
        }
    except ImportError:
        return {"success": False, "message": "reportlab nicht installiert"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_upload_file(content_base64: str, filename: str, mime_type: str = "application/octet-stream") -> dict:
    """Speichert Datei aus Base64."""
    try:
        content = clean_base64(content_base64, filename)
        metadata = store_file(content, filename, mime_type)
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": filename,
            "size": metadata["size"],
            "message": f"Datei gespeichert. Download: {metadata['download_url']}"
        }
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


# ============ HTTP ENDPOINTS ============

async def health(request):
    cleanup_expired_files()
    return JSONResponse({
        "status": "healthy",
        "skills_count": len(list_available_skills()),
        "files_count": len(FILE_METADATA)
    })


async def root(request):
    return JSONResponse({
        "name": "MCP Skills Server",
        "version": "2.1.0",
        "note": "Für PDF-Upload mit OpenWebUI nutze /merge_pdfs_upload (Multipart) statt /merge_pdfs (Base64-JSON)",
        "endpoints": {
            "skills": ["/list_skills", "/get_skill", "/search_skills"],
            "tools": ["/merge_pdfs", "/merge_pdfs_upload", "/split_pdf", "/pdf_to_images", "/create_text_pdf"],
            "files": ["/files/{file_id}/{filename}"]
        }
    })


# Skill Endpoints
async def endpoint_list_skills(request):
    return JSONResponse({"result": tool_list_skills()})

async def endpoint_get_skill(request):
    skill_name = request.query_params.get("skill_name", "")
    return JSONResponse({"result": tool_get_skill(skill_name)})

async def endpoint_search_skills(request):
    query = request.query_params.get("query", "")
    return JSONResponse({"result": tool_search_skills(query)})


# PDF Tool Endpoints - JSON (Base64)
async def endpoint_merge_pdfs(request):
    """Erwartet Base64-kodierte PDFs im JSON-Body."""
    try:
        data = await request.json()
        logger.info(f"merge_pdfs JSON request")
        pdf_files = data.get("pdf_files", [])
        logger.info(f"Anzahl PDFs: {len(pdf_files)}")
        
        # Debug: Zeige was wir bekommen haben
        for i, pdf in enumerate(pdf_files):
            filename = pdf.get("filename", "unknown")
            content = pdf.get("content", "")
            logger.info(f"PDF {i+1}: {filename}, content length: {len(content)}")
            if content:
                logger.info(f"  Content starts with: {content[:80]}...")
        
        result = tool_merge_pdfs(pdf_files)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Fehler in endpoint_merge_pdfs")
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


# ============ MULTIPART UPLOAD ENDPOINT (für OpenWebUI) ============

async def endpoint_merge_pdfs_upload(request: Request):
    """
    Multipart File Upload für PDF-Merge.
    
    Verwendung mit curl:
        curl -X POST -F "files=@datei1.pdf" -F "files=@datei2.pdf" http://localhost:8001/merge_pdfs_upload
    
    Oder im Browser mit einem HTML-Formular.
    """
    try:
        form = await request.form()
        logger.info(f"Multipart form keys: {list(form.keys())}")
        
        pdf_list = []
        
        # Verarbeite alle hochgeladenen Dateien
        # Unterstützt sowohl "files" als auch "file" und einzelne Felder
        for key in form.keys():
            items = form.getlist(key)  # Hole alle Werte für diesen Key
            
            for item in items:
                # Prüfe ob es eine Datei ist (hat file und filename Attribute)
                if hasattr(item, 'file') and hasattr(item, 'filename'):
                    filename = item.filename
                    content = await item.read()
                    logger.info(f"Datei empfangen: {filename}, {len(content)} Bytes")
                    
                    # Prüfe ob es ein PDF ist
                    if content[:4] == b'%PDF':
                        pdf_list.append((filename, content))
                        logger.info(f"✓ {filename} ist ein gültiges PDF")
                    else:
                        logger.warning(f"✗ {filename} ist KEIN PDF (Header: {content[:20]})")
                        return JSONResponse({
                            "success": False,
                            "message": f"Datei {filename} ist kein gültiges PDF. Header: {content[:20]}"
                        }, status_code=400)
        
        if not pdf_list:
            return JSONResponse({
                "success": False,
                "message": "Keine PDF-Dateien im Upload gefunden. Sende Dateien als 'files' field mit multipart/form-data."
            }, status_code=400)
        
        logger.info(f"Merge {len(pdf_list)} PDFs via Multipart Upload")
        result = merge_pdfs_from_bytes(pdf_list)
        return JSONResponse(result)
        
    except Exception as e:
        logger.exception("Fehler in endpoint_merge_pdfs_upload")
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


async def endpoint_split_pdf(request):
    try:
        data = await request.json()
        result = tool_split_pdf(
            data.get("pdf_base64", ""),
            data.get("filename", "document.pdf"),
            data.get("pages", "1")
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


async def endpoint_pdf_to_images(request):
    try:
        data = await request.json()
        result = tool_pdf_to_images(
            data.get("pdf_base64", ""),
            data.get("filename", "document.pdf"),
            data.get("dpi", 150)
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


async def endpoint_create_text_pdf(request):
    try:
        data = await request.json()
        result = tool_create_text_pdf(
            data.get("text", ""),
            data.get("filename", "document.pdf")
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


async def endpoint_upload_file(request):
    try:
        data = await request.json()
        result = tool_upload_file(
            data.get("content_base64", ""),
            data.get("filename", "file"),
            data.get("mime_type", "application/octet-stream")
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


# File Download
async def endpoint_download_file(request):
    file_id = request.path_params.get("file_id", "")
    requested_filename = request.path_params.get("filename", "")
    
    metadata = get_file_metadata(file_id)
    if not metadata:
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    
    file_path = get_file_path(file_id)
    if not file_path:
        return JSONResponse({"error": "Datei nicht mehr verfügbar"}, status_code=404)
    
    return FileResponse(
        path=str(file_path),
        filename=metadata.get("original_filename", requested_filename),
        media_type=metadata.get("mime_type", "application/octet-stream")
    )


# ============ UPLOAD-FORMULAR (für einfaches Testen) ============

async def upload_form(request):
    """Einfaches HTML-Formular zum Testen des PDF-Uploads."""
    base_url = str(request.base_url).rstrip("/")
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>PDF Merge - Upload</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #333; }}
            .upload-area {{ 
                border: 2px dashed #ccc; 
                padding: 40px; 
                text-align: center;
                margin: 20px 0;
                background: #f9f9f9;
            }}
            input[type="file"] {{ margin: 20px 0; }}
            button {{ 
                background: #007bff; 
                color: white; 
                padding: 10px 30px; 
                border: none; 
                cursor: pointer;
                font-size: 16px;
            }}
            button:hover {{ background: #0056b3; }}
            #result {{ 
                margin-top: 20px; 
                padding: 20px; 
                background: #e9ffe9; 
                display: none;
                border-radius: 5px;
            }}
            #result.error {{ background: #ffe9e9; }}
            a {{ color: #007bff; }}
        </style>
    </head>
    <body>
        <h1>🔗 PDF Merge Tool</h1>
        <p>Wähle mehrere PDF-Dateien aus, um sie zusammenzufügen:</p>
        
        <form id="uploadForm" enctype="multipart/form-data">
            <div class="upload-area">
                <input type="file" name="files" id="files" multiple accept=".pdf" required>
                <p>PDF-Dateien auswählen (mehrere möglich)</p>
            </div>
            <button type="submit">PDFs zusammenfügen</button>
        </form>
        
        <div id="result"></div>
        
        <script>
            document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const formData = new FormData();
                const files = document.getElementById('files').files;
                
                for (let i = 0; i < files.length; i++) {{
                    formData.append('files', files[i]);
                }}
                
                const resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.className = '';
                resultDiv.innerHTML = '⏳ Verarbeite...';
                
                try {{
                    const response = await fetch('{base_url}/merge_pdfs_upload', {{
                        method: 'POST',
                        body: formData
                    }});
                    const data = await response.json();
                    
                    if (data.success) {{
                        resultDiv.innerHTML = `
                            <h3>✅ Erfolgreich!</h3>
                            <p>${{data.message}}</p>
                            <p><a href="${{data.download_url}}" target="_blank">📥 Download: ${{data.filename}}</a></p>
                            <p>Größe: ${{(data.size / 1024).toFixed(1)}} KB | Seiten: ${{data.pages_total}}</p>
                        `;
                    }} else {{
                        resultDiv.className = 'error';
                        resultDiv.innerHTML = `<h3>❌ Fehler</h3><p>${{data.message}}</p>`;
                    }}
                }} catch (err) {{
                    resultDiv.className = 'error';
                    resultDiv.innerHTML = `<h3>❌ Fehler</h3><p>${{err.message}}</p>`;
                }}
            }});
        </script>
    </body>
    </html>
    """)


# ============ OPENAPI SCHEMA ============

def get_openapi_schema(request):
    base_url = str(request.base_url).rstrip("/")
    if not base_url.startswith("https"):
        base_url = base_url.replace("http://", "https://")
    
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "MCP Skills Server",
            "description": "Server für Skills und PDF-Verarbeitung.\n\n**Für OpenWebUI:** Nutze `/merge_pdfs_upload` mit Multipart-Upload statt `/merge_pdfs`.\n\n**Test-UI:** Besuche `/upload` für ein einfaches Upload-Formular.",
            "version": "2.1.0"
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/list_skills": {
                "get": {
                    "operationId": "list_skills",
                    "summary": "Liste alle Skills",
                    "responses": {"200": {"description": "Liste der Skills"}}
                }
            },
            "/get_skill": {
                "get": {
                    "operationId": "get_skill",
                    "summary": "Hole einen Skill",
                    "parameters": [{"name": "skill_name", "in": "query", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Skill-Inhalt"}}
                }
            },
            "/search_skills": {
                "get": {
                    "operationId": "search_skills",
                    "summary": "Durchsuche Skills",
                    "parameters": [{"name": "query", "in": "query", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Suchergebnisse"}}
                }
            },
            "/merge_pdfs_upload": {
                "post": {
                    "operationId": "merge_pdfs_upload",
                    "summary": "🔗 PDFs zusammenfügen (Multipart Upload) - EMPFOHLEN",
                    "description": "Fügt PDF-Dateien zusammen. Akzeptiert echte Datei-Uploads als multipart/form-data.\n\n**Curl-Beispiel:**\n```\ncurl -X POST -F 'files=@datei1.pdf' -F 'files=@datei2.pdf' {base_url}/merge_pdfs_upload\n```",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "files": {
                                            "type": "array",
                                            "items": {"type": "string", "format": "binary"},
                                            "description": "PDF-Dateien"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL"}}
                }
            },
            "/merge_pdfs": {
                "post": {
                    "operationId": "merge_pdfs",
                    "summary": "PDFs zusammenfügen (Base64-JSON)",
                    "description": "⚠️ Funktioniert NICHT mit OpenWebUI! Nutze stattdessen `/merge_pdfs_upload`.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_files": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "filename": {"type": "string"},
                                                    "content": {"type": "string", "description": "Base64-encoded PDF"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL"}}
                }
            },
            "/split_pdf": {
                "post": {
                    "operationId": "split_pdf",
                    "summary": "Seiten extrahieren",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_base64": {"type": "string"},
                                        "filename": {"type": "string"},
                                        "pages": {"type": "string", "description": "z.B. '1,3,5-7'"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL"}}
                }
            },
            "/pdf_to_images": {
                "post": {
                    "operationId": "pdf_to_images",
                    "summary": "PDF zu Bildern",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_base64": {"type": "string"},
                                        "filename": {"type": "string"},
                                        "dpi": {"type": "integer", "default": 150}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Bild-URLs"}}
                }
            },
            "/create_text_pdf": {
                "post": {
                    "operationId": "create_text_pdf",
                    "summary": "PDF aus Text erstellen",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "filename": {"type": "string", "default": "document.pdf"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL"}}
                }
            }
        }
    }


async def openapi_schema(request):
    return JSONResponse(get_openapi_schema(request))


async def docs(request):
    return HTMLResponse("""
    <!DOCTYPE html><html><head><title>MCP Skills Server - API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
    <body><div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>SwaggerUIBundle({url: "/openapi.json", dom_id: '#swagger-ui'});</script>
    </body></html>
    """)


# ============ APP ============

routes = [
    Route("/", root),
    Route("/health", health),
    Route("/openapi.json", openapi_schema),
    Route("/docs", docs),
    Route("/upload", upload_form),  # HTML Upload-Formular
    
    # Skills
    Route("/list_skills", endpoint_list_skills),
    Route("/get_skill", endpoint_get_skill),
    Route("/search_skills", endpoint_search_skills),
    
    # PDF Tools
    Route("/merge_pdfs", endpoint_merge_pdfs, methods=["POST"]),
    Route("/merge_pdfs_upload", endpoint_merge_pdfs_upload, methods=["POST"]),  # MULTIPART
    Route("/split_pdf", endpoint_split_pdf, methods=["POST"]),
    Route("/pdf_to_images", endpoint_pdf_to_images, methods=["POST"]),
    Route("/create_text_pdf", endpoint_create_text_pdf, methods=["POST"]),
    Route("/upload_file", endpoint_upload_file, methods=["POST"]),
    
    # File Download
    Route("/files/{file_id}/{filename:path}", endpoint_download_file),
]

app = Starlette(routes=routes)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"")
    print(f"🚀 MCP Skills Server v2.1.0")
    print(f"=" * 50)
    print(f"📍 Server: http://{host}:{port}")
    print(f"📁 Skills: {SKILLS_DIR}")
    print(f"📦 Files: {FILES_DIR}")
    print(f"🔗 Public URL: {PUBLIC_BASE_URL}")
    print(f"")
    print(f"📚 Gefundene Skills: {list_available_skills()}")
    print(f"")
    print(f"🌐 Endpoints:")
    print(f"   /docs          - Swagger API Dokumentation")
    print(f"   /upload        - HTML Upload-Formular (zum Testen)")
    print(f"   /merge_pdfs_upload - Multipart PDF Upload (für OpenWebUI)")
    print(f"")
    uvicorn.run(app, host=host, port=port)
