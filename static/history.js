const historyState = {
    events: [],
    visible: [],
    limit: 500,
    search: "",
    index: "",
    timeframe: "",
    specificIndex: "",
    refreshMs: 5000,
    refreshTimer: null,
    dateFrom: "",
    dateTo: ""
};

const H = (id) => document.getElementById(id);

function hEsc(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function hMoney(value) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? `₹${n.toFixed(2)}` : "—";
}

function membershipValue(event) {
    if (event.index_membership) return event.index_membership;

    const symbol = event.symbol || "";

    // Backward-compatible fallback for older history entries.
    if (symbol === "NIFTY50" || symbol === "SENSEX" || symbol === "BANKNIFTY") {
        return "INDEX";
    }

    return "OTHER";
}

function membershipBadge(value) {
    const safe = hEsc(value);

    if (value === "N50 & N100") {
        return `<span class="history-membership both">${safe}</span>`;
    }

    if (value === "N100") {
        return `<span class="history-membership n100">${safe}</span>`;
    }

    if (value === "INDEX") {
        return `<span class="history-membership index">${safe}</span>`;
    }

    return `<span class="history-membership other">${safe}</span>`;
}

function signalBadge(signal) {
    const cls = String(signal || "").includes("GREEN → RED")
        ? "history-signal red-signal"
        : "history-signal green-signal";

    return `<span class="${cls}">${hEsc(signal || "—")}</span>`;
}

function shortDateTime(value) {
    if (!value) return "—";
    const raw=String(value);
    const d=new Date(raw);
    if(!Number.isNaN(d.getTime())) return d.toLocaleString("en-IN",{timeZone:"Asia/Kolkata",hour12:true,day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"});
    const m=raw.match(/^(\d{2}-\d{2}-\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})/);
    if(m){let h=Number(m[2]);const ap=h>=12?"PM":"AM";h=h%12||12;return `${m[1]} ${String(h).padStart(2,"0")}:${m[3]}:${m[4]} ${ap}`;}
    return raw.replace("T"," ").replace("+05:30","");
}

function historyOhlcChart(cs, compact=false){
    if(!Array.isArray(cs)||!cs.length) return '<span class="muted">No OHLC data</span>';
    const clean=cs.map((c,i)=>{
        const o=Number(c.open), cl=Number(c.close), hi=Number(c.high), lo=Number(c.low);
        if(![o,cl,hi,lo].every(Number.isFinite)) return null;
        return {...c,open:o,close:cl,high:Math.max(hi,o,cl),low:Math.min(lo,o,cl),index:i+1};
    }).filter(Boolean);
    if(!clean.length) return '<span class="muted">Invalid OHLC</span>';
    const max=Math.max(...clean.map(c=>c.high)), min=Math.min(...clean.map(c=>c.low));
    const pad=Math.max((max-min)*0.08,Math.abs(max)*0.00025,0.01), topValue=max+pad,bottomValue=min-pad;
    const width=compact?300:620,height=compact?100:190,top=10,bottom=24,plot=height-top-bottom,range=Math.max(topValue-bottomValue,1e-9);
    const y=v=>top+((topValue-v)/range)*plot;
    const step=(width-30)/clean.length, bodyW=Math.min(compact?14:22,Math.max(compact?8:12,step*.42));
    const grid=[.25,.5,.75].map(q=>{const gy=top+plot*q;return `<line class="history-chart-grid" x1="5" x2="${width-5}" y1="${gy.toFixed(2)}" y2="${gy.toFixed(2)}"/>`;}).join('');
    const marks=clean.map((c,i)=>{const x=15+step*i+step/2,yo=y(c.open),yc=y(c.close),yh=y(c.high),yl=y(c.low),bt=Math.min(yo,yc),bh=Math.max(Math.abs(yo-yc),c.type==='DOJI'?3:2),cls=String(c.type||'DOJI').toLowerCase();return `<g class="history-ohlc ${cls}"><line class="wick" x1="${x}" x2="${x}" y1="${yh.toFixed(2)}" y2="${yl.toFixed(2)}"/><rect class="body" x="${(x-bodyW/2).toFixed(2)}" y="${bt.toFixed(2)}" width="${bodyW.toFixed(2)}" height="${bh.toFixed(2)}" rx="1.5"/><title>C${i+1} ${c.type} · O ${hMoney(c.open)} · H ${hMoney(c.high)} · L ${hMoney(c.low)} · C ${hMoney(c.close)}</title></g>`}).join('');
    const labels=clean.map((c,i)=>{const pct=Number.isFinite(Number(c.wick_body_percent))?Number(c.wick_body_percent).toFixed(1)+'%':'N/A';return `<span class="history-chart-label ${String(c.type||'DOJI').toLowerCase()}" title="C${i+1} Wick/Body ${pct}"><b>${i+1}</b><small>${pct}</small></span>`;}).join('');
    return `<div class="history-ohlc-wrap ${compact?'compact':''}"><svg class="history-ohlc-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${clean.length}-candle OHLC chart">${grid}<line class="history-chart-base" x1="5" x2="${width-5}" y1="${height-bottom}" y2="${height-bottom}"/>${marks}</svg><div class="history-chart-labels">${labels}</div></div>`;
}

function renderPattern(event) {
    const types = event.seven_types || [];

    if (!types.length && event.pattern) {
        return `<span class="pattern-text">${hEsc(event.pattern)}</span>`;
    }

    return `
        <div class="history-pattern">
            ${types.map((type, index) => {
                const letter = type === "GREEN" ? "G" : type === "RED" ? "R" : "D";
                const cls = type === "GREEN" ? "green" : type === "RED" ? "red" : "doji";
                return `<span class="pattern-candle ${cls}">
                    <b>${index + 1}</b>${letter}
                </span>`;
            }).join("")}
        </div>
    `;
}

function renderRows() {
    const body = H("historyBody");
    const sortMode = H("historySort") ? H("historySort").value : "newest";
    historyState.events.sort((a,b)=>{
        const ta=Date.parse(a.arrival_time||a.signal_candle_time||"")||0;
        const tb=Date.parse(b.arrival_time||b.signal_candle_time||"")||0;
        return sortMode === "oldest" ? ta-tb : tb-ta;
    });

    const q = historyState.search.trim().toLowerCase();

    historyState.visible = historyState.events.filter(event => {
        const membership = membershipValue(event);
        const tags = event.index_tags || [];

        if (historyState.index) {
            if (historyState.index === "NIFTY 50" && !tags.includes("NIFTY 50")) return false;
            if (historyState.index === "NIFTY 100" && !tags.includes("NIFTY 100")) return false;
            if (historyState.index === "NIFTY 150" && !tags.includes("NIFTY 150")) return false;
            if (historyState.index === "NIFTY 200" && !tags.includes("NIFTY 200")) return false;
            if (historyState.index !== "NIFTY 50" && historyState.index !== "NIFTY 100" && historyState.index !== "NIFTY 150" && historyState.index !== "NIFTY 200" && historyState.index !== "SENSEX" && historyState.index !== "NIFTY BANK" && membership !== historyState.index) return false;
            if ((historyState.index === "SENSEX" || historyState.index === "NIFTY BANK") && !tags.includes(historyState.index)) return false;
        }

        if (historyState.specificIndex && !tags.join(" ").toLowerCase().includes(historyState.specificIndex.toLowerCase())) return false;

        if (historyState.timeframe && event.interval !== historyState.timeframe) {
            return false;
        }

        if (!q) return true;

        const haystack = [
            event.symbol,
            event.name,
            event.interval,
            event.signal,
            event.pattern,
            membership,
            (event.index_tags || []).join(" ")
        ].join(" ").toLowerCase();

        return haystack.includes(q);
    });

    H("visibleCount").textContent = historyState.visible.length;

    if (!historyState.visible.length) {
        body.innerHTML = `
            <tr>
                <td colspan="14" class="empty-history">
                    No matching signal history.
                </td>
            </tr>
        `;
        return;
    }

    body.innerHTML = historyState.visible.map((event, index) => {
        const candle = event.signal_candle || {};
        const membership = membershipValue(event);

        return `
            <tr class="history-row" data-index="${index}">
                <td class="history-serial">${index + 1}</td>

                <td>
                    <div class="detected-time">
                        <strong>${hEsc(shortDateTime(event.arrival_time || event.arrival_time_display))}</strong>
                        <small>Dashboard detected</small>
                    </div>
                </td>

                <td>
                    <div class="history-symbol">
                        <strong>${hEsc(event.symbol)}</strong>
                        <small>${hEsc(event.name || "")}</small>
                    </div>
                </td>

                <td>${membershipBadge(membership)}</td>

                <td>
                    <span class="tf-badge">${hEsc(event.interval)}</span>
                </td>

                <td>${renderPattern(event)}</td>

                <td>${historyOhlcChart(event.seven_candles || [], true)}</td>

                <td>${signalBadge(event.signal)}</td>

                <td>${hEsc(shortDateTime(event.signal_candle_time || event.signal_candle_time_ist))}</td>

                <td>${hEsc(shortDateTime(event.signal_candle_closed_at || event.signal_candle_closed_at_display))}</td>

                <td>${hMoney(candle.open)}</td>
                <td>${hMoney(candle.high)}</td>
                <td>${hMoney(candle.low)}</td>
                <td class="close-price">${hMoney(candle.close)}</td>

                <td>
                    <button class="view-seven" data-index="${index}">
                        View 7
                    </button>
                </td>
            </tr>
        `;
    }).join("");

    body.querySelectorAll(".view-seven").forEach(button => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            openHistoryModal(historyState.visible[Number(button.dataset.index)]);
        });
    });

    body.querySelectorAll(".history-row").forEach(row => {
        row.addEventListener("click", () => {
            openHistoryModal(historyState.visible[Number(row.dataset.index)]);
        });
    });
}

function openHistoryModal(event) {
    const membership = membershipValue(event);
    const candles = event.seven_candles || [];

    H("modalTitle").textContent =
        `${event.symbol} · ${event.interval}`;

    H("modalSub").textContent =
        `${event.name || event.symbol} · ${membership} · ${event.signal || ""}`;

    H("modalContent").innerHTML = `
        <div class="evidence-summary">
            <div>
                <span>7-Candle Pattern</span>
                <strong>${hEsc(event.pattern || "—")}</strong>
            </div>
            <div>
                <span>Signal Candle</span>
                <strong>${hEsc(shortDateTime(event.signal_candle_time || event.signal_candle_time_ist))}</strong>
            </div>
            <div>
                <span>Candle Closed</span>
                <strong>${hEsc(shortDateTime(event.signal_candle_closed_at || event.signal_candle_closed_at_display))}</strong>
            </div>
            <div>
                <span>Dashboard Detected</span>
                <strong>${hEsc(shortDateTime(event.arrival_time || event.arrival_time_display))}</strong>
            </div>
        </div>

        <div class="modal-chart-section"><div><h3>7-Candle OHLC Chart</h3><p>Wicks use High/Low. Body uses Open/Close. Doji is shown as a thin body.</p></div>${historyOhlcChart(candles, false)}</div>

        <div class="modal-evidence">
            <h3>Complete 7-Candle Evidence</h3>
            <div class="modal-table-wrap">
                <table class="modal-history-table">
                    <thead>
                        <tr>
                            <th>No.</th>
                            <th>Type</th>
                            <th>Candle Time</th>
                            <th>Closed At</th>
                            <th>Open</th>
                            <th>High</th>
                            <th>Low</th>
                            <th>Close</th>
                            <th>Wick/Body</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${candles.map((candle, index) => {
                            const cls = candle.type === "GREEN"
                                ? "green"
                                : candle.type === "RED"
                                    ? "red"
                                    : "doji";

                            return `
                                <tr>
                                    <td>${index + 1}</td>
                                    <td>
                                        <span class="modal-type ${cls}">
                                            ${hEsc(candle.type)}
                                        </span>
                                    </td>
                                    <td>${hEsc(shortDateTime(candle.time || candle.time_display))}</td>
                                    <td>${hEsc(shortDateTime(candle.closed_at || candle.closed_at_display))}</td>
                                    <td>${hMoney(candle.open)}</td>
                                    <td>${hMoney(candle.high)}</td>
                                    <td>${hMoney(candle.low)}</td>
                                    <td>${hMoney(candle.close)}</td>
                                    <td class="history-wb">${candle.wick_body_percent==null?'N/A':Number(candle.wick_body_percent).toFixed(1)+'%'}</td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="explanation-box">
            <strong>Why this signal?</strong>
            <span>${hEsc(event.explanation || "")}</span>
        </div>
    `;

    H("historyModal").classList.remove("hidden");
}

function closeHistoryModal() {
    H("historyModal").classList.add("hidden");
}

async function loadHistory() {
    try {
        const params = new URLSearchParams({limit: String(historyState.limit), _: String(Date.now())});
        if (historyState.dateFrom) params.set("date_from", historyState.dateFrom);
        if (historyState.dateTo) params.set("date_to", historyState.dateTo);
        const response = await fetch(`/api/history?${params.toString()}`, { cache: "no-store" });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to load history");
        }

        historyState.events = data.events || [];
        if (data.sc_wick_limit_percent && H("settingsStatus") && !H("settingsStatus").textContent.startsWith("Active")) H("settingsStatus").textContent = `Active ${Number(data.sc_wick_limit_percent).toFixed(0)}%`;
        renderRows();
        updateLastHistoryRefresh(data);

    } catch (error) {
        console.error(error);

        H("historyBody").innerHTML = `
            <tr>
                <td colspan="15" class="empty-history error-history">
                    ${hEsc(error.message)}
                </td>
            </tr>
        `;
    }
}

function updateHistoryClock() {
    H("historyClock").textContent =
        new Date().toLocaleTimeString(
            "en-IN",
            {
                timeZone: "Asia/Kolkata",
                hour12: true
            }
        );
}

H("historySearch").addEventListener("input", event => {
    historyState.search = event.target.value;
    renderRows();
});

H("indexFilter").addEventListener("change", event => {
    historyState.index = event.target.value;
    renderRows();
});

H("timeframeFilter").addEventListener("change", event => {
    historyState.timeframe = event.target.value;
    renderRows();
});

H("limit").addEventListener("change", event => {
    historyState.limit = Number(event.target.value);
    loadHistory();
});

H("clearHistory").addEventListener("click", async () => {
    const confirmed = window.confirm(
        "Clear all stored signal history?"
    );

    if (!confirmed) return;

    try {
        const response = await fetch(
            "/api/history/clear",
            { method: "POST" }
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to clear history");
        }

        await loadHistory();

    } catch (error) {
        alert(error.message);
    }
});

H("closeHistoryModal").addEventListener(
    "click",
    closeHistoryModal
);

H("historyModal").addEventListener(
    "click",
    event => {
        if (event.target === H("historyModal")) {
            closeHistoryModal();
        }
    }
);

function updateLastHistoryRefresh(data){
    const now = new Date();
    H("lastHistoryRefresh").textContent = now.toLocaleTimeString("en-IN", {timeZone:"Asia/Kolkata", hour12:true});
    if (H("csvStatus")) H("csvStatus").textContent = data && data.storage ? "DAILY AUTO SYNC" : "SYNCED";
}

async function refreshHistoryNow(){
    await loadHistory();
}

function restartHistoryRefresh(){
    if (historyState.refreshTimer) clearInterval(historyState.refreshTimer);
    if (historyState.refreshMs > 0) historyState.refreshTimer = setInterval(refreshHistoryNow, historyState.refreshMs);
}

if (H("specificIndex")) H("specificIndex").addEventListener("input", event => { historyState.specificIndex = event.target.value.trim(); renderRows(); });
if (H("historyRefresh")) H("historyRefresh").addEventListener("change", event => { historyState.refreshMs = Number(event.target.value); restartHistoryRefresh(); refreshHistoryNow(); });
setInterval(updateHistoryClock, 1000);
updateHistoryClock();
loadHistory().then(() => updateLastHistoryRefresh());
restartHistoryRefresh();
