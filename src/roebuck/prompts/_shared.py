from roebuck.config import ContextConfig


def build_context_section(context: ContextConfig) -> str:
    """Build a Markdown Project Context block from the given ContextConfig.

    Args:
        context (ContextConfig): project context configuration

    Returns:
        str: Markdown-formatted context section, always including the header
    """
    lines = ["## Project Context"]
    if context.team:
        lines.append(f"- **Team**: {context.team}")
    if context.phase:
        lines.append(f"- **Development phase**: {context.phase}")
    if context.notes:
        lines.append(f"- **Notes**: {context.notes}")
    return "\n".join(lines)
