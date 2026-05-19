"""
Carregamento assíncrono de sprites MVP (I/O + PIL) fora da thread da UI.

O worker só devolve bytes PNG já redimensionados; LRU e PhotoImage ficam na
thread principal (Tkinter), conforme combinado.
"""
from __future__ import annotations

import queue
import threading
from io import BytesIO
from typing import Optional, Tuple

from mvp_timer import resolve_mob_image

# Tamanho da miniatura na grelha (igual ao card MVP).
_MVP_THUMB_PX = (58, 58)


class MvpImageLoader:
    """
    Fila de trabalhos + thread daemon: resolve_mob_image → PIL thumbnail → PNG bytes.
    Nenhum widget Tk é tocado aqui.
    """

    def __init__(self) -> None:
        self._inq = queue.Queue()
        self._outq = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker_loop, name="MvpImageLoader", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()

    def enqueue(self, generation: int, monster_id: int, display_name: str) -> None:
        """Pedido vindo apenas da main thread."""
        self._inq.put((int(generation), int(monster_id), str(display_name or "")))

    def try_get_result(self) -> Optional[Tuple[int, int, Optional[bytes]]]:
        """Polling não bloqueante na main thread."""
        try:
            return self._outq.get_nowait()
        except queue.Empty:
            return None

    def has_backlog(self) -> bool:
        """Indica se ainda há trabalho ou resultados por processar (aproximado, CPython)."""
        try:
            return self._inq.qsize() > 0 or self._outq.qsize() > 0
        except NotImplementedError:
            return False

    def _worker_loop(self) -> None:
        from PIL import Image

        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        while not self._stop.is_set():
            try:
                gen, mid, name = self._inq.get(timeout=0.35)
            except queue.Empty:
                continue
            blob: Optional[bytes] = None
            try:
                raw, _src = resolve_mob_image(mid, display_name=name)
                if raw:
                    im = Image.open(BytesIO(raw)).convert("RGBA")
                    im.thumbnail(_MVP_THUMB_PX, resample)
                    buf = BytesIO()
                    im.save(buf, format="PNG")
                    blob = buf.getvalue()
            except Exception:
                blob = None
            try:
                self._outq.put((gen, mid, blob))
            except Exception:
                pass
