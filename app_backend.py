"""Shared CLI / bundled bootstrap. stdout is reserved for the READY protocol."""
import argparse
import asyncio
import json
import os
import socket
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed", action="store_true", help="Stop on parent control-pipe EOF")
    args = parser.parse_args()
    protocol_output = sys.stdout
    sys.stdout = sys.stderr
    from app.runtime import acquire_backend_lock, INSTANCE_ID, PROTOCOL_VERSION, update_lock_port
    try:
        acquire_backend_lock()
        import uvicorn
        from app.main import app

        async def serve():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.setblocking(False)
                port = listener.getsockname()[1]
                update_lock_port(port)
                server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", timeout_graceful_shutdown=2))
                parent_closed = threading.Event()
                if args.managed:
                    def watch_parent():
                        try:
                            while sys.stdin.buffer.read(1):
                                pass
                        finally:
                            parent_closed.set()
                    threading.Thread(target=watch_parent, daemon=True).start()

                async def monitor():
                    announced = False
                    while not server.should_exit:
                        if args.managed and parent_closed.is_set():
                            server.should_exit = True
                            return
                        if server.started and not announced:
                            payload = {"protocol_version": PROTOCOL_VERSION, "port": port,
                                       "instance_id": INSTANCE_ID, "pid": os.getpid(),
                                       "nonce": os.environ.get("GODOX_STARTUP_NONCE", "")}
                            protocol_output.write("GODOX_READY " + json.dumps(payload) + chr(10))
                            protocol_output.flush()
                            announced = True
                        await asyncio.sleep(0.05)

                watcher = asyncio.create_task(monitor())
                try:
                    await server.serve(sockets=[listener])
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)


        asyncio.run(serve())
    except Exception as exc:
        print("控制台后端启动或退出失败：" + str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
