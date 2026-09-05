"""The backup command: dump the database to HINDSIGHT_BACKUP_DIR."""
import os
import subprocess

from . import shell


def run(cfg, if_stale):
    shell.require_local_mode(cfg)
    if not cfg.backup_dir:
        print("  ℹ️  HINDSIGHT_BACKUP_DIR is not set, so there is nowhere to write.")
        print("  Configure it: atk setup hindsight")
        return 0
    shell.require_backup_dir(cfg)
    if if_stale and shell.dumps_are_fresh(cfg):
        return 0
    try:
        return run_backup(cfg)
    except BaseException:
        shell.notify("Hindsight backup FAILED",
                     "Check: atk run hindsight schedule status")
        raise


def run_backup(cfg):
    shell.require_service_running()
    print("=== Hindsight Backup ===")

    with shell.backup_lock(cfg):
        for stale in shell.partial_paths(cfg):
            os.remove(stale)
            print("  Removed a leftover partial: %s" % os.path.basename(stale))

        version = shell.server_version(cfg)
        if not version:
            shell.warn("Could not read the Hindsight version; naming the dump "
                       "'unknown'.")
            version = "unknown"
        dump_file = os.path.join(cfg.backup_dir,
                                 shell.dump_name(version, shell.now()))
        partial_file = dump_file + ".partial"
        try:
            pg = shell.PgInstance(shell.pg_instance_from_container())
            with open(partial_file, "wb") as fh:
                shell.run(["docker", "exec", "-e", "PGPASSWORD=" + pg.password,
                           "hindsight", os.path.join(pg.bin_dir, "pg_dump"),
                           "-h", "localhost", "-p", pg.port, "-U", pg.user,
                           "-d", pg.database, "-Fc"],
                          stdout=fh, check=True)

            # The dump becomes a backup only once its table of contents reads back.
            shell.run(["docker", "cp", partial_file, "hindsight:/tmp/toc-check.dump"],
                      stdout=subprocess.DEVNULL, check=True)
            shell.run(["docker", "exec", "-e", "LD_LIBRARY_PATH=" + pg.lib_dir,
                       "hindsight", os.path.join(pg.bin_dir, "pg_restore"),
                       "--list", "/tmp/toc-check.dump"],
                      stdout=subprocess.DEVNULL, check=True)
            shell.run(["docker", "exec", "-u", "root", "hindsight",
                       "rm", "-f", "/tmp/toc-check.dump"], check=True)

            os.replace(partial_file, dump_file)
            for path in shell.prune_selection(shell.dump_paths(cfg)):
                os.remove(path)
                print("  Pruned %s" % os.path.basename(path))
            print("  ✅ %s (%s)" % (dump_file, shell.human_size(dump_file)))
            return 0
        finally:
            try:
                os.remove(partial_file)
            except OSError:
                pass
