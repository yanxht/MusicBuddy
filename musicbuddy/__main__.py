"""Command line: python -m musicbuddy <command>."""
import argparse
import logging
import os


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="musicbuddy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="scan the input folder once; upload + enqueue new/changed lessons")
    w.add_argument("--input", default=None)
    w.add_argument("--force", action="store_true")
    p = sub.add_parser("process", help="process a lesson locally (raw files must be uploaded)")
    p.add_argument("date")
    p.add_argument("--keep", action="store_true", help="keep the local work folder")
    e = sub.add_parser("enqueue", help="queue a lesson for the cloud worker")
    e.add_argument("date")
    sub.add_parser("worker", help="run the queue worker in the foreground")
    d = sub.add_parser("delete", help="delete a lesson's raw files, outputs and index entry")
    d.add_argument("date")
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    s.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    if args.cmd == "watch":
        from . import ingest
        print("queued:", ingest.scan(args.input, force=args.force) or "nothing new")
    elif args.cmd == "process":
        from .pipeline import run
        run.process(args.date, keep_work=args.keep)
    elif args.cmd == "enqueue":
        from . import storage
        storage.enqueue(args.date, "manual")
    elif args.cmd == "worker":
        from . import worker
        worker.loop()
    elif args.cmd == "delete":
        from . import config, storage
        if not args.date.isdigit() or len(args.date) != 8:
            raise SystemExit("date must be YYYYMMDD")
        for cname in (config.RAW_CONTAINER, config.DATA_CONTAINER):
            for b in storage.list_blobs(cname, f"{args.date}/"):
                storage.container(cname).delete_blob(b.name)
        index = storage.get_json(config.DATA_CONTAINER, "index.json", {"lessons": []})
        index["lessons"] = [l for l in index["lessons"] if l["date"] != args.date]
        storage.put_json(config.DATA_CONTAINER, "index.json", index)
        print("deleted", args.date)
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("musicbuddy.web.app:app", host="0.0.0.0", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
