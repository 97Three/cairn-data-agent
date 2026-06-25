#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov --cov-report=term-missing
./scripts/security-check.sh
./scripts/wheel-smoke.sh

if [[ -f web/package.json ]]; then
  npm run check --prefix web
  npm run build --prefix web
  cmp -s LICENSE web/public/LICENSE.txt || {
    echo "Web LICENSE.txt 与仓库根许可证不一致" >&2
    exit 1
  }
  cmp -s web/public/LICENSE.txt web/dist/LICENSE.txt || {
    echo "Web 构建产物缺少项目许可证" >&2
    exit 1
  }
  cmp -s web/public/THIRD_PARTY_NOTICES.txt web/dist/THIRD_PARTY_NOTICES.txt || {
    echo "Web 构建产物缺少第三方许可声明" >&2
    exit 1
  }
fi
