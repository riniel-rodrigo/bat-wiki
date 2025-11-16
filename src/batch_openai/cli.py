import argparse
from typing import Optional

from .services.batch_service import submit, wait, download, status
from .parsers.output_parser import parse as parse_outputs


def run(
    input_path: str,
    job_name: Optional[str],
    completion_window: str,
    poll_interval: int,
    do_parse: bool,
) -> None:
    batch_id = submit(input_path, job_name, completion_window)
    wait(batch_id, poll_interval=poll_interval)
    download(batch_id)
    if do_parse:
        parse_outputs(batch_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="batch_openai", description="Batch API (OpenAI)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("input_path")
    p_submit.add_argument("--job-name", default=None)
    p_submit.add_argument("--completion-window", default="24h")
    p_submit.set_defaults(func=lambda a: print(submit(a.input_path, a.job_name, a.completion_window)))

    p_wait = sub.add_parser("wait")
    p_wait.add_argument("batch_id")
    p_wait.add_argument("--poll-interval", type=int, default=10)
    p_wait.set_defaults(func=lambda a: wait(a.batch_id, a.poll_interval))

    p_download = sub.add_parser("download")
    p_download.add_argument("batch_id")
    p_download.set_defaults(func=lambda a: download(a.batch_id))

    p_status = sub.add_parser("status")
    p_status.add_argument("batch_id")
    p_status.add_argument("--json", action="store_true", dest="json_output")
    p_status.set_defaults(func=lambda a: status(a.batch_id, a.json_output))

    p_parse = sub.add_parser("parse")
    p_parse.add_argument("batch_id")
    p_parse.set_defaults(func=lambda a: parse_outputs(a.batch_id))

    p_run = sub.add_parser("run")
    p_run.add_argument("input_path")
    p_run.add_argument("--job-name", default=None)
    p_run.add_argument("--completion-window", default="24h")
    p_run.add_argument("--poll-interval", type=int, default=10)
    p_run.add_argument("--parse", action="store_true")
    p_run.set_defaults(
        func=lambda a: run(
            a.input_path, a.job_name, a.completion_window, a.poll_interval, a.parse
        )
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
