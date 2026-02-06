#!/bin/bash
# Langfuse maintenance script - optimizes storage and prevents disk bloat

set -e

CLICKHOUSE_HOST="localhost"
CLICKHOUSE_PORT="18123"
CLICKHOUSE_USER="clickhouse"
CLICKHOUSE_PASSWORD="clickhouse"
CLICKHOUSE_DB="default"
CONTAINER_NAME="langfuse-langfuse-clickhouse-1"
COMPOSE_FILE="docker-compose.yml"
SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

execute_query() {
    curl -s --user "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" \
        --data-binary "$1" \
        "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}/?database=${CLICKHOUSE_DB}"
}

show_table_sizes() {
    echo "Table sizes:"
    execute_query "
        SELECT table, formatReadableSize(sum(bytes)) as size, sum(rows) as rows
        FROM system.parts
        WHERE active = 1 AND database = '${CLICKHOUSE_DB}'
        GROUP BY table ORDER BY sum(bytes) DESC
        FORMAT PrettyCompact
    "
}

show_trace_cost() {
    local trace_id="$1"
    if [ -z "$trace_id" ]; then
        echo "Usage: show_trace_cost <trace_id>"
        return 1
    fi

    echo "Cost breakdown for trace: $trace_id"
    execute_query "
        SELECT
            provided_model_name as model_name,
            COUNT(*) as calls,
            ROUND(SUM(total_cost), 6) as total_cost,
            SUM(usage_details['input']) as input_tokens,
            SUM(usage_details['input_cache_read']) as cached_tokens,
            SUM(usage_details['output']) as output_tokens
        FROM observations
        WHERE trace_id = '${trace_id}'
          AND provided_model_name IS NOT NULL
        GROUP BY provided_model_name
        ORDER BY total_cost DESC
        FORMAT PrettyCompact
    "

    echo ""
    echo "Summary totals:"
    execute_query "
        SELECT
            'TOTAL' as summary,
            COUNT(*) as calls,
            ROUND(SUM(total_cost), 6) as total_cost,
            SUM(usage_details['input']) as input_tokens,
            SUM(usage_details['input_cache_read']) as cached_tokens,
            SUM(usage_details['output']) as output_tokens
        FROM observations
        WHERE trace_id = '${trace_id}'
          AND provided_model_name IS NOT NULL
        FORMAT PrettyCompact
    "
}

disable_system_logging() {
    echo "Disabling ClickHouse system logging tables..."

    local config_content='<?xml version="1.0"?>
<clickhouse>
    <!-- Disable resource-intensive system tables -->
    <trace_log remove="1"/>
    <metric_log remove="1"/>
    <opentelemetry_span_log remove="1"/>
    <processors_profile_log remove="1"/>
    <asynchronous_metric_log remove="1"/>
    <query_metric_log remove="1"/>

    <!-- Keep essential logs with TTL -->
    <query_log>
        <database>system</database>
        <table>query_log</table>
        <partition_by>toYYYYMM(event_date)</partition_by>
        <ttl>event_date + INTERVAL 7 DAY DELETE</ttl>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
    </query_log>

    <query_thread_log>
        <database>system</database>
        <table>query_thread_log</table>
        <partition_by>toYYYYMM(event_date)</partition_by>
        <ttl>event_date + INTERVAL 7 DAY DELETE</ttl>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
    </query_thread_log>

    <text_log>
        <database>system</database>
        <table>text_log</table>
        <ttl>event_date + INTERVAL 3 DAY DELETE</ttl>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
    </text_log>
</clickhouse>'

    echo "$config_content" | docker exec -i "$CONTAINER_NAME" sh -c 'cat > /etc/clickhouse-server/config.d/z_system_tables.xml'
    echo "System logging configuration applied. Restart required for full effect."
}

cleanup_system_tables() {
    echo "Cleaning existing system table bloat..."

    local bloated_tables=("trace_log" "trace_log_0" "trace_log_1" "trace_log_2"
                          "metric_log" "metric_log_0" "metric_log_1"
                          "text_log" "text_log_0" "text_log_1" "text_log_2"
                          "opentelemetry_span_log" "processors_profile_log"
                          "asynchronous_metric_log"
                          "query_metric_log" "query_metric_log_0")

    for table in "${bloated_tables[@]}"; do
        execute_query "DROP TABLE IF EXISTS system.${table}" >/dev/null 2>&1 || true
    done

    execute_query "ALTER TABLE IF EXISTS system.query_log MODIFY TTL event_date + INTERVAL 7 DAY" >/dev/null 2>&1 || true
    execute_query "ALTER TABLE IF EXISTS system.query_thread_log MODIFY TTL event_date + INTERVAL 7 DAY" >/dev/null 2>&1 || true
}

force_ttl_cleanup() {
    echo "Forcing TTL cleanup..."
    for table in traces observations scores; do
        execute_query "OPTIMIZE TABLE ${table} FINAL" >/dev/null 2>&1 || true
    done
}

wait_for_clickhouse() {
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -s --user "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" \
            "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}/ping" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
    return 1
}

restart_clickhouse() {
    echo "Restarting ClickHouse to apply changes and reclaim disk space..."
    cd "$SERVICE_DIR"
    docker compose -f "$COMPOSE_FILE" restart langfuse-clickhouse >/dev/null 2>&1

    echo "Waiting for ClickHouse to be ready..."
    if ! wait_for_clickhouse; then
        echo "ERROR: ClickHouse failed to restart"
        exit 1
    fi
    echo "ClickHouse restarted successfully."
}

setup_ttl_policies() {
    local data_tables=("traces:timestamp:21" "observations:created_at:21" "scores:timestamp:21")

    for table_info in "${data_tables[@]}"; do
        local table="${table_info%%:*}"
        local time_column=$(echo "$table_info" | cut -d: -f2)
        local days=$(echo "$table_info" | cut -d: -f3)

        local table_exists=$(execute_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB}' AND name='${table}'" 2>/dev/null || echo "0")
        if [ "$table_exists" = "0" ]; then continue; fi

        execute_query "ALTER TABLE ${table} MODIFY TTL ${time_column} + INTERVAL ${days} DAY" >/dev/null 2>&1 || true
    done
}

cleanup_logs() {
    echo "Cleaning ClickHouse log files..."
    docker exec "$CONTAINER_NAME" sh -c 'find /var/log/clickhouse-server -name "*.log.*" -delete' 2>/dev/null || true
    docker exec "$CONTAINER_NAME" sh -c 'truncate -s 0 /var/log/clickhouse-server/*.log' 2>/dev/null || true
}

show_disk_usage() {
    echo "Disk usage:"
    docker system df -v | grep -E "langfuse.*clickhouse" || true
    docker exec "$CONTAINER_NAME" du -sh /var/lib/clickhouse 2>/dev/null || echo "Cannot access container"
    echo ""
    echo "Log directory:"
    docker exec "$CONTAINER_NAME" du -sh /var/log/clickhouse-server 2>/dev/null || echo "Cannot access logs"
}

setup_mode() {
    echo "=== Langfuse ClickHouse Setup & Optimization ==="

    if ! wait_for_clickhouse; then
        echo "ERROR: ClickHouse not accessible"
        exit 1
    fi

    echo ""
    echo "Step 1: Disable resource-intensive system logging"
    disable_system_logging

    echo ""
    echo "Step 2: Clean existing bloat"
    cleanup_system_tables
    cleanup_logs

    echo ""
    echo "Step 3: Setup TTL policies for Langfuse data"
    setup_ttl_policies

    echo ""
    echo "Step 4: Force cleanup"
    force_ttl_cleanup

    echo ""
    echo "Step 5: Restart ClickHouse to apply configuration"
    restart_clickhouse

    echo ""
    echo "=== Setup Complete ==="
    show_disk_usage
}

deep_clean() {
    echo "=== Deep Clean Mode ==="
    echo "This will:"
    echo "  1. Apply/update system logging configuration"
    echo "  2. DROP bloated system tables"
    echo "  3. Clean all log files"
    echo "  4. Force TTL cleanup on Langfuse data"
    echo "  5. Restart ClickHouse to reclaim disk space"
    echo ""

    if ! wait_for_clickhouse; then
        echo "ERROR: ClickHouse not accessible"
        exit 1
    fi

    echo "Before cleanup:"
    show_disk_usage
    echo ""

    echo "Applying system logging configuration..."
    disable_system_logging

    echo ""
    cleanup_system_tables
    cleanup_logs
    force_ttl_cleanup
    setup_ttl_policies

    echo ""
    restart_clickhouse

    echo ""
    echo "After cleanup:"
    show_disk_usage

    echo ""
    echo "✓ Deep clean completed"
}

update_containers() {
    echo "=== Update Langfuse Containers ==="
    echo ""
    echo "This will:"
    echo "  1. Pull latest images for all Langfuse services"
    echo "  2. Recreate containers with new images"
    echo "  3. Preserve all data volumes"
    echo ""

    cd "$SERVICE_DIR"

    echo "Current image versions:"
    docker compose -f "$COMPOSE_FILE" images 2>/dev/null || true
    echo ""

    echo "Pulling latest images..."
    if ! docker compose -f "$COMPOSE_FILE" pull; then
        echo "ERROR: Failed to pull images"
        exit 1
    fi
    echo ""

    echo "Recreating containers with new images..."
    if ! docker compose -f "$COMPOSE_FILE" up -d; then
        echo "ERROR: Failed to start containers"
        exit 1
    fi
    echo ""

    echo "Waiting for services to be healthy..."
    sleep 5

    echo ""
    echo "Updated image versions:"
    docker compose -f "$COMPOSE_FILE" images 2>/dev/null || true
    echo ""

    echo "Service status:"
    docker compose -f "$COMPOSE_FILE" ps 2>/dev/null || true
    echo ""

    echo "✓ Update completed"
    echo ""
    echo "Note: Run '$0 --setup' if this is a major version upgrade to reconfigure TTLs"
}

main() {
    if ! curl -s --user "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" \
        "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}/ping" >/dev/null; then
        echo "ERROR: ClickHouse not accessible"
        exit 1
    fi

    show_disk_usage
    show_table_sizes
    cleanup_system_tables
    cleanup_logs
    force_ttl_cleanup
    echo "Cleanup completed."
    show_table_sizes
    show_disk_usage
}

# Parse arguments
case "${1:-}" in
    --setup)
        setup_mode
        ;;
    --deep-clean)
        deep_clean
        ;;
    --update)
        update_containers
        ;;
    --tables-only)
        show_table_sizes
        ;;
    --disk-usage)
        show_disk_usage
        ;;
    --trace-cost)
        if [ -z "$2" ]; then
            echo "Error: --trace-cost requires a trace ID"
            echo "Usage: $0 --trace-cost <trace_id>"
            exit 1
        fi
        show_trace_cost "$2"
        ;;
    --help|-h)
        echo "Langfuse ClickHouse Maintenance Script"
        echo ""
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  --setup              Initial setup: disable bloated system tables, configure TTLs,"
        echo "                       and restart ClickHouse. Run once after starting Langfuse."
        echo "  --deep-clean         Full cleanup: apply config, drop bloated system tables,"
        echo "                       clean logs, and restart ClickHouse to reclaim disk space."
        echo "  --update             Pull latest images and recreate containers"
        echo "  --tables-only        Show table sizes"
        echo "  --disk-usage         Show disk usage"
        echo "  --trace-cost <id>    Show cost breakdown for specific trace"
        echo "  (no args)            Regular maintenance cleanup (no restart)"
        ;;
    *)
        main
        ;;
esac

