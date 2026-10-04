"""Render a local PDF page in an isolated process for the HTML preview."""
import json
import sys

import pymupdf

with pymupdf.open(sys.argv[1]) as document:
    if sys.argv[2] == "info":
        print(json.dumps({"pages": len(document)}))
    else:
        number = int(sys.argv[2])
        if not 1 <= number <= len(document):
            raise SystemExit("Page is out of range")
        sys.stdout.buffer.write(document[number - 1].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False).tobytes("png"))
