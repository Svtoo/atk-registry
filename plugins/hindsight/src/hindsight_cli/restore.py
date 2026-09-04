"""The restore command: replace the database from a backup dump."""
import os
import subprocess
import sys

from . import shell

HELPER = "hindsight-restore"
READY_PROBES = 31


def maintenance_pg(pg, tool, *args, **kwargs):
    """Runs an embedded-postgres client tool against the maintenance server.
    Server NOTICE chatter (e.g. from DROP ... IF EXISTS) reads like a failure
    in the restore output, so the session mutes everything below warning."""
    return shell.run(
        ["docker", "exec", "-e", "PGPASSWORD=" + pg.password,
         "-e", "PGOPTIONS=-c client_min_messages=warning",
         "-e", "LD_LIBRARY_PATH=" + pg.lib_dir, HELPER,
         os.path.join(pg.bin_dir, tool),
         "-h", "localhost", "-p", pg.port, "-U", pg.user] + list(args),
        **kwargs)


def sql(pg, statement):
    return maintenance_pg(pg, "psql", "-d", "postgres", "-q",
                          "-v", "ON_ERROR_STOP=1", "-c", statement, check=True)


def run(cfg, restore_file):
    shell.require_local_mode(cfg)
    shell.require_backup_dir(cfg)
    shell.require_volume(cfg)

    if restore_file is None:
        restore_file = shell.newest_dump(cfg)
    if not restore_file or not os.path.isfile(restore_file):
        shell.die("No dump found.",
                  "Looked for %s*.dump in %s" % (shell.DUMP_PREFIX, cfg.backup_dir))

    print("=== Hindsight Restore ===")
    print("  Source: %s (%s)" % (restore_file, shell.human_size(restore_file)))
    images = shell.compose(cfg, "config", "--images", stdout=subprocess.PIPE,
                           text=True, check=True).stdout.split()
    if not images:
        shell.die("docker compose reports no image for the service.")
    image = images[0]
    pg = shell.PgInstance(shell.pg_instance_from_volume(cfg, image))
    incoming = pg.database + "_incoming"
    previous = pg.database + "_previous"
    print("  Target: database '%s' in volume '%s'." % (pg.database, cfg.volume_name))
    print("  The backup restores into '%s' first; the live database" % incoming)
    print("  is replaced only after that restore completes cleanly.")
    if not shell.confirm("Proceed?"):
        print("  Aborted — nothing changed.")
        return 0

    shell.stop_services(cfg)
    shell.run(["docker", "rm", "-f", HELPER], capture_output=True, check=False)
    # A bulk HNSW index build allocates hundreds of MB of dynamic shared
    # memory; Docker's default 64MB /dev/shm fails it.
    shell.run(["docker", "run", "-d", "--name", HELPER, "--shm-size=1g",
               "-e", "LD_LIBRARY_PATH=" + pg.lib_dir,
               "-v", "%s:%s" % (cfg.volume_name, shell.PG_ROOT),
               "--entrypoint", os.path.join(pg.bin_dir, "postgres"), image,
               "-D", pg.data_dir, "-p", pg.port],
              stdout=subprocess.DEVNULL, check=True)
    try:
        ready = False
        for _ in range(READY_PROBES):
            probe = maintenance_pg(pg, "pg_isready", "-q",
                                   stderr=subprocess.DEVNULL, check=False)
            if probe.returncode == 0:
                ready = True
                break
            shell.sleep(1)
        if not ready:
            logs = shell.run(["docker", "logs", HELPER],
                             capture_output=True, text=True, check=False)
            tail = (logs.stdout + logs.stderr).splitlines()[-5:]
            for line in tail:
                print(line, file=sys.stderr)
            shell.die("The maintenance server did not come up.")

        # Copied in from the host: container-mount reads of the cloud-synced
        # backup folder can hit EOF while the folder is syncing.
        shell.run(["docker", "cp", restore_file, HELPER + ":/tmp/restore.dump"],
                  stdout=subprocess.DEVNULL, check=True)

        sql(pg, "DROP DATABASE IF EXISTS %s" % incoming)
        sql(pg, "CREATE DATABASE %s" % incoming)
        maintenance_pg(pg, "pg_restore", "-d", incoming, "--exit-on-error",
                       "/tmp/restore.dump", check=True)

        # The live database is untouched up to here; a failed restore only
        # ever leaves an _incoming to drop.
        sql(pg, "DROP DATABASE IF EXISTS %s" % previous)
        sql(pg, "ALTER DATABASE %s RENAME TO %s" % (pg.database, previous))
        try:
            sql(pg, "ALTER DATABASE %s RENAME TO %s" % (incoming, pg.database))
        except BaseException:
            sql(pg, "ALTER DATABASE %s RENAME TO %s" % (previous, pg.database))
            raise
        sql(pg, "DROP DATABASE %s" % previous)
    finally:
        shell.run(["docker", "rm", "-f", HELPER], capture_output=True, check=False)

    shell.start_services(cfg, os.environ)
    if not shell.wait_healthy(cfg):
        shell.die("Restored, but the API is not healthy.", "Check: atk logs hindsight")
    print("  ✅ Restored")
    return 0
