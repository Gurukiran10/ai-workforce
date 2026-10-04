"""Run the sandbox company: python -m sandbox [--port 8000]"""
import argparse

import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
uvicorn.run("sandbox.app:app", host="127.0.0.1", port=args.port, log_level="warning")
