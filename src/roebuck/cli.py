from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from roebuck.config import load_config, AppConfig

app = typer.Typer(
    name="roebuck",
    help="GitHub repository analysis tool powered by Claude.",
    no_args_is_help=True,
)
analyse_app = typer.Typer(help="Analyse a specific repository artefact.", no_args_is_help=True)
report_app = typer.Typer(help="Generate aggregate reports.", no_args_is_help=True)
profile_app = typer.Typer(help="Manage the project profile.", no_args_is_help=True)

app.add_typer(analyse_app, name="analyse")
app.add_typer(report_app, name="report")
app.add_typer(profile_app, name="profile")

console = Console()

_CONFIG_OPT = typer.Option(
    Path("config.toml"),
    "--config", "-c",
    help="Path to config.toml",
    show_default=True,
)

_REPO_OPT = typer.Option(
    None,
    "--repo", "-r",
    help="GitHub repository to analyse in owner/repo-name format (overrides config.toml)",
)


# ---------------------------------------------------------------------------
# analyse pr
# ---------------------------------------------------------------------------

@analyse_app.command("pr")
def analyse_pr(
    number: int = typer.Argument(..., help="Pull request number"),
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
) -> None:
    """Analyse a pull request: spec alignment, risk assessment, test adequacy."""
    cfg = _load(config_path, repo)
    from roebuck.analysers import pr as pr_analyser
    with console.status(f"[bold]Analysing PR #{number}…[/bold]"):
        report_path = pr_analyser.run(number, cfg)
    console.print(f"[green]Report written:[/green] {report_path}")


# ---------------------------------------------------------------------------
# analyse file
# ---------------------------------------------------------------------------

@analyse_app.command("file")
def analyse_file(
    path: str = typer.Argument(..., help="File path relative to repo root"),
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
) -> None:
    """Analyse the commit history of a file: evolution, risk areas, stability trend."""
    cfg = _load(config_path, repo)
    from roebuck.analysers import file_history as fh_analyser
    with console.status(f"[bold]Analysing file history for {path}…[/bold]"):
        report_path = fh_analyser.run(path, cfg)
    console.print(f"[green]Report written:[/green] {report_path}")


# ---------------------------------------------------------------------------
# analyse release
# ---------------------------------------------------------------------------

@analyse_app.command("release")
def analyse_release(
    tag: str = typer.Argument(..., help="Release tag to analyse"),
    base: str = typer.Option(None, "--base", "-b", help="Base tag/ref to compare against (defaults to previous tag)"),
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
) -> None:
    """Analyse changes introduced by a release tag."""
    cfg = _load(config_path, repo)
    from roebuck.analysers import release as release_analyser
    with console.status(f"[bold]Analysing release {tag}…[/bold]"):
        report_path = release_analyser.run(tag, base, cfg)
    console.print(f"[green]Report written:[/green] {report_path}")


# ---------------------------------------------------------------------------
# report churn
# ---------------------------------------------------------------------------

@report_app.command("churn")
def report_churn(
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
) -> None:
    """Generate a churn and defect correlation report for the repository."""
    cfg = _load(config_path, repo)
    from roebuck.analysers import churn as churn_analyser
    with console.status(
        f"[bold]Collecting churn data (last {cfg.churn.lookback_days} days)…[/bold]"
    ):
        report_path = churn_analyser.run(cfg)
    console.print(f"[green]Report written:[/green] {report_path}")


# ---------------------------------------------------------------------------
# profile capture
# ---------------------------------------------------------------------------

@profile_app.command("capture")
def profile_capture(
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing profile.json"),
) -> None:
    """Extract the project profile and write it to .roebuck/profile.json."""
    cfg = _load(config_path, repo)
    from roebuck.analysers.profile import capture
    with console.status("[bold]Capturing project profile...[/bold]"):
        result = capture(cfg, force=force)
    if result is not None:
        console.print(f"[green]Profile written:[/green] {result}")


# ---------------------------------------------------------------------------
# profile generate-docs
# ---------------------------------------------------------------------------

@profile_app.command("generate-docs")
def profile_generate_docs(
    config_path: Path = _CONFIG_OPT,
    repo: Optional[str] = _REPO_OPT,
) -> None:
    """Render the stored project profile as a Markdown draft document."""
    cfg = _load(config_path, repo)
    from roebuck.analysers.profile import generate_docs
    try:
        with console.status("[bold]Generating project profile document...[/bold]"):
            out = generate_docs(cfg)
        console.print(f"[green]Document written:[/green] {out}")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(config_path: Path, repo: Optional[str] = None) -> AppConfig:
    try:
        cfg = load_config(config_path)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=1)

    if repo:
        try:
            cfg = cfg.model_copy(update={"github": cfg.github.model_copy(update={"repo": repo})})
        except Exception as e:
            console.print(f"[red]Invalid --repo value:[/red] {e}")
            raise typer.Exit(code=1)

    return cfg


def main() -> None:
    app()
