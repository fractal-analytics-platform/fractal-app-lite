import argparse

import uvicorn

from backend.main import app

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8765)
args, _ = parser.parse_known_args()

uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
