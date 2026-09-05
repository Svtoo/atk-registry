"""The schedule command: the launchd job that keeps daily backups fresh."""
import os
import sys

from . import shell

SCHEDULE_LABEL = "com.atk.hindsight-backup"
SCHEDULE_LOG = "Library/Logs/atk-hindsight-backup.log"


def job_target():
    return "gui/%d/%s" % (os.getuid(), SCHEDULE_LABEL)


def plist_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                        SCHEDULE_LABEL + ".plist")


def job_loaded():
    return shell.run(["launchctl", "print", job_target()],
                     capture_output=True, check=False).returncode == 0


def remove_job():
    """Boot the job out and delete its plist; True when either existed."""
    removed = False
    if job_loaded():
        shell.run(["launchctl", "bootout", job_target()], check=True)
        removed = True
    if os.path.exists(plist_path()):
        os.remove(plist_path())
        removed = True
    return removed


def run(cfg, verb):
    # launchd is the whole mechanism here, so there is nothing to degrade to.
    if sys.platform != "darwin":
        shell.die("The backup schedule is macOS only, and this is %s." % sys.platform,
                  "Run 'atk run hindsight backup --if-stale' hourly from cron "
                  "or a systemd timer instead.")
    domain = "gui/%d" % os.getuid()
    target = job_target()
    plist = plist_path()
    log_path = os.path.join(os.path.expanduser("~"), SCHEDULE_LOG)

    def show_status():
        if job_loaded():
            print("  Job: loaded (%s; wakes hourly, dumps once the newest"
                  " backup is a day old)" % SCHEDULE_LABEL)
        else:
            print("  Job: not installed")
        newest = shell.newest_dump(cfg) if cfg.backup_dir else None
        if newest:
            print("  Newest backup: %s (%s)"
                  % (os.path.basename(newest), shell.human_size(newest)))
        else:
            print("  Newest backup: none")
        if os.path.isfile(log_path) and os.path.getsize(log_path):
            print("  Log: %s" % log_path)
            with open(log_path) as fh:
                for line in fh.read().splitlines()[-3:]:
                    print("    %s" % line)

    print("=== Hindsight Backup Schedule ===")
    verb = verb or "on"
    if verb == "on":
        shell.require_local_mode(cfg)
        if not cfg.backup_dir:
            shell.die("HINDSIGHT_BACKUP_DIR is not set.",
                      "Configure it: atk setup hindsight")
        os.makedirs(os.path.dirname(plist), exist_ok=True)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(plist, "w") as fh:
            fh.write(shell.render_plist(SCHEDULE_LABEL, cfg.plugin_dir, log_path))
        if job_loaded():
            shell.run(["launchctl", "bootout", target], check=True)
        shell.run(["launchctl", "bootstrap", domain, plist], check=True)
        show_status()
    elif verb == "off":
        remove_job()
        print("  Schedule removed.")
    elif verb == "status":
        show_status()
    else:
        shell.die("Unknown argument: %s" % verb, "Usage: schedule [off|status]")
    return 0
