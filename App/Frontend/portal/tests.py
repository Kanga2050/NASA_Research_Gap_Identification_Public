"""Consistency tests for the pipeline function registry.

The registry (``App.Backend.registry``) is the single declaration of every pipeline
function, and the task engine, the dashboard form, the Studio manifest, the REST API
and the MCP tools are all generated from it. These tests lock the one invariant that
holds that scheme together and that nothing else can check:

    the registry's params, in order, ARE the backend function's positional signature.

If someone reorders a backend function's arguments, or renames one, or adds a required
one, the tasks queued for it would silently receive their arguments in the wrong slots
-- a corrupted CSV rather than a crash. That used to be a real hazard: the argument
order was restated by hand in five places. Now it is stated once, and asserted here.

Run with:  python App/Frontend/manage.py test App/Frontend/portal
(the path form, not the dotted-module form: App has no __init__.py, so it's a
namespace package and unittest's dotted-label discovery breaks on it -- the
module object's __file__ is None, and dirname(None) raises TypeError.)
"""
from __future__ import annotations

import importlib
import inspect

from django.test import SimpleTestCase

from App.Backend import registry
from App.Frontend.portal.forms import TaskSubmitForm
from App.Frontend.portal.graph_manifest import MANIFEST

# What views.py hands a callable default (a default computed from a sibling form field).
CLEANED_FORM = {"csv_name": "SomeCsv"}


def _backend_callable(fn: registry.Function):
    module_path, attribute = fn.impl.split(":")
    return getattr(importlib.import_module(module_path), attribute)


class RegistryMatchesBackendTests(SimpleTestCase):
    """Every registry entry must line up with the function it actually runs."""

    def test_impl_is_importable(self):
        for fn in registry.ALL_FUNCTIONS:
            with self.subTest(function=fn.name):
                self.assertTrue(callable(_backend_callable(fn)))

    def test_params_are_the_backend_positional_signature(self):
        for fn in registry.ALL_FUNCTIONS:
            with self.subTest(function=fn.name):
                signature = inspect.signature(_backend_callable(fn))
                positional = [
                    name for name in signature.parameters if not name.endswith("_root")
                ]
                declared = [param.name for param in fn.params]
                self.assertEqual(
                    positional[: len(declared)],
                    declared,
                    f"{fn.name}: the registry's params must be a positional prefix of the "
                    f"backend signature {positional}",
                )

    def test_declared_roots_are_real_keyword_arguments(self):
        for fn in registry.ALL_FUNCTIONS:
            signature = inspect.signature(_backend_callable(fn))
            for root in fn.roots:
                with self.subTest(function=fn.name, root=root):
                    self.assertIn(f"{root}_root", signature.parameters)

    def test_queued_arguments_bind_to_the_backend_function(self):
        """The exact call the task engine will make must be a legal call."""
        for fn in registry.ALL_FUNCTIONS:
            with self.subTest(function=fn.name):
                args = [
                    param.default(CLEANED_FORM) if callable(param.default) else param.default
                    for param in fn.params
                ]
                roots = {f"{root}_root": "/tmp" for root in fn.roots}
                inspect.signature(_backend_callable(fn)).bind(*args, **roots)

    def test_output_param_is_where_the_dashboard_looks_for_it(self):
        """`output_index` is the positional slot the finished-task preview reads the
        produced file's name out of."""
        for fn in registry.ALL_FUNCTIONS:
            with self.subTest(function=fn.name):
                self.assertIs(fn.params[fn.output_index], fn.output_param)
                self.assertIn(fn.output_kind, ("csv", "html"))


class RegistryMatchesSurfacesTests(SimpleTestCase):
    """The generated surfaces must be able to express every function."""

    def test_form_declares_every_field_the_registry_expects(self):
        declared = set(TaskSubmitForm.base_fields)
        for fn in registry.ALL_FUNCTIONS:
            for field in fn.form_fields:
                with self.subTest(function=fn.name, field=field):
                    self.assertIn(field, declared)

    def test_every_studio_node_maps_to_a_registry_function(self):
        for action in MANIFEST:
            if action.startswith("__"):   # the canvas's own source/bridge nodes
                continue
            with self.subTest(action=action):
                self.assertIn(action, registry.REGISTRY)

    def test_api_and_mcp_names_are_unique_per_function(self):
        for fn in registry.ALL_FUNCTIONS:
            with self.subTest(function=fn.name):
                api = [param.api_name for param in fn.params]
                mcp = [param.mcp_name for param in fn.params]
                self.assertEqual(len(api), len(set(api)))
                self.assertEqual(len(mcp), len(set(mcp)))

    def test_form_computed_defaults_have_an_api_fallback(self):
        """A default computed from a sibling form field is meaningless to an API caller,
        who submits no such field -- so it needs a plain value to fall back on, or the
        caller would silently send None."""
        for fn in registry.ALL_FUNCTIONS:
            for param in fn.params:
                if callable(param.default) and not param.required:
                    with self.subTest(function=fn.name, param=param.name):
                        self.assertIsNotNone(param.api_default())

    def test_routes_are_unique(self):
        routes = [fn.route for fn in registry.ALL_FUNCTIONS]
        self.assertEqual(len(routes), len(set(routes)))
