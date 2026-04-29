from __future__ import annotations

import os


def query_backlog(question: str, backlog_text: str, scores_text: str) -> str:
    try:
        import anthropic
    except ImportError:
        return "query tool requires the anthropic package: pip install 'backlog-mcp[agent]'"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "query tool requires ANTHROPIC_API_KEY to be set"

    model = os.environ.get("BACKLOG_AGENT_MODEL", "claude-sonnet-4-6")

    system = (
        "You are a backlog analyst. Answer questions about the project backlog concisely "
        "and precisely. Cite item IDs when relevant.\n\n"
        f"## Backlog\n\n{backlog_text}"
    )
    if scores_text.strip():
        system += f"\n\n## Scores\n\n{scores_text}"

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": question}],
        max_tokens=1024,
    )
    return response.content[0].text
