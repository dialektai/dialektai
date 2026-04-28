"""Visual content engine — HTML templates rendered to PNG via Playwright."""

from .html_to_png import render_template, substitute_variables
from .installer import install_bundled_templates
from .template_registry import (
    Template,
    TemplateNotFoundError,
    TemplateValidationError,
    list_templates,
    get_template,
    render,
)

__all__ = [
    "render_template",
    "substitute_variables",
    "install_bundled_templates",
    "Template",
    "TemplateNotFoundError",
    "TemplateValidationError",
    "list_templates",
    "get_template",
    "render",
]
