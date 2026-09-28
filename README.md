# Dark Pattern Audit Agent 🕵️

An AI-powered tool that audits websites for dark UX patterns using Hindsight (browser automation) and Groq (LLM analysis).

## Project Structure

```
darkpattern-audit/
├── backend/           # FastAPI app
│   ├── main.py        # API entrypoint (3 placeholder endpoints)
│   ├── requirements.txt
│   └── .env           # API keys (never committed)
├── frontend/          # React + Vite app
├── sample_sites/      # Local HTML pages for testing
└── .gitignore
```

## Getting Started

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
uvicorn main:app --reload
```

API docs available at http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at http://localhost:5173

## API Endpoints (Placeholder)

| Method | Path       | Description                          |
|--------|------------|--------------------------------------|
| POST   | `/audit`   | Audit a URL for dark patterns        |
| POST   | `/review`  | Request an AI review of an audit     |
| GET    | `/history` | List past audits                     |

## Environment Variables

Fill in `backend/.env`:

```
GROQ_API_KEY=your_groq_key_here
HINDSIGHT_API_KEY=your_hindsight_key_here
```
