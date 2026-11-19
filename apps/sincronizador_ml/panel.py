"""Panel web del Sincronizador ML (http://localhost:8765), sin dependencias: http.server + HTML."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from apps.sincronizador_ml.motor import Motor, ultimas_lineas_log

PUERTO = 8765

FILTROS = {
    "movimientos": ["venta", "cancelacion", "stock"],
    "errores": ["error", "aviso", "resuelto"],
    "pasadas": ["pasada", "sistema"],
    "todo": None,
}

HTML = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sincronizador ML</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1d2330;--mu:#6b7280;--ln:#e5e7eb;--azul:#2d7ff9;--verde:#1f9d55;--rojo:#e5484d;--gris:#8a8f98;--amar:#b7791f}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1d2026;--tx:#e8eaee;--mu:#9aa1ad;--ln:#2c3038}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:20px 16px}
header{display:flex;gap:16px;align-items:center;background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:16px 18px}
.dot{width:22px;height:22px;border-radius:50%;flex:none;box-shadow:0 0 0 4px color-mix(in srgb,currentColor 18%,transparent)}
.st h1{font-size:17px;margin:0}.st p{margin:2px 0 0;color:var(--mu);font-size:13px}
.acc{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
button{font:inherit;border:1px solid var(--ln);background:var(--card);color:var(--tx);border-radius:8px;padding:7px 12px;cursor:pointer}
button:hover{border-color:var(--mu)}button.pri{background:var(--azul);border-color:var(--azul);color:#fff}
.err{margin-top:12px;background:color-mix(in srgb,var(--rojo) 10%,var(--card));border:1px solid color-mix(in srgb,var(--rojo) 40%,var(--ln));border-radius:10px;padding:10px 14px}
.err b{color:var(--rojo)}.err li{margin:3px 0}
nav{display:flex;gap:4px;margin:18px 0 10px;flex-wrap:wrap}
nav button{border:none;background:none;color:var(--mu);padding:6px 12px;border-radius:20px}
nav button.on{background:var(--card);color:var(--tx);box-shadow:0 0 0 1px var(--ln)}
.lista{background:var(--card);border:1px solid var(--ln);border-radius:12px;overflow:hidden}
.ev{display:grid;grid-template-columns:130px 110px 1fr;gap:10px;padding:9px 14px;border-top:1px solid var(--ln);align-items:start}
.ev:first-child{border-top:none}.ev.nuevo{background:color-mix(in srgb,var(--verde) 8%,transparent)}
.f{color:var(--mu);font-variant-numeric:tabular-nums;font-size:13px}
.t{font-size:12px;font-weight:600;border-radius:20px;padding:1px 9px;justify-self:start;white-space:nowrap}
.venta,.cancelacion{background:color-mix(in srgb,var(--verde) 16%,transparent);color:var(--verde)}
.stock{background:color-mix(in srgb,var(--azul) 14%,transparent);color:var(--azul)}
.error{background:color-mix(in srgb,var(--rojo) 14%,transparent);color:var(--rojo)}
.aviso{background:color-mix(in srgb,var(--amar) 16%,transparent);color:var(--amar)}
.pasada,.sistema,.resuelto,.simulacion{background:color-mix(in srgb,var(--gris) 16%,transparent);color:var(--mu)}
.vacio{padding:28px;text-align:center;color:var(--mu)}
pre{margin:0;padding:14px;max-height:65vh;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
@media (max-width:640px){header{flex-wrap:wrap}.acc{margin-left:0}.ev{grid-template-columns:1fr;gap:2px}}
</style></head><body><div class="wrap">
<header><div class="dot" id="dot"></div><div class="st"><h1 id="titulo">…</h1><p id="sub"></p></div>
<div class="acc"><button class="pri" onclick="post('sincronizar')">Sincronizar ahora</button>
<button onclick="post('visto')">Marcar como visto</button><button id="bp" onclick="post('pausa')">Pausar</button></div></header>
<div id="errs"></div>
<nav id="nav"></nav><div class="lista" id="lista"></div></div>
<script>
const COL={azul:'var(--azul)',verde:'var(--verde)',rojo:'var(--rojo)',gris:'var(--gris)'};
const TIT={azul:'Sin novedades',verde:'Hay movimientos nuevos de Mercado Libre',rojo:'Hay errores',gris:'Pausado'};
const NOM={venta:'Venta',cancelacion:'Cancelación',stock:'Stock',error:'Error',aviso:'Aviso',resuelto:'Resuelto',pasada:'Sincronización',sistema:'Sistema',simulacion:'Simulación'};
const TABS=[['movimientos','Movimientos'],['errores','Errores'],['pasadas','Sincronizaciones'],['todo','Todo'],['log','Log']];
let tab=localStorageGet()||'movimientos',visto=0;
function localStorageGet(){try{return localStorage.getItem('tab')}catch(e){return null}}
function hora(s){if(!s)return'—';const d=new Date(s);return d.toLocaleDateString('es-CL',{day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('es-CL',{hour:'2-digit',minute:'2-digit',hour12:false})}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function nav(){document.getElementById('nav').innerHTML=TABS.map(([k,n])=>`<button class="${k==tab?'on':''}" onclick="ir('${k}')">${n}</button>`).join('')}
function ir(k){tab=k;try{localStorage.setItem('tab',k)}catch(e){}nav();lista()}
async function post(a){await fetch('/api/'+a,{method:'POST'});setTimeout(cargar,300)}
async function estado(){const e=await (await fetch('/api/estado')).json();visto=e.visto_hasta;
 document.getElementById('dot').style.color=COL[e.color];document.getElementById('dot').style.background=COL[e.color];
 document.getElementById('titulo').textContent=e.ocupado?'Sincronizando…':TIT[e.color];
 document.getElementById('sub').textContent=`Última: ${hora(e.ultima_pasada)} — ${e.resumen}`+(e.proxima?` · próxima ${hora(e.proxima).slice(6)}`:'')+` · cada ${e.cada_minutos} min`;
 document.getElementById('bp').textContent=e.pausado?'Reanudar':'Pausar';
 document.getElementById('errs').innerHTML=e.errores_activos.length?`<div class="err"><b>Errores sin resolver</b><ul>${e.errores_activos.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:'';
 document.title=(e.color=='azul'?'':'● ')+'Sincronizador ML'}
async function lista(){const el=document.getElementById('lista');
 if(tab=='log'){const t=await (await fetch('/api/log')).text();el.innerHTML=`<pre>${esc(t)||'(vacío)'}</pre>`;const p=el.querySelector('pre');p.scrollTop=p.scrollHeight;return}
 const ev=await (await fetch('/api/eventos?filtro='+tab)).json();
 el.innerHTML=ev.length?ev.map(e=>`<div class="ev ${e.id>visto&&['venta','cancelacion','error'].includes(e.tipo)?'nuevo':''}"><span class="f">${hora(e.fecha)}</span><span class="t ${e.tipo}">${NOM[e.tipo]||e.tipo}</span><span>${esc(e.texto)}</span></div>`).join(''):'<div class="vacio">Nada por aquí todavía.</div>'}
async function cargar(){try{await estado();await lista()}catch(e){document.getElementById('titulo').textContent='El sincronizador no responde';document.getElementById('dot').style.background=COL.gris}}
nav();cargar();setInterval(cargar,5000);
</script></body></html>"""


def servidor(motor: Motor) -> ThreadingHTTPServer:
    """Crea el servidor (falla si el puerto está ocupado: otra copia abierta)."""

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sin ruido en el log
            pass

        def _enviar(self, cuerpo, tipo="application/json; charset=utf-8", codigo=200):
            datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                self._enviar(HTML, "text/html; charset=utf-8")
            elif u.path == "/api/estado":
                self._enviar(json.dumps(motor.estado(), ensure_ascii=False))
            elif u.path == "/api/eventos":
                filtro = parse_qs(u.query).get("filtro", ["movimientos"])[0]
                self._enviar(json.dumps(motor.registro.eventos(FILTROS.get(filtro)), ensure_ascii=False))
            elif u.path == "/api/log":
                self._enviar(ultimas_lineas_log(), "text/plain; charset=utf-8")
            else:
                self._enviar("{}", codigo=404)

        def do_POST(self):
            acciones = {"/api/sincronizar": motor.sincronizar_ahora, "/api/visto": motor.marcar_visto,
                        "/api/pausa": motor.alternar_pausa}
            accion = acciones.get(urlparse(self.path).path)
            if not accion:
                return self._enviar("{}", codigo=404)
            accion()
            self._enviar('{"ok": true}')

    return ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)


def iniciar_en_segundo_plano(srv: ThreadingHTTPServer) -> None:
    threading.Thread(target=srv.serve_forever, daemon=True, name="panel-ml").start()
