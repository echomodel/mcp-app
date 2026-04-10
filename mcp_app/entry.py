"""Zero-boilerplate entry points for pipx-installable solutions.

Solution authors write ZERO Python for the entry point. Everything
is declared in pyproject.toml:

    [project.scripts]
    my-solution-mcp = "mcp_app.entry:stdio"

    [project.entry-points."mcp_app"]
    app = "my_solution"

    [tool.setuptools.package-data]
    my_solution = ["mcp-app.yaml"]

How it works:
1. pipx installs the solution package (isolated venv)
2. User runs my-solution-mcp
3. That calls mcp_app.entry:stdio
4. stdio() uses importlib.metadata to find the "mcp_app" entry point group
5. Loads the registered "app" entry point → imports my_solution
6. Finds mcp-app.yaml next to my_solution/__init__.py
7. Calls mcp_app.run.stdio(config_path)

No subprocess. No cwd dependency. No Python glue in the solution.
"""

from importlib.metadata import entry_points
from pathlib import Path


def _discover_config() -> Path:
    """Find mcp-app.yaml from the registered mcp_app entry point."""
    eps = entry_points(group="mcp_app")
    app_eps = [ep for ep in eps if ep.name == "app"]

    if not app_eps:
        config = Path.cwd() / "mcp-app.yaml"
        if config.exists():
            return config
        raise FileNotFoundError(
            "No mcp_app entry point registered and no mcp-app.yaml in cwd.\n"
            "Add to your pyproject.toml:\n\n"
            '  [project.entry-points."mcp_app"]\n'
            '  app = "your_package"\n\n'
            '  [tool.setuptools.package-data]\n'
            '  your_package = ["mcp-app.yaml"]\n'
        )

    if len(app_eps) > 1:
        names = [ep.value for ep in app_eps]
        raise RuntimeError(
            f"Multiple mcp_app app entry points found: {names}. "
            "This happens when multiple mcp-app solutions are pip-installed "
            "in the same environment. Use pipx for isolated installs."
        )

    module = app_eps[0].load()
    config = Path(module.__file__).parent / "mcp-app.yaml"
    if not config.exists():
        pkg = app_eps[0].value
        raise FileNotFoundError(
            f"No mcp-app.yaml found in {config.parent}.\n"
            "Bundle it as package data in pyproject.toml:\n\n"
            "  [tool.setuptools.package-data]\n"
            f'  {pkg} = ["mcp-app.yaml"]\n'
        )
    return config


def stdio():
    """Entry point for stdio transport. Point your console_scripts here."""
    from mcp_app.run import stdio as _stdio
    _stdio(_discover_config())


def serve():
    """Entry point for HTTP transport. Point your console_scripts here."""
    from mcp_app.run import serve as _serve
    _serve(_discover_config())
