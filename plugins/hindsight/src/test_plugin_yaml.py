#!/usr/bin/env python3
"""Tests for plugin.yaml: what atk setup asks, and in what order."""
import os
import re
import unittest

PLUGIN_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin.yaml")


def env_var_names():
    with open(PLUGIN_YAML) as fh:
        block = fh.read().split("env_vars:", 1)[1].split("\nlifecycle:", 1)[0]
    return re.findall(r"^\s+- name: (\w+)", block, re.M)


class SetupOrderTest(unittest.TestCase):
    def test_setup_asks_provider_before_model_and_key(self):
        names = env_var_names()
        # Then the model and the key are answered with the provider known
        self.assertLess(names.index("HINDSIGHT_LLM_PROVIDER"),
                        names.index("HINDSIGHT_LLM_MODEL"))
        self.assertLess(names.index("HINDSIGHT_LLM_MODEL"),
                        names.index("HINDSIGHT_LLM_API_KEY"))

    def test_the_provider_is_optional_and_has_no_default(self):
        with open(PLUGIN_YAML) as fh:
            block = fh.read().split("- name: HINDSIGHT_LLM_PROVIDER", 1)[1].split("- name:", 1)[0]
        # Then remote mode is not asked for it as required, and local mode gets no guess
        self.assertIn("required: false", block)
        self.assertNotIn("default:", block)


if __name__ == "__main__":
    unittest.main()
