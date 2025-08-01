# Bias Scoring Service for holistic page bias scoring using Azure OpenAI

## Setup

1. Copy `.env.example` to `.env` and fill in your AOAI credentials.
2. Install dependencies:
   pip install -r requirements.txt
3. Run the server:
   uvicorn main:app --reload --host 0.0.0.0 --port 8001

## API

POST /score_page
- Request JSON: { "page_content": "...", "metadata": { ... } }
- Response JSON: { "bias_types": [...], "summary": "...", "recommendations": "..." }

The server uses AOAI to analyze the full page and returns a structured bias assessment.
