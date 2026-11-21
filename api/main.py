from fastapi import FastAPI


app = FastAPI(title="Case review API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
