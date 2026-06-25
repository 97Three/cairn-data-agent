#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smoke_root="$(mktemp -d -t cairn-wheel-smoke.XXXXXX)"

cleanup() {
  if [[ -d "$smoke_root" ]]; then
    rm -rf -- "$smoke_root"
  fi
}
trap cleanup EXIT INT TERM

mkdir -p "$smoke_root/dist" "$smoke_root/home" "$smoke_root/run" "$smoke_root/tmp"

TMPDIR="$smoke_root/tmp" uv build \
  --offline \
  --no-python-downloads \
  --out-dir "$smoke_root/dist" \
  "$repo_root"

mapfile -t wheel_paths < <(find "$smoke_root/dist" -maxdepth 1 -type f -name '*.whl' -print)
if [[ ${#wheel_paths[@]} -ne 1 ]]; then
  echo "wheel smoke 需要且只能生成一个 wheel" >&2
  exit 1
fi

mapfile -t sdist_paths < <(find "$smoke_root/dist" -maxdepth 1 -type f -name '*.tar.gz' -print)
if [[ ${#sdist_paths[@]} -ne 1 ]]; then
  echo "wheel smoke 需要且只能生成一个 sdist" >&2
  exit 1
fi

uv run --offline --no-sync --no-python-downloads \
  python "$repo_root/scripts/verify-wheel.py" \
  wheel "${wheel_paths[0]}" "$repo_root"

uv run --offline --no-sync --no-python-downloads \
  python "$repo_root/scripts/verify-wheel.py" \
  sdist "${sdist_paths[0]}" "$repo_root"

UV_PROJECT_ENVIRONMENT="$smoke_root/venv" TMPDIR="$smoke_root/tmp" uv sync \
  --project "$repo_root" \
  --locked \
  --offline \
  --no-dev \
  --no-install-project \
  --no-python-downloads

uv pip install \
  --offline \
  --no-config \
  --no-python-downloads \
  --no-deps \
  --python "$smoke_root/venv/bin/python" \
  "${wheel_paths[0]}"

uv pip check \
  --offline \
  --no-config \
  --no-python-downloads \
  --python "$smoke_root/venv/bin/python"

(
  cd "$smoke_root/run"
  env -i \
    HOME="$smoke_root/home" \
    PATH="$smoke_root/venv/bin:/usr/bin:/bin" \
    TMPDIR="$smoke_root/tmp" \
    LC_ALL=C.UTF-8 \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    "$smoke_root/venv/bin/python" "$repo_root/scripts/verify-wheel.py" \
    installed "$repo_root"

  env -i \
    HOME="$smoke_root/home" \
    PATH="$smoke_root/venv/bin:/usr/bin:/bin" \
    TMPDIR="$smoke_root/tmp" \
    LC_ALL=C.UTF-8 \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAIRN_MODEL_MODE=fake \
    "$smoke_root/venv/bin/cairn-data-agent-demo" > "$smoke_root/demo.json"
)

if find "$smoke_root/run" -mindepth 1 -print -quit | grep -q .; then
  echo "wheel Demo 污染了当前工作目录" >&2
  exit 1
fi

"$smoke_root/venv/bin/python" "$repo_root/scripts/verify-wheel.py" \
  demo "$smoke_root/demo.json" "$repo_root"
