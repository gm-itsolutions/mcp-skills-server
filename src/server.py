"""
MCP Skills Server - Mit echten Tools und File-Downloads
========================================================

Dieser Server stellt:
1. Skill-Anleitungen bereit (wie bisher)
2. Echte Tools die Code ausführen (PDF merge, split, etc.)
3. Download-Links für generierte Dateien
"""

import os
import uuid
import base64
import shutil
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import json
import yaml
import io

from starlette.applications import Starlette
from starlette.responses import JSONResponse, HTMLResponse, FileResponse, Response
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# ============ KONFIGURATION ============

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "./skills-data"))
FILES_DIR = Path(os.getenv("FILES_DIR", "./files"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8001/files")

# Stelle sicher dass Verzeichnisse existieren
FILES_DIR.mkdir(parents=True, exist_ok=True)

# File-Metadaten speichern (in Produktion: Redis/DB)
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

def clean_base64(content_b64: str) -> bytes:
    """
    Bereinigt einen Base64-String und dekodiert ihn sicher.
    
    Behandelt:
    - Whitespace (Leerzeichen, Newlines, Tabs)
    - Nicht-ASCII-Zeichen
    - Padding-Probleme
    - Data-URL-Präfixe (data:application/pdf;base64,)
    """
    if not content_b64:
        raise ValueError("Leerer Base64-String")
    
    # 1. Entferne Data-URL-Präfix falls vorhanden
    if ',' in content_b64 and content_b64.startswith('data:'):
        content_b64 = content_b64.split(',', 1)[1]
    
    # 2. Entferne alle Whitespace-Zeichen
    content_b64 = ''.join(content_b64.split())
    
    # 3. Entferne alle nicht-Base64-Zeichen (behalte nur A-Z, a-z, 0-9, +, /, =)
    content_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', content_b64)
    
    # 4. Korrigiere Padding falls nötig
    # Base64-Strings müssen eine Länge haben, die durch 4 teilbar ist
    missing_padding = len(content_b64) % 4
    if missing_padding:
        content_b64 += '=' * (4 - missing_padding)
    
    # 5. Dekodiere
    return base64.b64decode(content_b64)


# ============ SKILL FUNKTIONEN (wie bisher) ============

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
            result["meta"] = {}
    
    return result


def list_available_skills() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    
    skills = []
    for d in SKILLS_DIR.iterdir():
        if d.is_dir() and (d / "SKILL.md").exists():
            if not d.name.startswith("_"):
                skills.append(d.name)
    return sorted(skills)


# ============ FILE STORAGE SYSTEM ============

def store_file(content: bytes, filename: str, mime_type: str = "application/octet-stream") -> dict:
    """Speichert eine Datei und gibt Metadaten mit Download-URL zurück."""
    file_id = str(uuid.uuid4())
    
    # Behalte Dateiendung bei
    ext = Path(filename).suffix or ""
    stored_filename = f"{file_id}{ext}"
    file_path = FILES_DIR / stored_filename
    
    # Schreibe Datei
    file_path.write_bytes(content)
    
    # Metadaten speichern
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
    """Holt Metadaten für eine Datei."""
    return FILE_METADATA.get(file_id)


def get_file_path(file_id: str) -> Optional[Path]:
    """Holt den Pfad einer gespeicherten Datei."""
    metadata = get_file_metadata(file_id)
    if not metadata:
        return None
    
    file_path = FILES_DIR / metadata["stored_filename"]
    if not file_path.exists():
        return None
    
    return file_path


def cleanup_expired_files():
    """Löscht abgelaufene Dateien."""
    now = datetime.now()
    expired = []
    
    for file_id, meta in FILE_METADATA.items():
        expires_at = datetime.fromisoformat(meta["expires_at"])
        if now > expires_at:
            expired.append(file_id)
    
    for file_id in expired:
        meta = FILE_METADATA.pop(file_id, None)
        if meta:
            file_path = FILES_DIR / meta["stored_filename"]
            if file_path.exists():
                file_path.unlink()
    
    if expired:
        save_metadata()


# ============ TOOL FUNKTIONEN ============

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
        available = list_available_skills()
        return f"Skill '{skill_name}' nicht gefunden. Verfügbare: {', '.join(available)}"
    return skill["content"]


def tool_search_skills(query: str) -> str:
    query_lower = query.lower()
    matches = []
    for skill_name in list_available_skills():
        skill = load_skill_content(skill_name)
        if skill:
            searchable = f"{skill_name} {skill['content']} {skill.get('meta', {})}"
            if query_lower in searchable.lower():
                matches.append(skill_name)
    if not matches:
        return f"Keine Skills gefunden, die '{query}' enthalten."
    return f"Skills mit '{query}': {', '.join(matches)}"


# ============ PDF TOOLS ============

def tool_merge_pdfs(pdf_files_base64: list[dict]) -> dict:
    """
    Fügt mehrere PDFs zusammen.
    
    Args:
        pdf_files_base64: Liste von {"filename": str, "content": base64-string}
    
    Returns:
        {"success": bool, "download_url": str, "message": str}
    """
    try:
        from pypdf import PdfWriter, PdfReader
        
        writer = PdfWriter()
        
        for pdf_data in pdf_files_base64:
            filename = pdf_data.get("filename", "unknown.pdf")
            content_b64 = pdf_data.get("content", "")
            
            try:
                # KORRIGIERT: Verwende clean_base64 für robustes Decoding
                pdf_bytes = clean_base64(content_b64)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                return {"success": False, "message": f"Fehler beim Lesen von {filename}: {str(e)}"}
        
        # Schreibe das Ergebnis
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        # Speichere die Datei
        result_filename = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        metadata = store_file(output.read(), result_filename, "application/pdf")
        
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": result_filename,
            "size": metadata["size"],
            "message": f"PDFs erfolgreich zusammengefügt. Download: {metadata['download_url']}"
        }
        
    except ImportError:
        return {"success": False, "message": "pypdf ist nicht installiert"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_split_pdf(pdf_base64: str, filename: str, pages: str) -> dict:
    """
    Extrahiert bestimmte Seiten aus einem PDF.
    
    Args:
        pdf_base64: PDF als base64-String
        filename: Originaler Dateiname
        pages: Seitenangabe wie "1,3,5-7" oder "1-3"
    
    Returns:
        {"success": bool, "download_url": str, "message": str}
    """
    try:
        from pypdf import PdfWriter, PdfReader
        
        # KORRIGIERT: Verwende clean_base64
        pdf_bytes = clean_base64(pdf_base64)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        
        # Parse Seitenangabe
        page_indices = []
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-")
                start = int(start) - 1  # 0-basiert
                end = int(end)
                page_indices.extend(range(start, min(end, total_pages)))
            else:
                idx = int(part) - 1
                if 0 <= idx < total_pages:
                    page_indices.append(idx)
        
        if not page_indices:
            return {"success": False, "message": "Keine gültigen Seiten angegeben"}
        
        writer = PdfWriter()
        for idx in page_indices:
            writer.add_page(reader.pages[idx])
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        # Speichere die Datei
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
    """
    Konvertiert PDF-Seiten zu Bildern.
    
    Args:
        pdf_base64: PDF als base64-String
        filename: Originaler Dateiname
        dpi: Auflösung (default: 150)
    
    Returns:
        {"success": bool, "images": list[{"page": int, "download_url": str}], "message": str}
    """
    try:
        from pdf2image import convert_from_bytes
        
        # KORRIGIERT: Verwende clean_base64
        pdf_bytes = clean_base64(pdf_base64)
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
            "message": f"{len(results)} Seiten als Bilder exportiert."
        }
        
    except ImportError:
        return {"success": False, "message": "pdf2image ist nicht installiert"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


def tool_create_text_pdf(text: str, filename: str = "document.pdf") -> dict:
    """
    Erstellt ein einfaches PDF aus Text.
    
    Args:
        text: Der Text für das PDF
        filename: Gewünschter Dateiname
    
    Returns:
        {"success": bool, "download_url": str, "message": str}
    """
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
        return {"success": False, "message": "reportlab ist nicht installiert"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


# ============ GENERISCHES FILE UPLOAD TOOL ============

def tool_upload_file(content_base64: str, filename: str, mime_type: str = "application/octet-stream") -> dict:
    """
    Speichert eine beliebige Datei und gibt Download-URL zurück.
    
    Args:
        content_base64: Datei-Inhalt als base64-String
        filename: Dateiname
        mime_type: MIME-Type der Datei
    
    Returns:
        {"success": bool, "download_url": str, "message": str}
    """
    try:
        # KORRIGIERT: Verwende clean_base64
        content = clean_base64(content_base64)
        metadata = store_file(content, filename, mime_type)
        
        return {
            "success": True,
            "download_url": metadata["download_url"],
            "filename": filename,
            "size": metadata["size"],
            "expires_at": metadata["expires_at"],
            "message": f"Datei gespeichert. Download: {metadata['download_url']}"
        }
    except Exception as e:
        return {"success": False, "message": f"Fehler: {str(e)}"}


# ============ HTTP ENDPOINTS ============

async def health(request):
    cleanup_expired_files()  # Cleanup bei Health-Check
    return JSONResponse({
        "status": "healthy",
        "skills_count": len(list_available_skills()),
        "files_count": len(FILE_METADATA)
    })


async def root(request):
    return JSONResponse({
        "name": "MCP Skills Server",
        "version": "2.0.1",
        "features": ["skills", "pdf-tools", "file-downloads"],
        "endpoints": {
            "skills": ["/list_skills", "/get_skill", "/search_skills"],
            "tools": ["/merge_pdfs", "/split_pdf", "/pdf_to_images", "/create_text_pdf", "/upload_file"],
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


# PDF Tool Endpoints
async def endpoint_merge_pdfs(request):
    try:
        data = await request.json()
        pdf_files = data.get("pdf_files", [])
        result = tool_merge_pdfs(pdf_files)
        return JSONResponse(result)
    except Exception as e:
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


# File Download Endpoint
async def endpoint_download_file(request):
    file_id = request.path_params.get("file_id", "")
    requested_filename = request.path_params.get("filename", "")
    
    metadata = get_file_metadata(file_id)
    if not metadata:
        return JSONResponse({"error": "Datei nicht gefunden"}, status_code=404)
    
    file_path = get_file_path(file_id)
    if not file_path:
        return JSONResponse({"error": "Datei nicht mehr verfügbar"}, status_code=404)
    
    # Verwende originalen Dateinamen für Content-Disposition
    filename = metadata.get("original_filename", requested_filename)
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=metadata.get("mime_type", "application/octet-stream")
    )


# ============ OPENAPI SCHEMA ============

def get_openapi_schema(request):
    base_url = str(request.base_url).rstrip("/")
    base_url = base_url.replace("http://", "https://")
    
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "MCP Skills Server",
            "description": "Server für Skills und PDF-Verarbeitung mit Download-Links",
            "version": "2.0.1"
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/list_skills": {
                "get": {
                    "operationId": "list_skills",
                    "summary": "Liste alle verfügbaren Skills",
                    "description": "Gibt eine Liste aller verfügbaren Skills zurück.",
                    "responses": {
                        "200": {
                            "description": "Liste der Skills",
                            "content": {"application/json": {"schema": {"type": "object"}}}
                        }
                    }
                }
            },
            "/get_skill": {
                "get": {
                    "operationId": "get_skill",
                    "summary": "Hole einen Skill",
                    "parameters": [{
                        "name": "skill_name",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Skill-Inhalt"}}
                }
            },
            "/search_skills": {
                "get": {
                    "operationId": "search_skills",
                    "summary": "Durchsuche Skills",
                    "parameters": [{
                        "name": "query",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"}
                    }],
                    "responses": {"200": {"description": "Suchergebnisse"}}
                }
            },
            "/merge_pdfs": {
                "post": {
                    "operationId": "merge_pdfs",
                    "summary": "Füge PDFs zusammen",
                    "description": "Fügt mehrere PDFs zu einem zusammen und gibt Download-Link zurück.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_files": {
                                            "type": "array",
                                            "description": "Liste der PDFs mit filename und content (base64)",
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
                    "responses": {
                        "200": {
                            "description": "Ergebnis mit Download-URL",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "download_url": {"type": "string"},
                                            "message": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/split_pdf": {
                "post": {
                    "operationId": "split_pdf",
                    "summary": "Extrahiere Seiten aus PDF",
                    "description": "Extrahiert bestimmte Seiten und gibt Download-Link zurück.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pdf_base64": {"type": "string", "description": "Base64-encoded PDF"},
                                        "filename": {"type": "string"},
                                        "pages": {"type": "string", "description": "Seiten wie '1,3,5-7'"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Ergebnis mit Download-URL"}}
                }
            },
            "/pdf_to_images": {
                "post": {
                    "operationId": "pdf_to_images",
                    "summary": "Konvertiere PDF zu Bildern",
                    "description": "Konvertiert alle PDF-Seiten zu PNG-Bildern.",
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
                    "responses": {"200": {"description": "Liste der Bild-Download-URLs"}}
                }
            },
            "/create_text_pdf": {
                "post": {
                    "operationId": "create_text_pdf",
                    "summary": "Erstelle PDF aus Text",
                    "description": "Erstellt ein PDF aus reinem Text.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Der Text für das PDF"},
                                        "filename": {"type": "string", "default": "document.pdf"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL"}}
                }
            },
            "/upload_file": {
                "post": {
                    "operationId": "upload_file",
                    "summary": "Lade Datei hoch",
                    "description": "Speichert eine Datei und gibt Download-URL zurück. Nützlich für Dateien die von anderen Tools generiert wurden.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "content_base64": {"type": "string", "description": "Base64-encoded Datei-Inhalt"},
                                        "filename": {"type": "string"},
                                        "mime_type": {"type": "string", "default": "application/octet-stream"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Download-URL und Metadaten"}}
                }
            }
        }
    }


async def openapi_schema(request):
    return JSONResponse(get_openapi_schema(request))


async def docs(request):
    return HTMLResponse("""
    <!DOCTYPE html><html><head><title>MCP Skills Server</title>
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
    
    # Skill Endpoints
    Route("/list_skills", endpoint_list_skills),
    Route("/get_skill", endpoint_get_skill),
    Route("/search_skills", endpoint_search_skills),
    
    # Tool Endpoints (POST)
    Route("/merge_pdfs", endpoint_merge_pdfs, methods=["POST"]),
    Route("/split_pdf", endpoint_split_pdf, methods=["POST"]),
    Route("/pdf_to_images", endpoint_pdf_to_images, methods=["POST"]),
    Route("/create_text_pdf", endpoint_create_text_pdf, methods=["POST"]),
    Route("/upload_file", endpoint_upload_file, methods=["POST"]),
    
    # File Download (wird über /mcp-files/* von Traefik geroutet)
    Route("/files/{file_id}/{filename:path}", endpoint_download_file),
]

app = Starlette(routes=routes)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 MCP Skills Server v2.0.1 startet auf http://{host}:{port}")
    print(f"📁 Skills: {SKILLS_DIR}")
    print(f"📦 Files: {FILES_DIR}")
    print(f"🔗 Public URL: {PUBLIC_BASE_URL}")
    print(f"📚 Gefundene Skills: {list_available_skills()}")
    uvicorn.run(app, host=host, port=port)
