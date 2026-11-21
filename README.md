# resolv-hackathon

Hackathon workspace for reviewing buyer complaints against video evidence, order details, and product listings.

| Directory | Purpose |
| --- | --- |
| `web/` | Buyer and shop-owner interface |
| `api/` | FastAPI service for case intake and review |
| `judge/` | Python package for evidence analysis |

## Run the API

From the repository root, use a Python 3.12 virtual environment and run:

```sh
python -m pip install -r api/requirements.txt
python -m uvicorn api.main:app --reload
```

Open `http://localhost:8000/health` to check the service and `http://localhost:8000/docs` for the interactive API documentation.
