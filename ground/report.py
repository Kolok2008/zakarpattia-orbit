"""HTML-звіт з картою для презентації (Leaflet + супутникові знімки Esri)."""
import html
import json
from datetime import datetime

import config

VERDICT_STYLE = {
    "ЛІСОВА ПОЖЕЖА": ("fire", "#E4572E", "Лісова пожежа",
                      "Дрон підтвердив горіння в лісі. Потрібен виїзд пожежників."),
    "СПАЛЮВАННЯ ПОЛЯ / СТЕРНІ": ("field", "#E9A23B", "Спалювання поля",
                                 "Горить поле або стерня, а не ліс. Варто повідомити громаду."),
    "ХИБНА ТРИВОГА": ("calm", "#7FB069", "Хибна тривога",
                      "На місці ознак горіння немає. Супутник помилився."),
}
QUIET = ("calm", "#7FB069", "Поруч тихо", "")

TEMPLATE = r"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8">
<title>Zakarpattia Orbit — __TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
__REFRESH__
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700&family=Manrope:wght@400;500;700&display=swap">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--spruce:#0E2620;--moss:#2F4A3A;--lichen:#D8DEC8;--lichen-dim:#9FAA94;
  --ember:#E4572E;--amber:#E9A23B;--fresh:#7FB069;--accent:__ACCENT__}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--spruce);color:var(--lichen);font:15px/1.5 Manrope,system-ui,sans-serif}
#map{position:fixed;inset:0;background:var(--moss)}
.leaflet-container{font:inherit}

.panel{position:fixed;top:24px;left:24px;bottom:24px;width:410px;z-index:500;display:flex;flex-direction:column;gap:26px;
  padding:30px 28px;overflow:auto;background:rgba(14,38,32,.92);backdrop-filter:blur(8px);
  border-left:4px solid var(--accent);border-radius:4px 14px 14px 4px}
.panel>*{flex-shrink:0}
.brand{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.brand b{font:700 15px/1 Unbounded,sans-serif}
.brand time{color:var(--lichen-dim);font-size:13px}
.status{display:flex;flex-wrap:wrap;gap:8px;margin-top:-10px}
.status span{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;
  background:rgba(216,222,200,.08);font-size:13px;color:var(--lichen)}
.status i{width:8px;height:8px;border-radius:50%;background:var(--lichen-dim)}
.status i.on{background:var(--fresh);box-shadow:0 0 0 3px rgba(127,176,105,.25)}
.status i.sim{background:var(--amber)}

.verdict h1{margin:0;font:700 clamp(30px,3vw,38px)/1.04 Unbounded,sans-serif;color:var(--accent);overflow-wrap:anywhere}
.verdict p{margin:12px 0 0;color:var(--lichen-dim)}
.meter{margin-top:16px;height:6px;border-radius:3px;background:rgba(216,222,200,.15)}
.meter i{display:block;height:100%;border-radius:3px;background:var(--accent);width:__CONF__%}
.meter-label{display:flex;justify-content:space-between;margin-top:6px;font-size:13px;color:var(--lichen-dim)}
.meter-label b{color:var(--lichen)}

.chain{list-style:none;margin:0;padding:0;counter-reset:s}
.chain li{position:relative;padding:0 0 18px 40px;counter-increment:s}
.chain li::before{content:counter(s);position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;
  border:1.5px solid var(--lichen-dim);display:grid;place-items:center;font:500 12px/1 Unbounded,sans-serif}
.chain li::after{content:"";position:absolute;left:13px;top:30px;bottom:4px;width:1.5px;background:rgba(216,222,200,.2)}
.chain li:last-child{padding-bottom:0}
.chain li:last-child::after{display:none}
.chain li:last-child::before{background:var(--accent);border-color:var(--accent);color:var(--spruce)}
.chain h2{margin:2px 0;font:500 15px/1.3 Unbounded,sans-serif}
.chain p{margin:0;color:var(--lichen-dim);font-size:14px}
.chain em{font-style:normal;color:var(--fresh)}

.readings{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(216,222,200,.14);border-radius:10px;overflow:hidden}
.readings div{background:var(--spruce);padding:12px 14px}
.readings span{display:block;font-size:12.5px;color:var(--lichen-dim)}
.readings b{font:500 19px/1.3 Unbounded,sans-serif}
.readings b.ember{color:var(--accent)}
.note{margin:-14px 0 0;font-size:13px;color:var(--amber)}

.places h3{margin:0 0 10px;font:500 15px/1.3 Unbounded,sans-serif}
.places h3 small{font:400 13px Manrope,sans-serif;color:var(--lichen-dim);margin-left:6px}
.places ul{list-style:none;margin:0;padding:0;border-top:1px solid rgba(216,222,200,.14)}
.places button{all:unset;box-sizing:border-box;width:100%;display:grid;grid-template-columns:12px 1fr auto;gap:4px 12px;
  align-items:center;padding:10px 4px;border-bottom:1px solid rgba(216,222,200,.14);cursor:pointer;border-radius:6px}
.places button:hover{background:rgba(216,222,200,.06)}
.places button:focus-visible{outline:2px solid var(--lichen);outline-offset:2px}
.places .dot{width:10px;height:10px;border-radius:50%;background:#F2C1AE}
.places .dot.c{background:var(--ember)}
.places .s{font-size:14px}
.places .t{font-size:13px;color:var(--lichen-dim);text-align:right}
.places .m{grid-column:2/4;font-size:12.5px;color:var(--lichen-dim)}
.places .is-target .s{color:var(--accent);font-weight:700}
.empty{color:var(--lichen-dim);font-size:14px;margin:0}

.spot{width:14px;height:14px;border-radius:50%;background:#F2C1AE;border:2px solid #fff}
.spot.c{width:18px;height:18px;background:var(--ember)}
.spot.target{background:var(--accent);animation:pulse 2.2s ease-out infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 70%,transparent)}100%{box-shadow:0 0 0 26px transparent}}
.base{width:22px;height:22px;border-radius:5px;background:var(--lichen);border:3px solid var(--spruce);transform:rotate(45deg)}
.route{stroke-dasharray:8 8;animation:draw 1.6s ease-out both}
@keyframes draw{from{stroke-dashoffset:600;opacity:0}to{stroke-dashoffset:0;opacity:1}}
.tag{background:var(--spruce);color:var(--lichen);border:none;border-radius:6px;font:500 12.5px/1.3 Manrope,sans-serif;padding:6px 9px;box-shadow:none}
.tag::before{display:none}

.legend{position:fixed;right:20px;bottom:28px;z-index:500;display:flex;gap:18px;padding:10px 16px;border-radius:999px;
  background:rgba(14,38,32,.88);font-size:13px}
.legend span{display:flex;align-items:center;gap:8px}
.legend i{width:11px;height:11px;border-radius:50%;background:#F2C1AE}
.legend i.c{background:var(--ember)}
.legend i.b{border-radius:3px;background:var(--lichen);transform:rotate(45deg)}
.legend i.z{border-radius:50%;background:none;border:1.5px dashed var(--lichen)}

@media (max-width:760px){
  .panel{top:auto;left:0;right:0;bottom:0;width:auto;max-height:58vh;border-left:0;border-top:4px solid var(--accent);
    border-radius:14px 14px 0 0;padding:22px 20px}
  .legend{display:none}
}
@media (prefers-reduced-motion:reduce){.spot.target,.route{animation:none}}
</style></head>
<body>
<div id="map" role="img" aria-label="Супутникова карта Закарпаття з гарячими точками NASA"></div>

<aside class="panel">
  <div class="brand"><b>Zakarpattia Orbit</b><time>__NOW__</time></div>
  <div class="status">__STATUS__</div>
  <section class="verdict" aria-live="polite">
    <h1>__TITLE__</h1>
    <p>__SUMMARY__</p>
    __METER__
  </section>
  __CHAIN__
  __READINGS__
  <section class="places">
    <h3>Гарячі точки NASA<small>__PLACES_SUB__</small></h3>
    __PLACES__
  </section>
</aside>

<div class="legend" aria-hidden="true">
  <span><i class="c"></i>Бачили кілька разів</span><span><i></i>Один прохід</span>
  <span><i class="b"></i>База дрона</span><span><i class="z"></i>Радіус польоту</span>
</div>

<script>
const D = __DATA__;
const map = L.map('map',{zoomControl:false});
L.control.zoom({position:'topright'}).addTo(map);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:18,attribution:'Знімки © Esri, Maxar, Earthstar Geographics · Дані: NASA FIRMS'}).addTo(map);
const icon = (cls,s=22) => L.divIcon({className:'',html:`<div class="${cls}"></div>`,iconSize:[s,s],iconAnchor:[s/2,s/2]});

const base = [D.base.lat,D.base.lon];
L.circle(base,{radius:D.base.range_km*1000,color:'#D8DEC8',weight:1.2,dashArray:'4 6',fill:false,interactive:false}).addTo(map);
L.marker(base,{icon:icon('base'),title:'База дрона'}).addTo(map)
  .bindTooltip('База дрона',{className:'tag',permanent:true,direction:'right',offset:[14,0]});

const markers = [];
D.places.forEach((p,i) => {
  const cls = 'spot' + (p.confirmed?' c':'') + (p.target?' target':'');
  const m = L.marker([p.lat,p.lon],{icon:icon(cls),title:p.title,zIndexOffset:p.target?1000:0}).addTo(map)
    .bindTooltip(`${p.title}<br>${p.info}`,{className:'tag',direction:'top',offset:[0,-10],permanent:p.target});
  markers[i] = m;
});
if (D.target) L.polyline([base,[D.target.lat,D.target.lon]],{color:'#fff',weight:2.5,className:'route'}).addTo(map);

const pts = [base, ...D.places.map(p=>[p.lat,p.lon])];
const wide = window.innerWidth > 760;
map.fitBounds(L.latLngBounds(pts).pad(0.25),
  {paddingTopLeft:[wide?460:20,40],paddingBottomRight:[40,wide?40:window.innerHeight*0.55+20],maxZoom:12});

document.querySelectorAll('.places button').forEach(b => b.addEventListener('click', () => {
  const p = D.places[+b.dataset.i]; map.flyTo([p.lat,p.lon],13,{duration:.8}); markers[+b.dataset.i].openTooltip();
}));
</script>
</body></html>"""


def _fmt(v, unit, digits=0):
    return "—" if v is None else f"{v:.{digits}f} {unit}"


def _e(s):
    return html.escape(str(s))


def make_report(clusters, target, verdict, reading, path="report.html", *,
                source="live", source_note="", module_mode="none", refresh_min=0) -> str:
    now = datetime.now()
    if verdict is not None:
        cls, accent, title, summary = VERDICT_STYLE.get(verdict.label, QUIET)
    else:
        cls, accent, title, summary = QUIET
        summary = (f"У радіусі {config.MAX_RANGE_KM:.0f} км від бази немає гарячих точок за "
                   f"{config.DAY_RANGE} дн. Дрон чекає." if clusters else
                   f"NASA не бачить гарячих точок над Закарпаттям за {config.DAY_RANGE} дн.")

    # статус джерел — чесно
    src = (f'<span><i class="on"></i>NASA FIRMS: живі дані, {now:%H:%M}</span>' if source == "live"
           else '<span><i class="sim"></i>NASA: збережена точка (немає інтернету)</span>')
    mod = {"live": '<span><i class="on"></i>Модуль: на зв\'язку</span>',
           "sim": '<span><i class="sim"></i>Модуль: імітація</span>',
           "none": '<span><i></i>Модуль: не потрібен</span>'}[module_mode]
    status = src + mod + (f'<span>Оновлення кожні {refresh_min} хв</span>' if refresh_min else "")

    meter = chain = readings = ""
    if verdict is not None:
        conf = f"{verdict.confidence * 100:.0f}"
        meter = (f'<div class="meter" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{conf}"><i></i></div>'
                 f'<div class="meter-label"><span>Впевненість</span><b>{conf}%</b></div>')
        dist = target.distance_km(config.BASE_LAT, config.BASE_LON)
        seen = ", ".join(target.sensors)
        confirm = (f' <em>Підтверджено {len(target.spots)} проходами.</em>' if target.confirmed else "")
        chain = f"""<ol class="chain">
    <li><h2>Супутник помітив</h2><p>{_e(seen)}, останній раз {target.latest.local_time}. Потужність вогню до {target.frp_max} МВт.{confirm}</p></li>
    <li><h2>Дрон вилетів</h2><p>Від бази {dist:.1f} км, висота {config.FLIGHT_ALT_M} м. Якщо зник зв'язок — повертається сам за GPS.</p></li>
    <li><h2>Модуль виміряв</h2><p>Над точкою на висоті {config.INSPECT_ALT_M} м, огляд 30 с.</p></li>
    <li><h2>Висновок</h2><p>{_e(title)}</p></li>
  </ol>"""
        hot = reading.thermal_max_c is not None and reading.thermal_max_c >= 100
        readings = f"""<div class="readings">
    <div><span>Тепловізор, max</span><b class="{'ember' if hot else ''}">{_fmt(reading.thermal_max_c, '°C')}</b></div>
    <div><span>Ріст температури</span><b>+{reading.temp_rise_c:.1f} °C</b></div>
    <div><span>Чадний газ</span><b class="{'ember' if reading.co_detected else ''}">{'є' if reading.co_detected else 'немає'}</b></div>
    <div><span>Повітря</span><b>{_fmt(reading.air_temp_c, '°C', 1)}</b></div>
  </div>"""
        if module_mode == "sim":
            readings += '\n  <p class="note">Показання модуля поки імітовані: заліза ще немає.</p>'

    ordered = sorted(clusters, key=lambda c: -c.latest.when.timestamp())
    places, items = [], []
    for i, c in enumerate(ordered):
        is_t = target is not None and c is target
        d = c.distance_km(config.BASE_LAT, config.BASE_LON)
        places.append({"lat": c.lat, "lon": c.lon, "confirmed": c.confirmed, "target": is_t,
                       "title": "Ціль дрона" if is_t else ", ".join(c.sensors),
                       "info": f"{c.latest.local_time} · {c.frp_max} МВт · {d:.0f} км від бази"})
        times = f"{len(c.spots)} проходи" if len(c.spots) > 1 else "1 прохід"
        items.append(
            f'<li class="{"is-target" if is_t else ""}"><button data-i="{i}" aria-label="Показати на карті">'
            f'<span class="dot{" c" if c.confirmed else ""}"></span>'
            f'<span class="s">{"Ціль дрона · " if is_t else ""}{_e(", ".join(c.sensors))}</span>'
            f'<span class="t">{c.latest.local_time}</span>'
            f'<span class="m">{c.lat:.4f}, {c.lon:.4f} · {c.frp_max} МВт · {times} · {d:.0f} км</span></button></li>')
    places_html = (f"<ul>{''.join(items)}</ul>" if items else
                   '<p class="empty">Порожньо — це добрий знак: пожеж немає.</p>')
    sub = f"{len(clusters)} місць за {config.DAY_RANGE} дн." if clusters else ""
    if source_note:
        sub += " · живі дані недоступні"

    data = {"places": places,
            "target": None if target is None else {"lat": target.lat, "lon": target.lon},
            "base": {"lat": config.BASE_LAT, "lon": config.BASE_LON, "range_km": config.MAX_RANGE_KM}}

    repl = {
        "__REFRESH__": f'<meta http-equiv="refresh" content="{refresh_min * 60}">' if refresh_min else "",
        "__TITLE__": _e(title), "__ACCENT__": accent, "__NOW__": f"{now:%d.%m.%Y, %H:%M}",
        "__STATUS__": status, "__SUMMARY__": _e(summary), "__METER__": meter,
        "__CONF__": f"{verdict.confidence * 100:.0f}" if verdict else "0",
        "__CHAIN__": chain, "__READINGS__": readings,
        "__PLACES_SUB__": _e(sub), "__PLACES__": places_html,
        "__DATA__": json.dumps(data, ensure_ascii=False),
    }
    page = TEMPLATE
    for k in ["__REFRESH__", "__ACCENT__", "__NOW__", "__STATUS__", "__SUMMARY__", "__METER__", "__CHAIN__",
              "__READINGS__", "__PLACES_SUB__", "__PLACES__", "__DATA__", "__CONF__", "__TITLE__"]:
        page = page.replace(k, repl[k])
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path
