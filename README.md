# linuxfirst-azuredocs-enforcer

## Overview

This project crawls websites, extracts code snippets, and scores them using heuristics and LLMs to flag items of interest.

## Directory Structure

- `crawler/`: Async site crawler and HTML fetcher
- `extractor/`: HTML parsing and snippet extraction
- `scorer/`: Pre-filtering and LLM-based scoring
- `results/`: Output JSON or CSV files

## Setup

1. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```

## Usage

Run the orchestrator to start the pipeline:
```sh
python orchestrator.py
```

## Extending

- Add new extractors or scoring logic in their respective modules.
- Integrate with other LLM providers by extending `scorer/llm_client.py`.
