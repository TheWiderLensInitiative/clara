"""Tiny TCP relay for tests: python tcp_relay.py <listen_port> <target_port>"""
import asyncio, sys
async def pipe(r, w):
    try:
        while (d := await r.read(65536)): w.write(d); await w.drain()
    except Exception: pass
    finally: w.close()
async def handle(r, w):
    tr, tw = await asyncio.open_connection("127.0.0.1", int(sys.argv[2]))
    await asyncio.gather(pipe(r, tw), pipe(tr, w))
async def main():
    s = await asyncio.start_server(handle, "0.0.0.0", int(sys.argv[1]))
    async with s: await s.serve_forever()
asyncio.run(main())
