"""Hugging Face — model health monitoring and inference gateway."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)
HF_API = "https://huggingface.co/api"
HF_INFERENCE = "https://api-inference.huggingface.co/models"


def _headers():
    return {"Authorization": f"Bearer {Config.HF_TOKEN}"}


def get_model_info(repo_id: str = None) -> dict:
    """Fetch model metadata from HuggingFace hub."""
    repo = repo_id or Config.HF_MODEL_REPO
    r = httpx.get(f"{HF_API}/models/{repo}", headers=_headers())
    r.raise_for_status()
    info = r.json()
    logger.info(f"HF model info fetched: {repo} — downloads={info.get('downloads', 0)}")
    return info


def run_inference(inputs: str | list, repo_id: str = None,
                  parameters: dict = None) -> dict:
    """Run inference against a HuggingFace hosted model."""
    repo = repo_id or Config.HF_MODEL_REPO
    payload = {"inputs": inputs}
    if parameters:
        payload["parameters"] = parameters
    r = httpx.post(
        f"{HF_INFERENCE}/{repo}",
        json=payload,
        headers=_headers(),
        timeout=60.0
    )
    r.raise_for_status()
    result = r.json()
    logger.info(f"HF inference complete: {repo}")
    return result


def check_endpoint_health(endpoint_url: str) -> dict:
    """Ping a HuggingFace Inference Endpoint for health status."""
    r = httpx.get(
        f"{endpoint_url}/health",
        headers=_headers(),
        timeout=10.0
    )
    status = "healthy" if r.status_code == 200 else "unhealthy"
    logger.info(f"HF endpoint health: {endpoint_url} → {status}")
    return {"url": endpoint_url, "status": status, "code": r.status_code}


def list_models(author: str = None) -> list[dict]:
    """List models for a given author/org on HuggingFace Hub."""
    author = author or Config.HF_MODEL_REPO.split("/")[0]
    r = httpx.get(f"{HF_API}/models?author={author}&full=true", headers=_headers())
    r.raise_for_status()
    models = r.json()
    logger.info(f"HF models listed for {author}: {len(models)} found")
    return models
