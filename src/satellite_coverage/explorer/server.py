"""Loopback-only JSON API with file browsing and background orbit jobs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

from ..data_sources.dem_preview import dem_info, dem_preview
from ..orbit.visibility import calculate_visibility, parse_catalog, request_parameters, satellite_track, utc


PROJECT = Path(__file__).resolve().parents[3]


class Explorer:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve()
        if not self.root.is_dir():
            raise ValueError("数据根目录不存在")
        self.catalogs, self.jobs = {}, {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="visibility")
        self.lock = threading.Lock()
        package = Path(__file__).resolve().parents[1]
        self.source_hashes = {
            str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*"))
            if path.is_file() and path.suffix in (".py", ".html", ".js", ".css")
        }

    def path(self, value, kind=None):
        path = Path(value).expanduser()
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"文件必须位于数据根目录 {self.root} 内")
        if kind and (not path.is_file() or path.suffix.lower() not in ({".tle", ".txt"} if kind == "tle" else {".tif", ".tiff"})):
            raise ValueError("文件不存在或扩展名不支持")
        return path

    def browse(self, value, kind):
        folder = self.path(value or str(self.root))
        if not folder.is_dir():
            folder = folder.parent
        extensions = {".tle", ".txt"} if kind == "tle" else {".tif", ".tiff"}
        entries = []
        for item in folder.iterdir():
            if item.name.startswith(".") or not item.resolve().is_relative_to(self.root):
                continue
            if item.is_dir() or item.suffix.lower() in extensions:
                entries.append({"name": item.name, "path": str(item), "directory": item.is_dir()})
        return {"path": str(folder), "parent": str(folder.parent) if folder != self.root else None,
                "entries": sorted(entries, key=lambda item: (not item["directory"], item["name"]))}

    def defaults(self):
        data = self.root / "Satellite-Ground-Radiomap/data"
        if not data.exists():
            data = self.root
        tle = data / "starlink-2025-tle/2025-01-01.tle"
        dem = data / "l2_topo/china_dem_30.tif"
        return {"data_root": str(self.root), "tle_path": str(tle) if tle.exists() else "",
                "dem_path": str(dem) if dem.exists() else "", "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-01T02:00:00Z", "lon": 108.9016839, "lat": 34.2427189}

    def load_catalog(self, data):
        if "text" in data:
            raw = data["text"].encode("utf-8")
            name = str(data.get("name", "uploaded.tle"))
        else:
            path = self.path(data.get("path", ""), "tle")
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("TLE 文件不得超过 32 MiB")
            raw, name = path.read_bytes(), path.name
        catalog = parse_catalog(raw)
        summary = catalog.summary()
        with self.lock:
            if len(self.catalogs) >= 8:
                self.catalogs.pop(next(iter(self.catalogs)))
            self.catalogs[catalog.checksum] = catalog
        start = utc(summary["epoch_start"]).replace(hour=0, minute=0, second=0, microsecond=0)
        return {**summary, "catalog_id": catalog.checksum, "filename": name,
                "suggested_start": start.isoformat().replace("+00:00", "Z"),
                "suggested_end": (start + timedelta(hours=2)).isoformat().replace("+00:00", "Z")}

    def submit(self, data):
        request_parameters(data)
        catalog = self.catalogs.get(data.get("catalog_id"))
        if catalog is None:
            raise ValueError("请先解析 TLE 文件")
        with self.lock:
            if any(j["state"] in ("queued", "running") for j in self.jobs.values()):
                raise ValueError("已有计算正在进行，请等待完成或取消")
            while len(self.jobs) >= 8:
                self.jobs.pop(next(iter(self.jobs)))
            job_id = secrets.token_hex(8)
            job = {"state": "queued", "progress": 0, "total": 0, "window_count": 0,
                   "cancel": threading.Event(), "request": data, "catalog": catalog, "started": time.monotonic()}
            self.jobs[job_id] = job
        def work():
            job["state"] = "running"
            def progress(done, total, windows):
                job.update(progress=done, total=total, window_count=windows)
            try:
                result = calculate_visibility(catalog, data, progress, job["cancel"].is_set)
                result["source_files_sha256_at_server_start"] = self.source_hashes
                job.update(result=result, state="done", elapsed_s=time.monotonic() - job["started"])
            except InterruptedError:
                job["state"] = "cancelled"
            except Exception as exc:
                job.update(state="failed", error=str(exc))
        self.pool.submit(work)
        return {"job_id": job_id}

    def job(self, job_id):
        if job_id not in self.jobs:
            raise ValueError("任务不存在或已从内存释放，请重新计算")
        return self.jobs[job_id]


def handler_class(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, status, payload, kind="application/json; charset=utf-8"):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if kind.startswith("application/json") else payload
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            host = self.headers.get("Host", "")
            if host not in (f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"):
                self.send(403, {"error": "请通过 localhost 或 127.0.0.1 访问"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                self.send(403, {"error": "不接受跨站请求"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                if parsed.path in ("/", "/api/health"):
                    self.send(200, {"service": "satellite-coverage-sim", "api_version": 1,
                                    "status": "ready", "frontend": "separate satellite-coverage-demo project"})
                elif parsed.path == "/api/defaults":
                    self.send(200, app.defaults())
                elif parsed.path == "/api/browse":
                    self.send(200, app.browse(params.get("path", [""])[0], params.get("kind", ["tle"])[0]))
                elif parsed.path == "/api/job":
                    job = app.job(params.get("id", [""])[0])
                    self.send(200, {k: v for k, v in job.items() if k not in ("catalog", "cancel", "started", "request")})
                else:
                    self.send(404, {"error": "未知地址"})
            except Exception as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                if self.headers.get("X-Explorer") != "1":
                    raise ValueError("缺少应用请求头")
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 40 * 1024 * 1024:
                    raise ValueError("请求大小无效，最大 40 MiB")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求必须是 JSON 对象")
                route = urlparse(self.path).path
                if route == "/api/catalog":
                    result = app.load_catalog(data)
                elif route == "/api/visibility":
                    result = app.submit(data)
                elif route == "/api/cancel":
                    app.job(data["job_id"])["cancel"].set()
                    result = {"status": "cancel_requested"}
                elif route == "/api/track":
                    job = app.job(data["job_id"])
                    if job["state"] != "done" or data["norad_id"] not in {s["norad_id"] for s in job["result"]["satellites"]}:
                        raise ValueError("只能查看已成功计算卫星的轨迹")
                    result = satellite_track(job["catalog"], job["request"], data["norad_id"], data.get("point_index", 0))
                elif route == "/api/dem-info":
                    result = dem_info(app.path(data["path"], "dem"))
                elif route == "/api/dem":
                    result = dem_preview(app.path(data["path"], "dem"), data["bounds"], data.get("size", 384))
                else:
                    self.send(404, {"error": "未知接口"})
                    return
                self.send(200, result)
            except Exception as exc:
                self.send(400, {"error": str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="TLE 可见窗口与 DEM JSON API（独立前端另行启动）")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-root", type=Path, default=PROJECT.parent)
    args = parser.parse_args()
    app = Explorer(args.data_root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_class(app))
    print(f"Satellite API: http://127.0.0.1:{server.server_port}\n数据根目录：{app.root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in app.jobs.values():
            job["cancel"].set()
        server.server_close()
        app.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
