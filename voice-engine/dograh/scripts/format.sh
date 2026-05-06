#!/bin/sh -e
set -euo pipefail

ruff check api --select I --select F401 --fix
ruff format api
