import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("typer")
import yaml

BUILD = """
import sys
import glyphforge.cli, glyphforge._cli
glyphforge._cli.build_app()
loaded = {"datasets", "pyarrow"} & set(sys.modules)
assert not loaded, loaded
"""

PLAN = "import sys\nfrom glyphforge._cli import build_app\nbuild_app()(['plan', sys.argv[1], '--json', *sys.argv[2:]])"


def test_cli_startup_is_free_of_datasets_and_pyarrow():
    subprocess.run([sys.executable, "-I", "-c", BUILD], check=True)


def _estimate(recipe, *flags):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GLYPHFORGE_")}
    res = subprocess.run([sys.executable, "-I", "-c", PLAN, str(recipe), *flags], env=env, capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)["estimate"]


def test_docker_memory_flag_takes_effect_before_resources_import(tmp_path):
    recipe = tmp_path / "r.yaml"
    recipe.write_text(
        yaml.safe_dump(
            {
                "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["a+v", "b+v"]},
                "classes": ["greek.upsilon_v"],
                "composition": {"total": 2},
            }
        )
    )
    assert _estimate(recipe, "--docker-memory", "2")["docker_memory_gb"] == 2
    assert _estimate(recipe)["docker_memory_gb"] == 4
