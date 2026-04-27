"""Visual content engine — HTML templates rendered to PNG via Playwright."""

from .html_to_png import render_template, substitute_variables

__all__ = ["render_template", "substitute_variables"]
