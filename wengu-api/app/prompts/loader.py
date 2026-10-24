"""Load versioned prompts from Markdown; the repository files are the source of truth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

_TOKEN_PATTERN = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


class PromptError(RuntimeError):
    """Raised when a prompt file is missing or malformed."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    path: Path
    template: str

    def render(self, **values: str) -> str:
        def substitute(match: re.Match[str]) -> str:
            token = match.group(1)
            if token not in values:
                raise PromptError(f"prompt {self.id}@{self.version} is missing token {token}")
            return values[token]

        return _TOKEN_PATTERN.sub(substitute, self.template)


def _parse_prompt(path: Path) -> Prompt:
    post = frontmatter.load(path)
    prompt_id = post.get("id")
    version = post.get("version")
    template = post.content.strip()

    if not isinstance(prompt_id, str) or not prompt_id.strip():
        raise PromptError(f"{path.name}: frontmatter 'id' is required")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PromptError(f"{path.name}: frontmatter 'version' must be a positive integer")
    if not template:
        raise PromptError(f"{path.name}: prompt body is empty")

    return Prompt(id=prompt_id.strip(), version=version, path=path, template=template)


def load_prompts(directory: str | Path) -> dict[str, Prompt]:
    """Load every *.md prompt once; duplicates or malformed files fail fast at startup."""

    prompt_dir = Path(directory)
    if not prompt_dir.is_dir():
        raise PromptError(f"prompt directory not found: {prompt_dir}")

    prompts: dict[str, Prompt] = {}
    for path in sorted(prompt_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        prompt = _parse_prompt(path)
        if prompt.id in prompts:
            raise PromptError(
                f"duplicate prompt id {prompt.id}: {prompts[prompt.id].path.name} and {path.name}"
            )
        prompts[prompt.id] = prompt
    return prompts
