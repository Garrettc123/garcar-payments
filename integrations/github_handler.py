"""GitHub — repo events, issue creation, and deployment triggers."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)
GH_API = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"token {Config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def create_issue(repo: str, title: str, body: str = "", labels: list = None) -> dict:
    """Create a GitHub issue."""
    payload = {"title": title, "body": body, "labels": labels or []}
    r = httpx.post(
        f"{GH_API}/repos/{Config.GITHUB_ORG}/{repo}/issues",
        json=payload, headers=_headers()
    )
    r.raise_for_status()
    issue = r.json()
    logger.info(f"GitHub issue created: {repo}#{issue['number']} — {title}")
    return issue


def trigger_workflow(repo: str, workflow_id: str, ref: str = "main",
                     inputs: dict = None) -> bool:
    """Trigger a GitHub Actions workflow dispatch."""
    payload = {"ref": ref, "inputs": inputs or {}}
    r = httpx.post(
        f"{GH_API}/repos/{Config.GITHUB_ORG}/{repo}/actions/workflows/{workflow_id}/dispatches",
        json=payload, headers=_headers()
    )
    success = r.status_code == 204
    logger.info(f"Workflow dispatch: {repo}/{workflow_id} → {'OK' if success else r.text}")
    return success


def get_open_issues(repo: str) -> list[dict]:
    """List all open issues in a repo."""
    r = httpx.get(
        f"{GH_API}/repos/{Config.GITHUB_ORG}/{repo}/issues?state=open&per_page=100",
        headers=_headers()
    )
    r.raise_for_status()
    return r.json()
