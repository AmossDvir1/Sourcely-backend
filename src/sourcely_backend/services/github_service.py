import base64
import httpx
import re
from typing import Set, Dict, Tuple, Optional
from ..core.config import settings

# --- Constants for Filtering ---

# A set of common source code and configuration file extensions.
SOURCE_CODE_EXTENSIONS: Set[str] = {
    ".py", ".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".java", ".kt", ".scala", ".go", ".rs", ".swift",
    ".rb", ".php", ".sh", ".bash", ".ps1", ".json", ".xml", ".yaml",
    ".yml", ".toml", ".sql", ".md", ".txt", "Dockerfile", "docker-compose.yml"
}

# A set of directory names to completely ignore.
IGNORED_DIRS: Set[str] = {
    "__pycache__", ".git", ".idea", ".vscode", "node_modules",
    "venv", ".venv", "dist", "build", "target", "out", "bin"
}

# A set of specific, large filenames to ignore.
IGNORED_FILES: Set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "Gemfile.lock", "Pipfile.lock", "poetry.lock"
}

# A size limit (e.g., 1MB) to avoid fetching huge binary files by mistake.
MAX_FILE_SIZE_BYTES: int = 1024 * 1024


def _parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a GitHub URL to extract the owner and repo name using regex.
    Handles various URL formats (e.g., with/without .git, www, etc.).
    """
    # Regex to capture owner and repo from various GitHub URL formats
    pattern = re.compile(r"github\.com/([^/]+)/([^/.\s]+)")
    match = pattern.search(url)
    if match:
        owner, repo = match.groups()
        # Remove a trailing '.git' if it exists
        if repo.endswith('.git'):
            repo = repo[:-4]
        return owner, repo
    return None


async def _fetch_file_content(client: httpx.AsyncClient, download_url: str) -> Optional[str]:
    """Fetches the text content of a single file from its download URL."""
    try:
        response = await client.get(download_url)
        # We only care about successful responses
        if response.status_code == 200:
            # We assume the content is decodable as utf-8.
            # For robustness, one could add more complex encoding detection.
            return response.text
    except httpx.RequestError as e:
        print(f"Error fetching file content from {download_url}: {e}")
    return None


async def _get_repo_tree_recursive(
        client: httpx.AsyncClient,
        owner: str,
        repo: str
) -> list:
    """
    Fetches the entire file tree for the repository using the recursive Git Trees API.
    This is much more efficient than fetching directory contents one by one.
    """
    # 1. Get the SHA of the latest commit on the default branch
    main_branch_url = f"https://api.github.com/repos/{owner}/{repo}"
    branch_response = await client.get(main_branch_url)
    branch_response.raise_for_status()  # Will raise for 4xx/5xx errors
    default_branch = branch_response.json().get("default_branch", "main")

    branch_details_url = f"https://api.github.com/repos/{owner}/{repo}/branches/{default_branch}"
    details_response = await client.get(branch_details_url)
    details_response.raise_for_status()
    commit_sha = details_response.json()["commit"]["sha"]

    # 2. Use the commit SHA to get the entire file tree in one recursive call
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
    tree_response = await client.get(tree_url)
    tree_response.raise_for_status()

    return tree_response.json().get("tree", [])


async def get_repo_contents_from_url(github_url: str) -> Dict[str, str]:
    """
    Fetches and filters the contents of a public GitHub repository.

    This function orchestrates the process:
    1. Parses the URL.
    2. Fetches the entire repository file tree.
    3. Filters the tree for relevant source code files.
    4. Fetches the content for each valid file.
    5. Returns a dictionary mapping {file_path: content}.
    """
    owner_repo = _parse_github_url(github_url)
    if not owner_repo:
        raise ValueError("Invalid GitHub URL format. Could not parse owner and repository.")

    owner, repo = owner_repo
    repo_files_with_content: Dict[str, str] = {}

    headers = {
        "Accept": "application/vnd.github.v3+json",
        # This tells GitHub who you are and grants you the higher rate limit.
        "Authorization": f"Bearer {settings.GITHUB_ACCESS_TOKEN}"
    }


    async with httpx.AsyncClient(headers=headers) as client:
        try:
            tree = await _get_repo_tree_recursive(client, owner, repo)

            for item in tree:
                # We only care about files ('blobs')
                if item.get("type") != "blob":
                    continue

                path = item.get("path", "")

                # --- Apply Filtering Logic ---
                if any(ignored in path.split('/') for ignored in IGNORED_DIRS):
                    continue

                filename = path.split('/')[-1]
                if filename in IGNORED_FILES:
                    continue

                if not any(path.endswith(ext) for ext in SOURCE_CODE_EXTENSIONS):
                    if filename not in SOURCE_CODE_EXTENSIONS:  # For files like 'Dockerfile'
                        continue

                if item.get("size", 0) > MAX_FILE_SIZE_BYTES:
                    continue
                # --- End Filtering ---

                # If the file passes all checks, fetch its content
                content_url = item.get("url")
                if content_url:
                    # The client already has the auth headers, so this call is authenticated.
                    blob_response = await client.get(content_url)
                    if blob_response.status_code == 200:
                        blob_data = blob_response.json()
                        if blob_data.get("encoding") == "base64":
                            file_content = base64.b64decode(blob_data["content"]).decode('utf-8', 'ignore')
                            repo_files_with_content[path] = file_content

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                # print(f"x-ratelimit-reset status: {e.response.headers.get("x-ratelimit-reset")}")

                # The message will now likely be about a bad token instead of a rate limit
                print(
                    f"GitHub API 403 Forbidden. Check if your GITHUB_ACCESS_TOKEN is valid and has `public_repo` scope. Error: {e}")
                raise Exception("Failed to authenticate with GitHub. Please check server configuration.")
            elif e.response.status_code == 404:
                raise ValueError(
                    f"Repository not found at '{github_url}'. Please check if the URL is correct and the repository is public.")
            else:
                print(f"A GitHub API error occurred: {e}")
                raise Exception("Failed to retrieve repository data from GitHub.")
        except Exception as e:
            print(f"An unexpected error occurred in get_repo_contents_from_url: {e}")
            raise Exception("An unexpected error occurred while processing the repository.")

    return repo_files_with_content
