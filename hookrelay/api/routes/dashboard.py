# ruff: noqa: E501

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hookrelay.api.auth import CurrentTenant
from hookrelay.db.session import get_db_session
from hookrelay.models import Delivery, Event

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
ui_router = APIRouter(tags=["dashboard"])


@ui_router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> str:
    return """<!doctype html><html><head><title>HookRelay</title><style>
body{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;background:#0b1020;color:#e8eefc}
input,button{padding:10px;margin:4px;background:#17213b;color:white;border:1px solid #506080;border-radius:6px}
.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#17213b;padding:18px;border-radius:10px;min-width:120px}
table{width:100%;border-collapse:collapse;margin-top:20px}td,th{padding:9px;border-bottom:1px solid #334}</style></head>
<body><h1>HookRelay Dashboard</h1><p>Tenant-scoped delivery health</p>
<input id="key" type="password" placeholder="X-API-Key"><button onclick="load()">Refresh</button>
<div id="cards" class="cards"></div><table><thead><tr><th>Delivery</th><th>Status</th><th>Attempts</th><th>Created</th></tr></thead><tbody id="rows"></tbody></table>
<script>async function load(){let r=await fetch('/api/v1/dashboard/summary',{headers:{'X-API-Key':key.value}});if(!r.ok){alert('Request failed: '+r.status);return}let d=await r.json();cards.innerHTML=Object.entries(d.counts).map(([k,v])=>`<div class=card><b>${v}</b><br>${k}</div>`).join('');rows.innerHTML=d.recent.map(x=>`<tr><td>${x.id}</td><td>${x.status}</td><td>${x.attempts}</td><td>${new Date(x.created_at).toLocaleString()}</td></tr>`).join('')}</script></body></html>"""


@router.get("/summary")
async def dashboard_summary(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: CurrentTenant,
) -> dict[str, Any]:
    counts = dict(
        (
            await session.execute(
                select(Delivery.status, func.count())
                .join(Event, Event.id == Delivery.event_id)
                .where(Event.tenant_id == tenant.id)
                .group_by(Delivery.status)
            )
        ).all()
    )
    recent = list(
        await session.scalars(
            select(Delivery)
            .join(Event, Event.id == Delivery.event_id)
            .where(Event.tenant_id == tenant.id)
            .order_by(Delivery.created_at.desc())
            .limit(20)
        )
    )
    return {
        "counts": counts,
        "recent": [
            {
                "id": str(item.id),
                "status": item.status,
                "attempts": item.attempt_count,
                "created_at": item.created_at,
            }
            for item in recent
        ],
    }
