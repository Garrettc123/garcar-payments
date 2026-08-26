"""Linear — auto-create onboarding projects and tasks on every sale."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)
LINEAR_API = "https://api.linear.app/graphql"


def _gql(query: str, variables: dict = None) -> dict:
    r = httpx.post(
        LINEAR_API,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": Config.LINEAR_API_KEY, "Content-Type": "application/json"}
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Linear GraphQL error: {data['errors']}")
    return data["data"]


def create_onboarding_project(client_name: str, email: str,
                               product: str, tenant_id: str) -> str:
    """Create a Linear project for client onboarding. Returns project ID."""
    mutation = """
    mutation CreateProject($input: ProjectCreateInput!) {
      projectCreate(input: $input) {
        success
        project { id name }
      }
    }
    """
    variables = {
        "input": {
            "name": f"[ONBOARDING] {client_name} — {product}",
            "description": f"Tenant: {tenant_id}\nEmail: {email}\nProduct: {product}",
            "teamIds": [Config.LINEAR_TEAM_ID],
            "status": "started"
        }
    }
    data = _gql(mutation, variables)
    project_id = data["projectCreate"]["project"]["id"]
    logger.info(f"Linear project created: {project_id} — {client_name}")

    # Create standard onboarding tasks
    _create_onboarding_tasks(project_id, client_name, email, product)
    return project_id


def _create_onboarding_tasks(project_id: str, client_name: str,
                              email: str, product: str):
    """Create standard onboarding checklist tasks."""
    tasks = [
        f"Send welcome email to {email}",
        f"Provision {product} tenant environment",
        "Schedule kickoff call (Calendly link)",
        "Share onboarding Notion workspace",
        "Verify DocuSign contract signed",
        "Enable Stripe billing portal access",
        "Complete 30-day check-in"
    ]
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) { success issue { id } }
    }
    """
    for title in tasks:
        variables = {
            "input": {
                "title": title,
                "teamId": Config.LINEAR_TEAM_ID,
                "projectId": project_id,
                "priority": 2
            }
        }
        _gql(mutation, variables)
    logger.info(f"Linear onboarding tasks created for project {project_id}")


def create_issue(title: str, description: str = "", priority: int = 3) -> str:
    """Create a standalone Linear issue. Returns issue ID."""
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) { success issue { id identifier } }
    }
    """
    data = _gql(mutation, {"input": {
        "title": title,
        "description": description,
        "teamId": Config.LINEAR_TEAM_ID,
        "priority": priority
    }})
    issue_id = data["issueCreate"]["issue"]["id"]
    logger.info(f"Linear issue created: {issue_id} — {title}")
    return issue_id
