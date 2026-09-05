"""The banks command: list memory banks or delete them permanently."""
import json

from . import client, shell


def run(cfg, verb, names):
    if verb == "list":
        try:
            body = client.http("GET", cfg.url + "/v1/default/banks", timeout=30)
        except Exception as error:
            shell.die("Cannot reach Hindsight at %s: %s" % (cfg.url, error),
                      "Is the service running? atk start hindsight")
        data = json.loads(body)
        banks = data["banks"]
        if not banks:
            print("no banks")
            return 0
        width = max(len(bank["bank_id"]) for bank in banks)
        for bank in sorted(banks, key=lambda b: -b["fact_count"]):
            mark = "  <- this agent" if bank["bank_id"] == cfg.bank else ""
            print("%8d  %-*s  %s%s" % (bank["fact_count"], width, bank["bank_id"],
                                       bank["last_write_at"] or "never written",
                                       mark))
        return 0
    if verb == "delete":
        if not names:
            shell.die("usage: banks delete <bank> [bank...]")
        print("  Deleting permanently: %s" % " ".join(names))
        for bank in names:
            if not shell.confirm("Delete '%s' and everything in it?" % bank):
                shell.die("Aborted — nothing deleted.")
            try:
                client.http("DELETE", "%s/v1/default/banks/%s" % (cfg.url, bank),
                            timeout=60)
            except Exception:
                shell.die("Failed to delete '%s'." % bank,
                          "Nothing further was attempted.")
            print("  ✓ deleted %s" % bank)
        return 0
    shell.die("usage: banks [list|delete <bank>...]")
