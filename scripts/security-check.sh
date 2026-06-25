#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

sensitive_path="$(find . -type f \( -name '.env' -o -name '.env.*' -o -name '.npmrc' \
  -o -name '*.pem' -o -name '*.key' -o -name '*.db' -o -name '*.sqlite3' \) \
  -not -name '.env.example' \
  -not -path './.venv/*' -not -path './.mypy_cache/*' -not -path './.pytest_cache/*' \
  -not -path './runtime-data/*' -not -path './web/node_modules/*' -print -quit)"
if [[ -n "$sensitive_path" ]]; then
  echo "发现不应提交的密钥或运行时文件" >&2
  exit 1
fi

if rg -n -i --glob '!uv.lock' --glob '!package-lock.json' \
  '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|api[_-]?key\s*[:=]\s*[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,})' .; then
  echo "发现疑似凭证" >&2
  exit 1
fi

home_prefix='/'"home"'/'
users_prefix='/'"Users"'/'
if rg --hidden -n -F -e "$home_prefix" -e "$users_prefix" . \
  --glob '!.venv/**' --glob '!web/node_modules/**' --glob '!web/dist/**' \
  --glob '!.mypy_cache/**' --glob '!.pytest_cache/**' --glob '!.ruff_cache/**' \
  --glob '!runtime-data/**' --glob '!.coverage'; then
  echo "发现不应公开的用户目录绝对路径" >&2
  exit 1
fi
