"""
Central place for the app's version number and GitHub repo info.

Bump APP_VERSION here whenever you cut a new release / tag on GitHub.
The update checker compares this value against the latest GitHub release tag.
"""

APP_NAME = "Reportix"
APP_VERSION = "1.2.1"

GITHUB_OWNER = "Abdulaziz-hu"
GITHUB_REPO_NAME = "Reportix"

GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_RELEASES_URL = f"{GITHUB_REPO_URL}/releases/latest"
GITHUB_ISSUES_URL = f"{GITHUB_REPO_URL}/issues"
GITHUB_ISSUES_NEW_URL = f"{GITHUB_REPO_URL}/issues/new/choose"
GITHUB_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
)
