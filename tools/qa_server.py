"""Servidor de QA visual: roda a UI real num navegador comum, ligada à Api real.

Serve ``gdz_monitor/web/`` e encaminha ``window.pywebview.api.*`` para a classe
``Api`` via HTTP — mesmo código do .exe, sem PyWebView. Útil para qualquer agente
com navegador (ou humano) clicar pelas páginas e conferir uma mudança.

Isolamento:
- HOME e banco SQLite temporários (o seu ``gdz_monitor.db`` real nunca é alterado);
- ``--with-my-data`` copia o seu banco (ou, se ainda não existir, os ~/herosaga_*.json
  antigos) para esse ambiente — sessão Discord incluída; a cópia é apagada ao encerrar;
- worker de alertas desligado (sem e-mails).
A rede NÃO é bloqueada: buscas/atualizações consultam o site (só leitura).

Uso (na raiz):
    python tools/qa_server.py [--with-my-data] [--port 8765]
Abrir http://127.0.0.1:8765 . No console do navegador:
    window.__qaErrors          → erros JS / promises rejeitadas
    fetch('/__calls')          → últimas chamadas à Api (ok/erro/exceção)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "gdz_monitor", "web")

SHIM = b"""<script>
window.__qaErrors=[];
window.addEventListener('error',e=>__qaErrors.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>__qaErrors.push('rejeicao: '+String(e.reason)));
window.pywebview={api:new Proxy({},{get:(_,name)=>(...args)=>fetch('/__api/'+name,{method:'POST',body:JSON.stringify(args)})
  .then(r=>r.json()).then(j=>{if(j.__error)throw new Error(j.__error);return j.result;})})};
setTimeout(()=>window.dispatchEvent(new Event('pywebviewready')),50);
</script>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--with-my-data", action="store_true", help="copia o seu banco de dados para o ambiente isolado")
    args = ap.parse_args()

    real_home = os.path.expanduser("~")
    real_db = os.environ.get("GDZ_MONITOR_DB") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.join(real_home, ".gdz_monitor"), "GDZMonitor", "gdz_monitor.db")
    qa_home = tempfile.mkdtemp(prefix="gdz_qa_home_")
    qa_db = os.path.join(qa_home, "gdz_monitor.db")
    if args.with_my_data:
        if os.path.isfile(real_db):
            src = sqlite3.connect(f"file:{real_db.replace(os.sep, '/')}?mode=ro", uri=True)
            dst = sqlite3.connect(qa_db)
            try:
                src.backup(dst)  # cópia consistente mesmo com o app aberto (WAL)
            finally:
                dst.close()
                src.close()
        else:
            for path in glob.glob(os.path.join(real_home, "herosaga_*.json")):
                shutil.copy2(path, qa_home)  # migrados para o banco de QA na primeira abertura
    os.environ["USERPROFILE"] = os.environ["HOME"] = os.environ["LOCALAPPDATA"] = qa_home
    os.environ["GDZ_MONITOR_DB"] = qa_db
    sys.path.insert(0, ROOT)

    import gdz_monitor.app.api as api_mod  # depois de trocar HOME/banco

    orig_worker = api_mod.get_alert_worker

    def idle_worker(*a, **k):
        w = orig_worker(*a, **k)
        w.start = lambda *a, **k: None
        return w

    api_mod.get_alert_worker = idle_worker
    api = api_mod.Api()
    calls: list = []

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=WEB, **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    html = f.read().replace(b"<head>", b"<head>" + SHIM, 1)
                return self._send(html, "text/html; charset=utf-8")
            if self.path == "/__calls":
                return self._send(json.dumps(calls[-300:], ensure_ascii=False).encode(), "application/json")
            return super().do_GET()

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]
            params = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
            entry: dict = {"m": name, "args": params}
            try:
                if name.startswith("_"):
                    raise AttributeError(name)
                res = getattr(api, name)(*params)
                body = {"result": res}
                if isinstance(res, dict):
                    entry.update(ok=res.get("ok"), err=res.get("error"))
            except Exception as exc:  # noqa: BLE001
                body = {"__error": f"{type(exc).__name__}: {exc}"}
                entry["exc"] = traceback.format_exc()[-1500:]
            calls.append(entry)
            self._send(json.dumps(body, ensure_ascii=False, default=str).encode(), "application/json")

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    from gdz_monitor.core import database

    if os.path.abspath(database.DB_FILE) != os.path.abspath(qa_db):
        sys.exit(f"banco fora do QA: {database.DB_FILE}")
    print(f"QA server em http://127.0.0.1:{args.port}  (HOME/banco isolados: {qa_home})", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        database.close()
        shutil.rmtree(qa_home, ignore_errors=True)


if __name__ == "__main__":
    main()
