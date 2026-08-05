# Installation

## Requirements

- Python 3.11+ (developed on 3.13)
- git

## 1. Clone the repository

```bash
git clone https://github.com/Kanga2050/Research_Gap_Identification.git
cd Research_Gap_Identification
```

## 2. Install Python dependencies

Using a virtual environment is recommended but not required:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## 3. Download the spaCy English model

```bash
python -m spacy download en_core_web_sm
```

## 4. Start the server

```bash
python App/Servers/Server.py
```

The app is now running at [http://127.0.0.1:8000](http://127.0.0.1:8000).

`SECRET_KEY` and the field-encryption key are created the first time
`settings.py` is imported (i.e. the first time you run the command above)
and reused on every subsequent run, so restarting the server doesn't
invalidate existing sessions or encrypted data.

## Optional configuration

None of the following are required to run the app — they only matter if
you're deploying somewhere other than your own machine:

| Variable | Purpose | Default |
|---|---|---|
| `DJANGO_DEBUG` | Enable Django's debug mode (verbose error pages) | `0` (off) |
| `DJANGO_SECRET_KEY` | Override the auto-generated Django secret key | auto-generated |
| `DJANGO_FIELD_ENCRYPTION_KEY` | Override the auto-generated field-encryption key | auto-generated |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts Django will serve | `127.0.0.1,localhost,testserver` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins allowed to make credentialed cross-origin requests | none (CORS disabled) |
| `SERVER_HOST` | Host the FastAPI/Django server binds to | `127.0.0.1` |
| `SERVER_PORT` | Port the server listens on | `8000` |
