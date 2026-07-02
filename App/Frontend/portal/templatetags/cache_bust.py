import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as static_url

register = template.Library()


@register.simple_tag
def static_versioned(path: str) -> str:
    """{% static %} plus a `?v=<mtime>` suffix so editing a static file
    (e.g. style.css) always busts browser cache without a manual bump."""
    url = static_url(path)
    absolute_path = finders.find(path)
    if not absolute_path:
        return url
    try:
        version = int(os.path.getmtime(absolute_path))
    except OSError:
        return url
    return f"{url}?v={version}"
