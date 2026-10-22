import os
import pathlib
import subprocess
import sys

path = os.environ["VITE_CONFIG"]
repo_root = os.environ["PROJECT_ROOT"]

# Read the committed (clean) content so we always patch the same baseline.
result = subprocess.run(
    ["git", "show", "HEAD:src/frontend/vite.config.js"],
    cwd=repo_root,
    capture_output=True,
    text=True,
    check=True,
)
original = result.stdout
patched = original.replace(
    "alias: {\n\t\t\t'fractal-components': fractalComponents\n\t\t}\n\t},",
    "alias: {\n\t\t\t'fractal-components': fractalComponents\n\t\t},\n\t\tdedupe: ['ajv', 'ajv-formats', 'slim-select', 'svelte', 'color-hash', 'marked', 'dompurify']\n\t},",
)
if patched == original:
    print(
        "ERROR: vite.config.js patch did not apply — structure may have changed",
        file=sys.stderr,
    )
    sys.exit(1)
pathlib.Path(path).write_text(patched)
