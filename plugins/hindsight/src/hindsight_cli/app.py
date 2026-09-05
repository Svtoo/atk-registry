"""Typer application: argument parsing, dispatch, and the process entry point.
The .sh wrappers load .env and exec the hindsight-cli console script."""
import os
import signal
import subprocess
import sys
from typing import List, Optional

import click
import typer

from . import (backup, banks, config, lifecycle, mental_models, restore,
               schedule)

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
mm_app = typer.Typer(add_completion=False)
app.add_typer(mm_app, name="mental-models")


@app.callback()
def _root(ctx: typer.Context):
    """Manage the hindsight memory service."""
    ctx.obj = config.Config(os.environ)


@app.command("backup")
def backup_command(ctx: typer.Context,
                   if_stale: bool = typer.Option(False, "--if-stale")):
    return backup.run(ctx.obj, if_stale)


@app.command("restore")
def restore_command(ctx: typer.Context,
                    dump_file: Optional[str] = typer.Argument(None)):
    return restore.run(ctx.obj, dump_file)


@app.command("schedule")
def schedule_command(ctx: typer.Context, verb: str = typer.Argument("")):
    return schedule.run(ctx.obj, verb)


@app.command("service")
def service_command(ctx: typer.Context, verb: str = typer.Argument("")):
    return lifecycle.service(ctx.obj, verb)


@app.command("install")
def install_command(ctx: typer.Context):
    return lifecycle.install(ctx.obj)


@app.command("uninstall")
def uninstall_command(ctx: typer.Context):
    return lifecycle.uninstall(ctx.obj)


@app.command("banks")
def banks_command(ctx: typer.Context,
                  verb: str = typer.Argument("list"),
                  names: List[str] = typer.Argument(None)):
    return banks.run(ctx.obj, verb, list(names or ()))


@mm_app.callback(invoke_without_command=True)
def mental_models_group(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        return mental_models.list_models(ctx.obj)


@mm_app.command("list")
def mental_models_list(ctx: typer.Context):
    return mental_models.list_models(ctx.obj)


@mm_app.command("show")
def mental_models_show(ctx: typer.Context,
                       model_id: str = typer.Argument(...)):
    return mental_models.show(ctx.obj, model_id)


@mm_app.command("create")
def mental_models_create(ctx: typer.Context,
                         model_id: str = typer.Argument(...),
                         query: Optional[str] = typer.Option(None, "--query"),
                         name: Optional[str] = typer.Option(None, "--name"),
                         cron: Optional[str] = typer.Option(None, "--cron"),
                         max_tokens: int = typer.Option(800, "--max-tokens")):
    """Create a mental model.

    One model = one question about one dimension. Write an open question
    naming the subject and its boundary ("exclude X"); never enumerate the
    answer. Keep scopes disjoint. 600-800 tokens.
    """
    return mental_models.create(ctx.obj, model_id, query, name, cron, max_tokens)


@mm_app.command("set")
def mental_models_set(ctx: typer.Context,
                      model_id: str = typer.Argument(...),
                      query: Optional[str] = typer.Option(None, "--query"),
                      cron: Optional[str] = typer.Option(None, "--cron"),
                      mode: Optional[str] = typer.Option(None, "--mode"),
                      max_tokens: Optional[int] = typer.Option(
                          None, "--max-tokens"),
                      keep_trace: Optional[bool] = typer.Option(
                          None, "--keep-trace/--no-keep-trace")):
    return mental_models.set_options(
        ctx.obj, model_id, query, cron, mode, max_tokens, keep_trace)


@mm_app.command("refresh")
def mental_models_refresh(ctx: typer.Context,
                          model_id: str = typer.Argument(...)):
    return mental_models.refresh(ctx.obj, model_id)


@mm_app.command("dry-run")
def mental_models_dry_run(ctx: typer.Context,
                          model_id: str = typer.Argument(...),
                          as_json: bool = typer.Option(False, "--json")):
    """Print the diff a refresh would write, without writing it; paid like a refresh."""
    return mental_models.dry_run(ctx.obj, model_id, as_json)


@mm_app.command("audit")
def mental_models_audit(ctx: typer.Context):
    """Raw data per model, then hints; exits 1 when any hint fires."""
    return mental_models.audit(ctx.obj)


@mm_app.command("review")
def mental_models_review(ctx: typer.Context,
                         model_ids: list[str] = typer.Argument(None)):
    """Data plus the restructuring playbook, for some models or all.

    Free, local reads. Run it when audit flags a model. Prints a stat and
    query block per reviewed model, the remaining models' queries for
    overlap and split judgment, and the playbook that orders the fixes,
    once. No ids reviews every model.
    """
    return mental_models.review(ctx.obj, list(model_ids or []))


@mm_app.command("rebuild")
def mental_models_rebuild(ctx: typer.Context,
                          model_id: str = typer.Argument(...),
                          yes: bool = typer.Option(
                              False, "--yes",
                              help="Skip the prompt; consent came from the"
                                   " conversation.")):
    """Clear a model and regenerate it from the whole bank.

    Only for drift: a document shaped by many delta refreshes that no
    longer matches what a fresh build would say. A freshly rebuilt model
    that is still over budget has a query or budget problem, and
    rebuilding again reproduces it. Paid.
    """
    return mental_models.rebuild(ctx.obj, model_id, yes=yes)


@mm_app.command("delete")
def mental_models_delete(ctx: typer.Context,
                         model_id: str = typer.Argument(...),
                         yes: bool = typer.Option(
                             False, "--yes",
                             help="Skip the prompt; consent came from the"
                                  " conversation.")):
    return mental_models.delete(ctx.obj, model_id, yes=yes)


def _terminate(signum, frame):
    raise SystemExit(128 + signum)


def main(argv):
    # SystemExit runs the finally blocks that release locks, remove partial
    # dumps and stop the maintenance container; a raw SIGTERM would not.
    signal.signal(signal.SIGTERM, _terminate)
    try:
        result = app(args=list(argv), standalone_mode=False,
                     prog_name="hindsight-cli")
        return result if isinstance(result, int) else 0
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.exceptions.Abort:
        # click echoes a blank line before turning Ctrl-C into Abort.
        return 130
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except subprocess.CalledProcessError as error:
        stderr = error.stderr
        if stderr:
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            sys.stderr.write(stderr if stderr.endswith("\n") else stderr + "\n")
        print("  ❌ Command failed (exit %s): %s"
              % (error.returncode, " ".join(error.cmd)), file=sys.stderr)
        code = error.returncode
        return 128 - code if code < 0 else (code or 1)
    except FileNotFoundError as error:
        print("  ❌ %s" % error, file=sys.stderr)
        return 1


def run():
    # A closed pipe (e.g. | head) should end the process the way it ends any
    # shell tool, not raise BrokenPipeError.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    # Line buffering keeps the launchd log chronological when stdout is a file.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    sys.exit(main(sys.argv[1:]))
