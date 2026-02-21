# MangaFlow

**MangaFlow** è un'applicazione desktop moderna e veloce per cercare, leggere e scaricare manga dai tuoi siti preferiti (attualmente integrato **MangaWorld**).  
L'interfaccia grafica è realizzata in Python utilizzando `CustomTkinter` per un look pulito e responsivo.

Disponibile sia per Windows che per MacOS.

## 🚀 Funzionalità Principali

*   **🔍 Ricerca Multithread**: Cerca istantaneamente tra migliaia di titoli disponibili.
*   **📖 Lettore Integrato**: Leggi i capitoli direttamente nell'app con zoom, navigazione fluida e modalità full-screen.
*   **💾 Download Smart**: Scarica capitoli in formato **EPUB** (ottimizzato per Kindle/eReader) o **PDF**.
    *   Opzione per unire più capitoli in un unico volume.
    *   Suddivisione automatica per dimensione file sopra i 200mb per usufruire del servizio di "sendtokindle".
*   **⭐ Gestione Preferiti**: Salva i tuoi manga preferiti, traccia automaticamente i capitoli letti e riprendi la lettura da dove avevi lasciato.
*   **⚡ Modalità Offline**: Sfoglia la cache dei capitoli scaricati/visualizzati anche senza connessione.

---

## 🛠️ Installazione e Avvio (Sorgente Python)

Se vuoi modificare il codice o eseguire l'applicazione tramite Python, segui questi passaggi.

### Prerequisiti
*   [Python 3.10](https://www.python.org/downloads/) o superiore.

### Come avviare

1.  **Clona la repository** (o scarica lo zip):
    ```bash
    git clone https://github.com/Larus54/MangaFlow.git
    cd MangaFlow
    ```

2.  **Crea un ambiente virtuale** (raccomandato):
    *   *Windows*: `python -m venv .venv` poi `.venv\Scripts\activate`
    *   *macOS/Linux*: `python3 -m venv .venv` poi `source .venv/bin/activate`

3.  **Installa le dipendenze**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Avvia l'applicazione**:
    ```bash
    python mangascraper.py
    ```

---

## 📦 Download Eseguibile (Windows & macOS)

Puoi scaricare l'ultima versione pre-compilata direttamente dalla pagina delle **Releases** di questa repository.

*   **Windows**: Scarica il file `.exe`.
*   **macOS**: Scarica l'archivio `.zip` (estrai il contenuto per ottenere l'app).

👉 **[Vai alla pagina Releases](../../releases)**

---

## 🛠️ Build Manuale (Opzionale)

Se preferisci compilare l'app autonomamente partendo dal codice sorgente:

### Windows (Comando)

```powershell
pyinstaller --noconfirm --clean --onefile --name "Manga Scraper" --windowed --add-data "assets;assets" --icon "assets/logo.png" mangascraper.py
```

### macOS (Comando)
```bash
pyinstaller --noconfirm --clean --name "Manga Scraper" --windowed --add-data "assets:assets" --icon "assets/logo.png" mangascraper.py
```
*Troverai l'applicazione `Manga Scraper.app` nella cartella `dist/`. Per distribuirla, si consiglia di comprimerla in un file `.zip`.*

> **Nota:** Su macOS, il separatore per `--add-data` è i due punti (`:`) invece del punto e virgola (`;`) usato su Windows.

---

## 🔮 Sviluppi Futuri (Roadmap)

 Ecco cosa arriverà presto nei prossimi aggiornamenti:

*   [ ] **Performance e Ottimizzazione (Windows)**: Migliorare l'ottimizzazione e le performance dell'app, non ancora ottimali per Windows
*   [ ] **Nuovi Provider**: Aggiunta di supporto per altri siti (es. Mangadex, ecc.).
*   [ ] **Miglioramenti Reader**: Modalità "striscia continua" (webtoon style) e doppia pagina.
*   [ ] **Sync Cloud**: Integrazione con MyAnimeList/Anilist per sincronizzare i progressi.
*   [ ] **Impostazioni Avanzate**: Temi personalizzabili e gestione cartelle di download.
*   [ ] **Sezione Anime**: Implementare oltre ad una sezione manga, anche una sezione anime, con interfaccia dedicata e videoplayer integrato. Con le stesse funzionalità della sezione manga.

---
## 📜 Changelog

### v1.0.2 (21/02/2026)
*   **Capitoli**: Raggruppati per volumi quando disponibili (sidebar e popup lettura/download).
*   **Download**: Selezione nel popup tra modalità **Capitoli** o **Volumi** per scaricare solo ciò che serve.
*   **Volumi**: Aggiunto supporto alle copertine dei volumi (EPUB per volume usa la cover corretta).
*   **Download**: Nuova opzione per separare i file finali per volume quando si uniscono i capitoli.

### v1.0.1 (16/02/2026)
*   **Download**: Corretto l'ordine di salvataggio dei capitoli nei file EPUB/PDF (dal più vecchio al più recente).

### v1.0.0 (12/01/2026) 🎉
*   **Primo Rilascio Pubblico**: L'applicazione è ora stabile e disponibile per Windows e macOS.
*   **Provider**: Supporto completo per *MangaWorld*.
*   **Download**: Aggiunta conversione automatica in EPUB (ottimizzato Kindle) e PDF.
*   **UI/UX**: Interfaccia grafica completa con modalità scura/chiara automatica, zoom reader e navigazione fluida.
*   **Sistema**: Implementata gestione cache locale e salvataggio automatico dei preferiti.

---

Versione app: 1.0.2 (21/02/2026)

Versione README: 0.4 (21/02/2026)
