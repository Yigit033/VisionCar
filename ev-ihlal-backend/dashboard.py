"""Basit pano — olayları kanıt küçük görseliyle listeler. Tüm görsel kod burada.

Şablon motoru/JS bağımlılığı yok; sade, okunaklı bir HTML döndürür.
"""
from __future__ import annotations

import html
from typing import Iterable

from config import Settings
from models import EventState, ViolationEvent

_STATE_COLOR = {
    EventState.OPEN: "#e9a13b",
    EventState.FORWARDED: "#46d17a",
    EventState.RETENTION_PURGED: "#8a909c",
}


def _row(e: ViolationEvent) -> str:
    when = (e.detected_at.strftime("%Y-%m-%d %H:%M:%S") + " UTC") if e.detected_at else "-"
    color = _STATE_COLOR.get(e.state, "#8a909c")
    if e.image_key:
        thumb = (f'<a href="/media/{html.escape(e.image_key)}" target="_blank">'
                 f'<img src="/media/{html.escape(e.image_key)}" '
                 f'loading="lazy" alt="kanit"></a>')
    else:
        thumb = '<div class="noimg">görsel yok<br>(retention)</div>'
    fwd = e.forwarded_at.strftime("%H:%M:%S") if e.forwarded_at else "—"
    return f"""
    <tr>
      <td class="thumb">{thumb}</td>
      <td><span class="mono">#{e.id}</span></td>
      <td><strong>{html.escape(e.station_id)}</strong></td>
      <td class="mono">{when}</td>
      <td><span class="pill">{html.escape(e.telemetry_status.value)}</span></td>
      <td><span class="state" style="color:{color}">{e.state.value}</span></td>
      <td class="mono">{fwd}</td>
      <td class="muted">{html.escape(e.source)}</td>
    </tr>"""


def render_dashboard(events: Iterable[ViolationEvent], settings: Settings) -> str:
    rows = "".join(_row(e) for e in events) or (
        '<tr><td colspan="8" class="muted" style="padding:24px">Henüz olay yok. '
        'Bir işgal olayı tetikleyin (POST /api/events/occupancy).</td></tr>')
    cam_badge = ("MOCK KAMERA" if settings.camera_mode == "mock"
                 else f"ISAPI {settings.camera_ip}")
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EV İhlal Panosu</title>
<style>
  :root {{ --bg:#0f1115; --panel:#171a21; --line:#2a2f3a; --text:#e6e8ec; --muted:#8a909c; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family:"Segoe UI",system-ui,Arial,sans-serif; }}
  header {{ padding:16px 24px; background:var(--panel); border-bottom:1px solid var(--line);
            display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
  header h1 {{ font-size:1.1rem; margin:0; }}
  .badge {{ font-size:.75rem; padding:4px 10px; border:1px solid var(--line);
            border-radius:999px; color:var(--muted); }}
  .wrap {{ padding:18px 24px; }}
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line);
            vertical-align:middle; }}
  th {{ color:var(--muted); font-weight:600; font-size:.72rem; text-transform:uppercase;
        letter-spacing:.5px; }}
  .thumb img {{ width:150px; height:84px; object-fit:cover; border-radius:6px;
                border:1px solid var(--line); display:block; }}
  .noimg {{ width:150px; height:84px; display:flex; align-items:center; justify-content:center;
            text-align:center; font-size:.72rem; color:var(--muted);
            border:1px dashed var(--line); border-radius:6px; }}
  .mono {{ font-variant-numeric:tabular-nums; font-family:Consolas,monospace; }}
  .muted {{ color:var(--muted); }}
  .pill {{ background:#1d212b; border:1px solid var(--line); border-radius:6px;
           padding:3px 8px; font-size:.8rem; }}
  .state {{ font-weight:700; font-size:.8rem; }}
</style></head><body>
<header>
  <h1>🅿️ EV İhlal Panosu</h1>
  <span class="badge">kamera: {cam_badge}</span>
  <span class="badge">grace: {settings.grace_period_sec:.0f}s</span>
  <span class="badge">vacancy: {settings.vacancy_grace_sec:.0f}s</span>
  <span class="badge">retention: {settings.retention_days:.0f} gün</span>
</header>
<div class="wrap">
  <table>
    <thead><tr>
      <th>Kanıt</th><th>#</th><th>İstasyon</th><th>Tespit</th><th>Telemetri</th>
      <th>Durum</th><th>İletim</th><th>Kaynak</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
</body></html>"""
