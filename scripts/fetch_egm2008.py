"""Fetch the public PROJ EGM2008 grid with validated, retryable byte ranges."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://cdn.proj.org/us_nga_egm08_25.tif"
SIZE = 80585622
CHUNK = 2*1024*1024


def fetch(start):
    stop = min(start+CHUNK,SIZE)-1
    error = None
    for attempt in range(3):
        try:
            req = Request(URL, headers={"Range":f"bytes={start}-{stop}"})
            with urlopen(req,timeout=30) as response:
                if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{stop}/{SIZE}":
                    raise ValueError("server did not return the requested byte range")
                data = response.read(stop-start+2)
                if len(data) != stop-start+1:
                    raise ValueError("incomplete geoid chunk")
                return data
        except Exception as exc:
            error = exc
    raise RuntimeError(f"range {start}-{stop} failed") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary = args.output.with_suffix(".download")
    digest = hashlib.sha256()
    with ThreadPoolExecutor(max_workers=4) as pool, temporary.open("wb") as stream:
        for index, data in enumerate(pool.map(fetch,range(0,SIZE,CHUNK))):
            stream.write(data)
            digest.update(data)
            if index%5 == 0:
                print(f"downloaded {stream.tell()}/{SIZE} bytes",flush=True)
    if temporary.stat().st_size != SIZE:
        raise ValueError("geoid file size mismatch")
    temporary.replace(args.output)
    print(f"sha256:{digest.hexdigest()}",flush=True)


if __name__ == "__main__":
    main()
