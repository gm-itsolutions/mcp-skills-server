# MCP Skills Server v2.0

Ein MCP Server der **echte Tools** mit **Download-Links** bereitstellt. Designed für die Integration mit OpenWebUI über Coolify/Traefik.

## 🆕 Was ist neu in v2.0?

| Feature | v1.0 | v2.0 |
|---------|------|------|
| Skills bereitstellen | ✅ | ✅ |
| Echte Code-Ausführung | ❌ | ✅ |
| PDF zusammenfügen | ❌ | ✅ |
| PDF splitten | ❌ | ✅ |
| PDF → Bilder | ❌ | ✅ |
| Download-Links | ❌ | ✅ |
| Nur internes Netzwerk | ❌ | ✅ |

## 🏗️ Architektur

```
                    webui.homelab-gm.com
                            │
                            ▼
                    ┌──────────────┐
                    │   Traefik    │  (Coolify)
                    └──────────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
      /mcp-files/*                   alles andere
              │                           │
              ▼                           ▼
    ┌──────────────────┐        ┌──────────────────┐
    │   MCP-Server     │◄───────│    OpenWebUI     │
    │  (nur intern!)   │  API   │                  │
    │                  │        │                  │
    │  • Skills        │        │  Tool-Calls:     │
    │  • PDF Tools     │        │  merge_pdfs()    │
    │  • File Storage  │        │  split_pdf()     │
    └──────────────────┘        └──────────────────┘
              │
        /files/{id}
              │
              ▼
    Download-Link für User:
    webui.homelab-gm.com/mcp-files/abc123/merged.pdf
```

**Wichtig:** 
- Der MCP-Server hat **keinen offenen Port** zum Internet
- Downloads laufen über Traefik → `/mcp-files/*` wird zum Server geroutet
- OpenWebUI erreicht den Server intern über `http://mcp-skills-server:8001`

## 🚀 Installation (Coolify)

### 1. Repository auf GitHub pushen

```bash
git add .
git commit -m "MCP Skills Server v2.0"
git push
```

### 2. In Coolify deployen

1. **Neues Projekt** erstellen oder bestehendes verwenden
2. **Neue Resource** → "Docker Compose" → Repository URL eingeben
3. **Environment Variables** setzen:
   ```
   PUBLIC_BASE_URL=https://webui.homelab-gm.com/mcp-files
   ```
4. **Netzwerk prüfen**: Der Container muss im `coolify` Netzwerk sein (passiert automatisch durch docker-compose.yml)
5. **Deploy** klicken

### 3. OpenWebUI konfigurieren

In OpenWebUI → Admin → Settings → Tools:

| Feld | Wert |
|------|------|
| Name | `MCP Skills Server` |
| URL | `http://mcp-skills-server:8001` |
| Type | `OpenAPI` |

**Hinweis:** Die URL ist die **interne** Docker-Netzwerk-URL, nicht die öffentliche!

## 📦 Verfügbare Tools

### Skill-Tools (wie bisher)

| Tool | Beschreibung |
|------|--------------|
| `list_skills` | Zeigt alle verfügbaren Skills |
| `get_skill` | Holt einen bestimmten Skill |
| `search_skills` | Durchsucht Skills |

### PDF-Tools (NEU!)

| Tool | Beschreibung |
|------|--------------|
| `merge_pdfs` | Fügt mehrere PDFs zusammen |
| `split_pdf` | Extrahiert bestimmte Seiten |
| `pdf_to_images` | Konvertiert PDF-Seiten zu PNG |
| `create_text_pdf` | Erstellt PDF aus Text |
| `upload_file` | Speichert beliebige Dateien |

## 💬 Beispiel-Nutzung in OpenWebUI

**User:**
> Füge diese 3 PDFs zusammen

**LLM:**
1. Ruft `merge_pdfs` Tool auf mit den base64-codierten PDFs
2. Server fügt PDFs zusammen
3. Server speichert Ergebnis mit UUID
4. Server gibt Download-URL zurück

**LLM antwortet:**
> Ich habe die PDFs zusammengefügt. Hier ist der Download-Link:
> https://webui.homelab-gm.com/mcp-files/abc123/merged.pdf

## 🔧 Lokale Entwicklung

```bash
# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate

# Dependencies installieren
pip install -r requirements.txt

# Server starten
python src/server.py
```

Dann http://localhost:8001/docs öffnen für die API-Dokumentation.

## 📁 Projektstruktur

```
mcp-skills-server/
├── docker-compose.yml      # Coolify Deployment mit Traefik-Labels
├── Dockerfile              # Container-Build
├── requirements.txt        # Python Dependencies
├── src/
│   └── server.py          # Haupt-Server mit Tools
├── skills-data/           # Skill-Definitionen
│   ├── writing/
│   ├── code-review/
│   ├── pdf/
│   └── ...
├── .env.example           # Environment Template
└── README.md
```

## ⚠️ Wichtige Hinweise

### Download-Links laufen ab

Generierte Dateien werden nach **24 Stunden** automatisch gelöscht. Dies verhindert, dass der Speicher vollläuft.

### Base64-Encoding

Die PDF-Tools erwarten Dateien als Base64-String. Das LLM muss die hochgeladenen Dateien entsprechend kodieren. Bei großen Dateien kann dies zu Performance-Problemen führen.

### Traefik Strip-Prefix

Die Traefik-Middleware entfernt `/mcp-files` aus dem Pfad bevor die Anfrage zum Server geht:
- Öffentlich: `webui.homelab-gm.com/mcp-files/abc123/file.pdf`
- Intern wird: `/files/abc123/file.pdf`

## 🔒 Sicherheit

- Server ist **nicht direkt aus dem Internet erreichbar**
- Nur Traefik kann den Server über das interne Netzwerk erreichen
- Download-Links sind nur 24h gültig
- UUIDs sind nicht erratbar

## 📝 Lizenz

MIT
