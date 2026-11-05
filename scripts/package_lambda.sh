#!/usr/bin/env bash
# Stage the Lambda source bundle consumed by infra/template.yaml (CodeUri: ../build/lambda).
# Usage: scripts/package_lambda.sh && sam build -t infra/template.yaml && sam deploy --guided
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/lambda"

rm -rf "$OUT"
mkdir -p "$OUT"
cp -r "$ROOT/costlens" "$ROOT/aws" "$OUT/"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +

# Runtime dependencies only; boto3 is provided by the Lambda runtime.
cat > "$OUT/requirements.txt" <<'EOF'
duckdb>=1.1
numpy>=2.0
EOF

echo "Lambda bundle staged in $OUT"
