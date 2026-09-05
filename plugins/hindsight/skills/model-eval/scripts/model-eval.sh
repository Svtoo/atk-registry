#!/bin/bash
# Bake-off of a candidate extraction model against the production Hindsight
# stack: one arm at a time, on a frozen corpus, with the eval stack generated
# from a snapshot of the production container and checked against that
# snapshot before a cent is spent.
#
#   model-eval preflight
#   model-eval pin <arm> [--json]                                   openrouter arms only
#   model-eval ingest <arm> [--pin '<json list>'] [--subset <corpus file>]
#                     [--key-is-for <provider>] [--exclusive] [--dry-run] [arm.py args]
#   model-eval read <run-id> [--key-is-for <provider>] [--exclusive] [read_test.py args]
#   model-eval compare [--runs a,b]
#   model-eval cost [--runs a,b]                                    openrouter runs only
#   model-eval list
#
# Arms are declared in arms.yaml. Runs land in the plugin's
# custom/model-eval-runs/<run-id>/ and are never overwritten.
#
# The key is always the plugin's HINDSIGHT_LLM_API_KEY. An arm on another
# provider than production's needs that key swapped in the plugin's .env for
# the run and --key-is-for naming the provider; a shell export cannot stand in,
# because .env wins over the shell environment under atk run and in lib.sh.
#
# --exclusive stops production for a local arm that needs the machine to
# itself, after a yes typed in the terminal, and restarts it on every exit.
set -euo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$SCRIPTS/.." && pwd)"
PROD_PLUGIN=hindsight
# The plugin is found through ATK's home rather than by walking out of this
# skill, so the skill behaves the same wherever it is copied.
PLUGIN="${HINDSIGHT_PLUGIN_DIR:-${ATK_HOME:-$HOME/.atk}/plugins/$PROD_PLUGIN}"
[ -d "$PLUGIN" ] || {
  printf 'FATAL: no hindsight plugin at %s\n' "$PLUGIN" >&2
  printf '       set ATK_HOME, or HINDSIGHT_PLUGIN_DIR to the plugin itself\n' >&2
  exit 1
}
# The plugin already holds the provider and its key, and an eval runs against
# that same stack, so this reads them rather than asking for a second copy.
# .env wins over the shell, exactly as it does under atk run.
if [ -f "$PLUGIN/.env" ]; then
  set -a
  . "$PLUGIN/.env"
  set +a
fi
# Not custom/model-eval: atk run resolves custom/<script> before the plugin
# root, so a directory of that name would shadow model-eval.sh.
RUNS="${MODEL_EVAL_RUNS_DIR:-$PLUGIN/custom/model-eval-runs}"
# Every python step reads the same two paths.
export HINDSIGHT_PLUGIN_DIR="$PLUGIN" MODEL_EVAL_RUNS_DIR="$RUNS"
CORPUS="$SKILL/corpus"
PROJECT=hindsight-eval
EVAL_CONTAINER=hindsight-eval
PROD_CONTAINER=hindsight
EVAL_API=http://localhost:18888
PROD_API="${HINDSIGHT_URL:-http://localhost:8888}"
PROD_BANK="${HINDSIGHT_BANK:-default}"
DEFAULT_SUBSET=half.txt
SNAPSHOT_CONTAINER=prod.json
SNAPSHOT_BANK=prod-bank.json
PROD_STOPPED=""

die() { printf 'FATAL: %s\n' "$*" >&2; exit 1; }
say() { printf '== %s\n' "$*"; }
usage() { awk 'NR > 1 && /^set -euo pipefail/ { exit } NR > 1 { print }' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

prod_image() {
  docker inspect "$PROD_CONTAINER" --format '{{.Config.Image}}' 2>/dev/null \
    || die "production container '$PROD_CONTAINER' is not present"
}
image_tag() {
  local image; image="$(prod_image)"
  case "$image" in
    *:*) echo "${image##*:}" ;;
    *) die "production image '$image' carries no tag" ;;
  esac
}

compose_up() {  # <compose file>
  docker compose -p "$PROJECT" -f "$1" up -d --force-recreate >/dev/null
}
wait_health() {
  local i
  for i in $(seq 1 100); do
    curl -fsS "$EVAL_API/health" >/dev/null 2>&1 && return 0
    [ "$(docker inspect -f '{{.State.Status}}' "$EVAL_CONTAINER" 2>/dev/null)" = "running" ] \
      || die "$EVAL_CONTAINER stopped while starting; see: docker compose -p $PROJECT logs --tail 50"
    sleep 3
  done
  die "$EVAL_API/health did not answer within 300s"
}
verify_stack() {  # <provider> <model>: prove the container serves THIS stack before a request is made
  local env provider model
  env="$(docker inspect "$EVAL_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}')"
  provider="$(printf '%s\n' "$env" | { grep '^HINDSIGHT_API_LLM_PROVIDER=' || true; } | cut -d= -f2-)"
  model="$(printf '%s\n' "$env" | { grep '^HINDSIGHT_API_LLM_MODEL=' || true; } | cut -d= -f2-)"
  [ "$provider" = "$1" ] || die "container serves provider '$provider', expected '$1'"
  [ "$model" = "$2" ] || die "container serves '$model', expected '$2'"
  say "container is serving $model on $provider"
}
parity() {  # <run-dir> [eval bank]
  if [ $# -ge 2 ]; then
    python3 "$SCRIPTS/parity.py" --run-dir "$1" "$2" || die "stack does not match production; not spending a cent"
  else
    python3 "$SCRIPTS/parity.py" --run-dir "$1" || die "stack does not match production; not spending a cent"
  fi
}
bank_exists() {  # <bank>
  curl -fsS "$EVAL_API/v1/default/banks" \
    | BANK="$1" python3 -c '
import json, os, sys
d = json.load(sys.stdin)
banks = d.get("banks") or d.get("items") or d
ids = {b.get("bank_id") or b.get("id") if isinstance(b, dict) else b for b in banks}
sys.exit(0 if os.environ["BANK"] in ids else 1)'
}
resolve_subset() {  # name in corpus/, or a path
  case "$1" in
    */*) [ -f "$1" ] || die "subset file not found: $1"
         echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" ;;
    *)   [ -f "$CORPUS/$1" ] || die "no subset '$1' in $CORPUS"
         echo "$CORPUS/$1" ;;
  esac
}
take_snapshot() {  # <run-dir>: production's container and bank config, before anything else happens
  python3 "$SCRIPTS/snapshot.py" --run-dir "$1" --prod-container "$PROD_CONTAINER" \
    --prod-api "$PROD_API" --bank "$PROD_BANK"
}
arm_export() {  # <arm key or id>: sets ARM_ID ARM_KEY ARM_PROVIDER ARM_MODEL ARM_BASE_URL ARM_STRICT_SCHEMA ARM_MAX_CONCURRENT
  local exports
  exports="$(python3 "$SCRIPTS/armsfile.py" --export "$1")" || die "no usable arm '$1'; known arms: python3 $SCRIPTS/armsfile.py --list"
  eval "$exports"
}
export_stack() {  # <run-dir> <provider> <model> <base_url> <strict_schema> <max_concurrent> <pin json or empty>
  local exports
  unset EVAL_REFLECT_LLM_EXTRA_BODY
  if [ -n "$7" ]; then
    exports="$(python3 "$SCRIPTS/stack.py" --run-dir "$1" --provider "$2" --model "$3" --base-url "$4" \
               --strict-schema "$5" --max-concurrent "$6" --pin "$7")" || die "stack derivation failed"
  else
    exports="$(python3 "$SCRIPTS/stack.py" --run-dir "$1" --provider "$2" --model "$3" --base-url "$4" \
               --strict-schema "$5" --max-concurrent "$6")" || die "stack derivation failed"
  fi
  eval "$exports"
  say "stack: provider=$EVAL_LLM_PROVIDER model=$EVAL_LLM_MODEL base_url=${EVAL_LLM_BASE_URL:-<provider default>}" \
      "strict_schema=$EVAL_LLM_STRICT_SCHEMA max_concurrent=$EVAL_LLM_MAX_CONCURRENT"
  [ -z "${EVAL_REFLECT_LLM_EXTRA_BODY+x}" ] || say "reflect extra body: $EVAL_REFLECT_LLM_EXTRA_BODY"
}

resolve_key() {  # <arm provider> <--key-is-for value or empty>: exports EVAL_LLM_API_KEY
  local provider="$1" declared="$2" prod_provider="${HINDSIGHT_LLM_PROVIDER:-}" hint=""
  [ -n "$prod_provider" ] || die "HINDSIGHT_LLM_PROVIDER is not set in the plugin environment"
  [ -n "${HINDSIGHT_LLM_API_KEY:-}" ] || die "HINDSIGHT_LLM_API_KEY is not set in the plugin environment"
  if [ -n "$declared" ] && [ "$declared" != "$provider" ]; then
    die "--key-is-for $declared does not name this arm's provider '$provider'"
  fi
  if [ "$provider" != "$prod_provider" ] && [ -z "$declared" ]; then
    [ "$provider" != ollama ] || hint=" Ollama ignores the key, so not-needed will do."
    die "the plugin key belongs to production's provider '$prod_provider'; this arm runs on '$provider'.
       Swap HINDSIGHT_LLM_API_KEY in the plugin's .env to a key for $provider, rerun with --key-is-for $provider,
       and swap it back afterwards. The running production container keeps the key it started with, so the
       swap holds until the next atk restart hindsight.${hint}"
  fi
  export EVAL_LLM_API_KEY="$HINDSIGHT_LLM_API_KEY"
  say "key: the plugin's HINDSIGHT_LLM_API_KEY, for $provider (${#EVAL_LLM_API_KEY} chars)"
}

exclusive_precheck() {  # refuse before anything is touched when no yes can be typed
  [ "${ATK_NONINTERACTIVE:-}" != "1" ] \
    || die "--exclusive stops production and needs a yes typed in this session; ATK_NONINTERACTIVE=1 refuses it"
  [ -t 0 ] || die "--exclusive stops production and needs a yes typed in this session; stdin is not a terminal"
  command -v atk >/dev/null 2>&1 || die "atk is not on PATH; --exclusive stops and starts production through it"
}
restart_production() {
  local rc=$?
  if [ -n "$PROD_STOPPED" ]; then
    say "restarting production ($PROD_PLUGIN)"
    if atk start "$PROD_PLUGIN"; then
      say "production restarted"
    else
      printf 'FATAL: production did not restart; run: atk start %s\n' "$PROD_PLUGIN" >&2
      [ "$rc" -ne 0 ] || rc=1
    fi
  fi
  exit "$rc"
}
stop_production() {  # the only place production is touched, and only after a typed yes
  local state answer
  state="$(docker inspect -f '{{.State.Status}}' "$PROD_CONTAINER" 2>/dev/null || echo absent)"
  [ "$state" = running ] || die "production is '$state', not running; --exclusive stops a running production and restarts it, it does not guess at one that is already down"
  printf '\nThis run stops production (%s) until it ends, and restarts it on exit, success or failure.\nAgents lose their memory while it is stopped. Type yes to continue: ' "$PROD_PLUGIN"
  read -r answer
  [ "$answer" = "yes" ] || die "not confirmed; production untouched"
  trap restart_production EXIT
  trap 'exit 130' INT TERM
  PROD_STOPPED=1
  atk stop "$PROD_PLUGIN" || die "atk stop $PROD_PLUGIN failed"
  say "production stopped"
}

cmd_preflight() {
  command -v docker >/dev/null 2>&1 || die "docker is not on PATH"
  docker info >/dev/null 2>&1 || die "Docker is not running"
  command -v python3 >/dev/null 2>&1 || die "python3 is not on PATH"
  local state health
  state="$(docker inspect -f '{{.State.Status}}' "$PROD_CONTAINER" 2>/dev/null)" \
    || die "production container '$PROD_CONTAINER' is not present"
  [ "$state" = "running" ] || die "production container is '$state', not running"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$PROD_CONTAINER")"
  [ "$health" = "healthy" ] || die "production container health is '$health'"
  curl -fsS "$PROD_API/health" >/dev/null 2>&1 || die "production API at $PROD_API/health does not answer"
  say "production: $(prod_image) running and healthy"

  docker inspect "$PROD_CONTAINER" --format '{{json .Config.Env}}' | python3 -c '
import json, sys, urllib.request
env = dict(e.split("=", 1) for e in json.load(sys.stdin) if "=" in e)
model = env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL") or sys.exit("production sets no embeddings model")
base = env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL") or sys.exit("production sets no embeddings base url")
host = base.replace("host.docker.internal", "localhost")
tags = host[: host.index("/v1")] + "/api/tags" if "/v1" in host else host.rstrip("/") + "/api/tags"
try:
    names = [m["name"] for m in json.load(urllib.request.urlopen(tags, timeout=5)).get("models", [])]
except Exception as e:
    sys.exit(f"embeddings endpoint {tags} is not answering: {e}")
want = model if ":" in model else model + ":latest"
if want not in names:
    sys.exit(f"embeddings model {want!r} is not available at {tags}; pull it with: ollama pull {model}")
print(f"== embeddings: {want} available at {host}")
' || die "embeddings check failed"

  [ -n "${HINDSIGHT_LLM_PROVIDER:-}" ] || die "HINDSIGHT_LLM_PROVIDER is not set in the plugin environment"
  [ -n "${HINDSIGHT_LLM_API_KEY:-}" ] || die "HINDSIGHT_LLM_API_KEY is not set in the plugin environment"
  say "plugin key: for $HINDSIGHT_LLM_PROVIDER (${#HINDSIGHT_LLM_API_KEY} chars); an arm on another provider needs it swapped in .env and --key-is-for"
  python3 "$SCRIPTS/armsfile.py" --validate >/dev/null || die "arms.yaml is invalid"
  local f
  for f in code_handover.json decisions_rationale.json meetings_people.json short_factual.json half.txt queries.json; do
    [ -f "$CORPUS/$f" ] || die "corpus file missing: $CORPUS/$f"
  done
  say "corpus complete; arms: $(python3 "$SCRIPTS/armsfile.py" --list | awk '{print $2}' | tr '\n' ' ')"
  local tmp; tmp="$(mktemp -d -t model-eval-preflight)"
  take_snapshot "$tmp" >/dev/null || die "snapshot failed"
  python3 "$SCRIPTS/compose.py" --run-dir "$tmp" --out "$tmp/docker-compose.yml" >/dev/null || die "compose generation failed"
  rm -rf "$tmp"
  say "snapshot and compose generate from production"
  state="$(docker inspect -f '{{.State.Status}}' "$EVAL_CONTAINER" 2>/dev/null || echo absent)"
  say "eval container is $state; ingest and read recreate it, its volumes are kept"
  say "preflight OK"
}

cmd_pin() {
  python3 "$SCRIPTS/pins.py" "$@"
}

cmd_ingest() {
  local arm="${1:?usage: model-eval ingest <arm> [--pin '<json list>'] [--subset <file>] [--key-is-for <provider>] [--exclusive] [--dry-run]}"; shift
  local pin="" subset="$DEFAULT_SUBSET" key_for="" exclusive="" dry_run="" pass=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --pin)        [ $# -ge 2 ] || die "--pin needs a value"; pin="$2"; shift 2 ;;
      --subset)     [ $# -ge 2 ] || die "--subset needs a value"; subset="$2"; shift 2 ;;
      --key-is-for) [ $# -ge 2 ] || die "--key-is-for needs a provider"; key_for="$2"; shift 2 ;;
      --exclusive)  exclusive=1; shift ;;
      --dry-run)    dry_run=1; shift ;;
      *)            pass+=("$1"); shift ;;
    esac
  done
  arm_export "$arm"
  if [ "$ARM_PROVIDER" = openrouter ]; then
    [ -n "$pin" ] || die "--pin is required for an openrouter arm; build one with: model-eval pin $ARM_KEY"
  else
    [ -z "$pin" ] || die "--pin is an OpenRouter concept; arm '$ARM_KEY' runs on $ARM_PROVIDER and takes none"
  fi
  if [ -n "$exclusive" ]; then
    [ "$ARM_PROVIDER" = ollama ] || die "--exclusive is for a local ollama arm; '$ARM_KEY' runs on $ARM_PROVIDER"
    exclusive_precheck
  fi
  resolve_key "$ARM_PROVIDER" "$key_for"
  local subset_path; subset_path="$(resolve_subset "$subset")"

  local image tag base_id run_id n run_dir bank
  image="$(prod_image)"; tag="$(image_tag)"
  base_id="$(date +%F)_${ARM_KEY}_${tag}"; run_id="$base_id"; n=1
  while [ -e "$RUNS/$run_id" ]; do n=$((n + 1)); run_id="${base_id}_$n"; done
  if [ -n "$dry_run" ]; then
    run_id="${base_id}_dry"
    run_dir="$(mktemp -d -t model-eval-dry)"
  else
    run_dir="$RUNS/$run_id"
    mkdir -p "$run_dir"
  fi
  bank="eval-$run_id"

  say "run $run_id  arm=$ARM_KEY  provider=$ARM_PROVIDER  model=$ARM_MODEL  image=$image${dry_run:+  (dry run)}"
  [ -z "$pin" ] || say "pin $pin"
  [ "$ARM_STRICT_SCHEMA" = true ] || say "strict_schema=false: this run measures JSON-mode extraction and is not schema-comparable to strict arms"
  take_snapshot "$run_dir"
  python3 "$SCRIPTS/compose.py" --run-dir "$run_dir" --out "$run_dir/docker-compose.yml"
  [ -z "$pin" ] || printf '%s\n' "$pin" > "$run_dir/pin.json"

  export_stack "$run_dir" "$ARM_PROVIDER" "$ARM_MODEL" "$ARM_BASE_URL" "$ARM_STRICT_SCHEMA" "$ARM_MAX_CONCURRENT" "$pin"
  [ -z "$exclusive" ] || stop_production
  compose_up "$run_dir/docker-compose.yml"
  wait_health
  verify_stack "$ARM_PROVIDER" "$ARM_MODEL"
  parity "$run_dir"
  if [ -n "$dry_run" ]; then
    say "dry run complete: the stack boots and matches production; nothing retained. Artifacts: $run_dir"
    return 0
  fi
  if bank_exists "$bank"; then die "bank '$bank' already exists on the eval instance; a run never ingests into a bank that holds data"; fi

  python3 "$SCRIPTS/arm.py" --run-dir "$run_dir" --run-id "$run_id" --arm "$ARM_KEY" --image "$image" \
    --bank "$bank" --subset "$subset_path" ${exclusive:+--exclusive} ${pass[@]+"${pass[@]}"}
  parity "$run_dir" "$bank"
  python3 "$SCRIPTS/tally.py" --run-dir "$run_dir" --bank "$bank" --subset "$subset_path" --label "$ARM_KEY  $ARM_MODEL"
  say "run $run_id complete: $run_dir"
  say "next: model-eval read $run_id${exclusive:+ --exclusive}${key_for:+ --key-is-for $key_for}"
}

cmd_read() {
  local run_id="${1:?usage: model-eval read <run-id> [--key-is-for <provider>] [--exclusive] [read_test.py args]}"; shift
  local key_for="" exclusive="" pass=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --key-is-for) [ $# -ge 2 ] || die "--key-is-for needs a provider"; key_for="$2"; shift 2 ;;
      --exclusive)  exclusive=1; shift ;;
      *)            pass+=("$1"); shift ;;
    esac
  done
  local run_dir="$RUNS/$run_id"
  [ -f "$run_dir/run.json" ] || die "no run.json in $run_dir; see: model-eval list"
  [ -f "$run_dir/docker-compose.yml" ] || die "no docker-compose.yml in $run_dir"
  if [ ! -f "$run_dir/$SNAPSHOT_CONTAINER" ] || [ ! -f "$run_dir/$SNAPSHOT_BANK" ]; then
    die "run $run_id carries no production snapshot ($SNAPSHOT_CONTAINER, $SNAPSHOT_BANK): it was recorded before snapshots existed and cannot be re-read against the production it was copied from"
  fi
  local exports
  exports="$(python3 "$SCRIPTS/runs.py" --export "$run_id")" || die "cannot read $run_dir/run.json"
  eval "$exports"
  if [ "$RUN_EXCLUSIVE" = true ]; then
    [ -n "$exclusive" ] || die "run $run_id was exclusive (production stopped); its read side needs the machine too: pass --exclusive"
    exclusive_precheck
  else
    [ -z "$exclusive" ] || die "run $run_id was not exclusive; --exclusive does not apply to it"
  fi
  resolve_key "$RUN_PROVIDER" "$key_for"
  say "read $run_id  provider=$RUN_PROVIDER  model=$RUN_MODEL  bank=$RUN_BANK"
  export_stack "$run_dir" "$RUN_PROVIDER" "$RUN_MODEL" "$RUN_BASE_URL" "$RUN_STRICT_SCHEMA" "$RUN_MAX_CONCURRENT" "$RUN_PIN"
  [ -z "$exclusive" ] || stop_production
  compose_up "$run_dir/docker-compose.yml"
  wait_health
  verify_stack "$RUN_PROVIDER" "$RUN_MODEL"
  parity "$run_dir"
  bank_exists "$RUN_BANK" || die "bank '$RUN_BANK' is not on the eval instance; its volume was replaced or the bank was deleted"
  # The bank must be exactly as ingestion left it; a changed count means something
  # rewrote it between runs and the read result would not describe that ingestion.
  curl -fsS "$EVAL_API/v1/default/banks/$RUN_BANK/stats" \
   | python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"   bank: {d['total_nodes']} facts, {d['total_observations']} observations, {d['pending_consolidation']} pending consolidation\")"
  python3 "$SCRIPTS/read_test.py" --run-dir "$run_dir" ${pass[@]+"${pass[@]}"}
  say "read $run_id complete: $run_dir/read.json"
}

cmd_compare() {
  python3 "$SCRIPTS/compare.py" "$@"
  echo
  python3 "$SCRIPTS/read_compare.py" "$@"
}

cmd_cost() {
  python3 "$SCRIPTS/cost.py" "$@"
}

cmd_list() {
  [ -d "$RUNS" ] || { say "no runs yet in $RUNS"; return 0; }
  python3 "$SCRIPTS/runs.py" --list
}

case "${1:-}" in
  preflight|pin|ingest|read|compare|cost|list) cmd="$1"; shift; "cmd_$cmd" "$@" ;;
  -h|--help) usage ;;
  "") usage; exit 1 ;;
  *) usage >&2; die "unknown subcommand '$1'" ;;
esac
