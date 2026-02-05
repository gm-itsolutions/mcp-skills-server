# Code Review Skill

Dieser Skill enthält Anweisungen für effektive Code Reviews und Code-Qualitätsprüfungen.

## Review-Prozess

### 1. Überblick verschaffen
- Lies zuerst die PR/MR Beschreibung
- Verstehe das Ziel der Änderung
- Prüfe den Umfang (zu groß? aufteilen?)

### 2. Architektur-Review
- Passt die Lösung zur bestehenden Architektur?
- Gibt es bessere Patterns für diesen Use Case?
- Sind die Abhängigkeiten sinnvoll?

### 3. Code-Qualität
- Ist der Code lesbar und verständlich?
- Sind Variablen- und Funktionsnamen aussagekräftig?
- Gibt es Duplikate die extrahiert werden könnten?

### 4. Fehlerbehandlung
- Werden Edge Cases behandelt?
- Gibt es sinnvolles Error Handling?
- Sind Fehlermeldungen hilfreich?

### 5. Tests
- Sind ausreichend Tests vorhanden?
- Decken die Tests die wichtigen Pfade ab?
- Sind die Tests lesbar und wartbar?

## Checkliste für Reviews

### Funktionalität
- [ ] Code erfüllt die Anforderungen
- [ ] Edge Cases sind behandelt
- [ ] Keine offensichtlichen Bugs

### Code-Qualität
- [ ] Code ist lesbar und selbsterklärend
- [ ] Keine unnötige Komplexität
- [ ] DRY-Prinzip beachtet
- [ ] Konsistenter Stil

### Sicherheit
- [ ] Keine hardcodierten Secrets
- [ ] Input wird validiert
- [ ] SQL Injection / XSS vermieden
- [ ] Authentifizierung/Autorisierung korrekt

### Performance
- [ ] Keine N+1 Queries
- [ ] Große Operationen sind optimiert
- [ ] Caching wo sinnvoll

### Dokumentation
- [ ] Komplexe Logik ist kommentiert
- [ ] API-Änderungen dokumentiert
- [ ] README aktualisiert (wenn nötig)

## Feedback geben

### DO ✅
- Sei konstruktiv und respektvoll
- Erkläre das "Warum" hinter Vorschlägen
- Biete Alternativen an
- Lobe guten Code
- Frage bei Unklarheiten nach

### DON'T ❌
- Persönlich werden
- Nur kritisieren ohne Lösung
- Stilfragen zu stark gewichten
- Perfektionismus über Pragmatismus stellen

## Formulierungen

| Statt | Besser |
|-------|--------|
| "Das ist falsch" | "Hast du bedacht, dass...?" |
| "Mach es so" | "Was hältst du von...?" |
| "Das verstehe ich nicht" | "Kannst du erklären, warum...?" |
| "Das muss geändert werden" | "Ich würde vorschlagen..." |
