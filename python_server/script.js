const $ = id => document.getElementById(id);
const log = t => $("log").textContent = t;

let imgBytes = null;
let gcode = [];
let busy = false;

let socket = null;
let pythonConnected = false;

let cvLoaded = false;
let py = null;
let pyProcess = null;
let pyFinalize = null;

(async () => {
    const loadingText = $("loading_text");

    try {
        loadingText.textContent = "Loading Python...";

        py = await loadPyodide();

        loadingText.textContent = "Loading Python packages...";

        await py.loadPackage([
            "numpy",
            "scipy",
            "pillow",
            "scikit-image"
        ]);

        loadingText.textContent = "Loading image processor...";

        const response = await fetch("/python_server/script.py");

        if (!response.ok) {
            throw new Error("Cannot load script.py");
        }

        await py.runPythonAsync(await response.text());

        pyProcess = py.globals.get("process");
        pyFinalize = py.globals.get("finalize");

        $("loading").hidden = true;
        $("upload").hidden = false;

        console.log("Python initialized!");

    } catch (e) {
        console.error(e);

        loadingText.textContent =
            "Python error: " + e.message;
    }
})();

$("file").onchange = async e => {
  imgBytes = new Uint8Array(await e.target.files[0].arrayBuffer());
  $("editor").hidden = false;
};

$("iSub").onclick = () => {
    run();
}

const sliders = { levels: "lvV", smooth: "smV", minlen: "mlV", tol: "tlV", thr: "thV", hgap: "hgV", hdark: "hdV", bx0: "b0V", by0: "b1V", bx1: "b2V", by1: "b3V" };
for (const [id, out] of Object.entries(sliders)) {
  $(id).oninput = () => $(out).textContent = $(id).value;
  $(id).onchange = () => imgBytes && run();
}
["mode", "bg"].forEach(id => $(id).onchange = () => imgBytes && run());
["aw", "ah", "mg"].forEach(id => $(id).onchange = () => paths.length && commit());

const cv = $("cv");
let paths = [], hist = [], redoStack = [], imgW = 0, imgH = 0;
let tool = "del", hover = -1, cursor = null, stroke = null, erasing = false, lastPt = null;

const eraseR = () => +$("er").value;
const pxScale = () => cv.width / cv.getBoundingClientRect().width;
const pos = e => {
  const r = cv.getBoundingClientRect();
  return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height];
};

function distSeg(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
  let t = l ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

function nearest(p, maxd) {
  let best = -1, bd = maxd;
  paths.forEach((q, i) => {
    for (let j = 0; j < q.length - 1; j++) {
      const d = distSeg(p, q[j], q[j + 1]);
      if (d < bd) { bd = d; best = i; }
    }
  });
  return best;
}

function densify(q, step) {
  const out = [q[0]];
  for (let j = 1; j < q.length; j++) {
    const a = q[j - 1], b = q[j], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let k = 1; k <= n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
  }
  return out;
}

function eraseAt(p, r) {
  const out = [];
  for (const q of paths) {
    let near = false;
    for (let j = 0; j < q.length - 1 && !near; j++) near = distSeg(p, q[j], q[j + 1]) <= r;
    if (!near) { out.push(q); continue; }
    let cur = [];
    for (const pt of densify(q, 1)) {
      if (Math.hypot(pt[0] - p[0], pt[1] - p[1]) <= r) {
        if (cur.length > 1) out.push(cur);
        cur = [];
      } else cur.push(pt);
    }
    if (cur.length > 1) out.push(cur);
  }
  paths = out;
}

function eraseLine(a, b, r) {
  const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (r / 2)));
  for (let k = 1; k <= n; k++) eraseAt([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n], r);
}

function snapshot() {
  hist.push(JSON.stringify(paths));
  if (hist.length > 40) hist.shift();
  redoStack = [];
}

function commit() {
  if (pyFinalize) {
    const res = JSON.parse(pyFinalize(JSON.stringify(paths), imgW, imgH, +$("aw").value, +$("ah").value, +$("mg").value));
    paths = res.paths;
    gcode = res.gcode;
  }
  redraw();
  $("bSave").disabled = false;
  log(`${paths.length} ścieżek, ${gcode.length} linii G-code`);
}

function line(c, p) {
  c.beginPath();
  p.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
  c.stroke();
}

function redraw() {
  if (!imgW) return;
  const c = cv.getContext("2d");
  c.setLineDash([]);
  c.fillStyle = "#fff"; c.fillRect(0, 0, cv.width, cv.height);
  c.strokeStyle = "#000"; c.lineWidth = 1;
  for (const p of paths) line(c, p);
  if (hover >= 0 && paths[hover]) { c.strokeStyle = "#e22"; c.lineWidth = 2.5; line(c, paths[hover]); }
  if (stroke) { c.strokeStyle = "#16f"; c.lineWidth = 1.5; line(c, stroke); }
  if (cursor && tool === "erase") {
    c.strokeStyle = "#888"; c.lineWidth = 1;
    c.beginPath(); c.arc(cursor[0], cursor[1], eraseR(), 0, 6.283); c.stroke();
  }
  if ($("bg").checked) {
    c.strokeStyle = "#e22"; c.lineWidth = 1; c.setLineDash([6, 4]);
    const x0 = +$("bx0").value / 100 * cv.width, y0 = +$("by0").value / 100 * cv.height;
    c.strokeRect(x0, y0, +$("bx1").value / 100 * cv.width - x0, +$("by1").value / 100 * cv.height - y0);
    c.setLineDash([]);
  }
}

cv.onpointerdown = e => {
  if (!imgW) return;
  cv.setPointerCapture(e.pointerId);
  const p = pos(e);
  if (tool === "del") {
    const i = nearest(p, 10 * pxScale());
    if (i >= 0) { snapshot(); paths.splice(i, 1); hover = -1; commit(); }
  } else if (tool === "erase") {
    snapshot(); erasing = true; lastPt = p; eraseAt(p, eraseR()); redraw();
  } else {
    stroke = [p];
  }
};

cv.onpointermove = e => {
  if (!imgW) return;
  const p = pos(e);
  cursor = p;
  if (tool === "del") hover = nearest(p, 10 * pxScale());
  if (erasing) { eraseLine(lastPt, p, eraseR()); lastPt = p; }
  else if (stroke) {
    const l = stroke[stroke.length - 1];
    if (Math.hypot(p[0] - l[0], p[1] - l[1]) >= 1.5) stroke.push(p);
  }
  redraw();
};

cv.onpointerup = cv.onpointercancel = () => {
  if (erasing) { erasing = false; commit(); }
  else if (stroke) {
    if (stroke.length > 1) { snapshot(); paths.push(stroke); }
    stroke = null;
    commit();
  }
};

cv.onpointerleave = () => { cursor = null; hover = -1; redraw(); };

const tools = { tDel: "del", tErase: "erase", tDraw: "draw" };
for (const [id, t] of Object.entries(tools)) {
  $(id).onclick = () => {
    tool = t; hover = -1;
    Object.keys(tools).forEach(k => $(k).classList.toggle("active", k === id));
    redraw();
  };
}
$("er").oninput = () => $("erV").textContent = $("er").value;
$("bUndo").onclick = () => {
  if (!hist.length) return;
  redoStack.push(JSON.stringify(paths));
  paths = JSON.parse(hist.pop());
  commit();
};
$("bRedo").onclick = () => {
  if (!redoStack.length) return;
  hist.push(JSON.stringify(paths));
  paths = JSON.parse(redoStack.pop());
  commit();
};

async function run() {
  if (!pyProcess || busy) return;
  busy = true;
  log("Przetwarzanie...");
  await new Promise(r => setTimeout(r, 30));
  try {
    if ($("bg").checked && !cvLoaded) {
      log("Ładowanie OpenCV...");
      await py.loadPackage("opencv-python");
      cvLoaded = true;
      log("Przetwarzanie...");
    }
    const res = JSON.parse(pyProcess(imgBytes, $("mode").value, +$("levels").value, +$("smooth").value,
      +$("minlen").value, +$("tol").value, +$("thr").value, +$("hgap").value, +$("hdark").value, $("bg").checked ? 1 : 0, +$("bx0").value, +$("by0").value, +$("bx1").value, +$("by1").value, +$("aw").value, +$("ah").value, +$("mg").value));
    paths = res.paths; gcode = res.gcode;
    imgW = res.w; imgH = res.h;
    hist = []; redoStack = []; hover = -1; stroke = null;
    cv.width = res.w; cv.height = res.h;
    redraw();
    $("bSave").disabled = false;
    log(`${paths.length} ścieżek, ${gcode.length} linii G-code`);
  } catch (e) { log("Błąd: " + e); }
  busy = false;
}

$("bSave").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([gcode.join("\n") + "\n"], { type: "text/plain" }));
  a.download = "rysunek.gcode";
  a.click();
};


function connectPython() {

    if (socket && socket.readyState === WebSocket.OPEN) {
        return;
    }

    $("ble_status").textContent = "Connecting to Python...";

    socket = new WebSocket("ws://127.0.0.1:8765");

    socket.onopen = () => {
        $("ble_status").textContent = "Python connected. Searching for ESP32...";
    };

    socket.onmessage = event => {

        const data = JSON.parse(event.data);

        switch (data.status) {

            case "searching":
                pythonConnected = false;
                $("ble_status").textContent = "Searching for ESP32...";
                $("bSend").disabled = true;
                break;

            case "connecting":
                $("ble_status").textContent = "Connecting to ESP32...";
                break;

            case "connected":
                pythonConnected = true;
                $("ble_status").textContent = "ESP32 connected!";
                $("bSend").disabled = false;
                break;

            case "disconnected":
                pythonConnected = false;
                $("ble_status").textContent = "ESP32 disconnected";
                $("bSend").disabled = true;
                break;

            case "sending":
                log(`Sending ${data.progress}/${data.total}: ${data.command}`);
                break;

            case "complete":
                log("G-code transmission completed!");
                break;

            case "error":
                log("Error: " + data.message);
                break;
        }
    };

    socket.onerror = () => {
        $("ble_status").textContent = "Cannot connect to Python server";
    };

    socket.onclose = () => {
        pythonConnected = false;
        $("bSend").disabled = true;
        $("ble_status").textContent = "Python disconnected";
    };
}


$("bConn").onclick = connectPython;


$("bSend").onclick = () => {

    if (!pythonConnected || !gcode.length) {
        return;
    }

    if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
    }

    $("bSend").disabled = true;

    socket.send(JSON.stringify({
        action: "send",
        commands: gcode
    }));
};

const dropZone = document.querySelector(".file-upload-wrapper");
const fileInput = $("file");

["dragenter", "dragover"].forEach(t => dropZone.addEventListener(t, e => {
  e.preventDefault();
  dropZone.classList.add("dragover");
}));

["dragleave", "drop"].forEach(t => dropZone.addEventListener(t, e => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
}));

dropZone.addEventListener("drop", e => {
  const f = e.dataTransfer.files[0];
  if (!f || !f.type.startsWith("image/")) return;
  fileInput.files = e.dataTransfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

let previewUrl = null;

fileInput.addEventListener("change", () => {
  const f = fileInput.files[0];
  if (!f) return;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(f);
  const img = $("file_preview");
  img.src = previewUrl;
  img.hidden = false;
  $("file_label_title").textContent = f.name;
  $("file_label_hint").textContent = "kliknij lub upuść inny plik, aby zmienić";
  dropZone.classList.add("has-file");
});

["dragover", "drop"].forEach(t => window.addEventListener(t, e => e.preventDefault()));