# BIS Intelligent Assistant (SIH26107)

LangGraph + FastAPI + Chroma + Groq agent answering questions about Indian Standards, BIS certification schemes (ISI/Scheme I, CRS/Scheme II, FMCS, Hallmarking, MSCS), lab recognition, and Standards Clubs — with cited sources and product→standard reasoning.

## Demo Queries (locked — corpus covers these)
1. `standard_lookup`: "What is IS 2347 and which products does it cover?"
2. `standard_lookup`: "What does IS 4151 specify for helmets?"
3. `product_to_standard`: "I manufacture stainless steel pressure cookers — which BIS standard and scheme applies?"
4. `product_to_standard`: "I want to sell LED bulbs in India — do I need CRS or ISI?"
5. `scheme_process`: "What is the process for CRS (Scheme II) registration?"
6. `lab_query`: "How does a lab get BIS recognition under LRS 2018?"

## Quickstart
```bash
# Pick ONE depending on where you run from:

# From INSIDE bis-assistant (you are at C:\sih2026\bis-assistant):
uvicorn api.main:app --reload --port 8000
#  ^ no --app-dir when already inside. Using --app-dir here causes ModuleNotFoundError: No module named 'api'

# From REPO ROOT (you are at C:\sih2026):
uvicorn api.main:app --app-dir bis-assistant --reload --port 8000

# Either also works via launcher:
python run.py              # from C:\sih2026
python ../run.py           # from C:\sih2026\bis-assistant
```

### Setup (first time)
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt              # if inside bis-assistant
# or: pip install -r bis-assistant/requirements.txt  # if at repo root
copy .env.example .env  # fill GROQ_API_KEY
python -m ingestion.fetch_and_chunk  # fetch corpus -> Chroma (already seeded: 97 docs)
python -m ingestion.seed_synthetic   # synthetic ground-truth for 6 demo queries
```

### Frontend (TypeScript dashboard)
```bash
cd frontend
npm install
npm run build   # outputs to frontend/dist — FastAPI serves it at /
npm run dev     # Vite dev at :5173 proxies /health + /query to :8000
```

Endpoints:
- `POST /query` -> `{answer, citations, query_type, used_live_fallback}`
- `GET /health`
- `GET /` serves single-file chat UI

## Tech
- Groq `openai/gpt-oss-120b` (synthesize) / `openai/gpt-oss-20b` (router) — no deprecated Llama models
- Chroma local, `bge-base-en-v1.5` embeddings
- Tavily scoped to `bis.gov.in`, DuckDuckGo fallback

## Tests
```bash
pytest -q
# Skip live adversarial tests by default (marked integration):
pytest -q -m "not integration"
# Run live adversarial suite (requires GROQ_API_KEY, burns credits):
pytest -o "addopts=" -m integration -v
```

## Debug logging
Set `DEBUG_VERBOSE=true` in `.env` to print full retrieval scores, prompts, and raw model output to the terminal for debugging. Default is `false` (quiet). This prints only to the terminal running `uvicorn` — it does **not** leak into the API response body or the judge-facing UI.
```bash
# .env
DEBUG_VERBOSE=true
uvicorn api.main:app --reload --port 8000  # or: uvicorn api.main:app --app-dir bis-assistant --port 8000
```
