// ReelVault in the browser. Implements FORMAT.md: reel buffer + robust frame codec.
"use strict";

// ================================================================
// Reel buffer: header, deflate, AES-GCM (matches reelvault/header.py, packing.py, crypto.py)
// ================================================================
const MAGIC = [0x52, 0x56, 0x4c, 0x54]; // "RVLT"
const VERSION = 1;
const FLAG_DEFLATE = 0x01, FLAG_ENCRYPTED = 0x02, FLAG_FOLDER = 0x04;
const PBKDF2_ITERATIONS = 600000;

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function streamThrough(bytes, transform) {
  const stream = new Blob([bytes]).stream().pipeThrough(transform);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
const deflateRaw = (b) => streamThrough(b, new CompressionStream("deflate-raw"));
const inflateRaw = (b) => streamThrough(b, new DecompressionStream("deflate-raw"));

async function deriveKey(password, salt, iterations) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]
  );
}

async function buildReel(data, name, { compress = true, password = "" } = {}) {
  let payload = data, flags = 0, cryptoBlock = null;

  if (compress) {
    const squeezed = await deflateRaw(data);
    if (squeezed.length < data.length) { payload = squeezed; flags |= FLAG_DEFLATE; }
  }
  if (password) {
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKey(password, salt, PBKDF2_ITERATIONS);
    payload = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, key, payload));
    flags |= FLAG_ENCRYPTED;
    cryptoBlock = new Uint8Array(32);
    cryptoBlock.set(salt, 0);
    cryptoBlock.set(nonce, 16);
    new DataView(cryptoBlock.buffer).setUint32(28, PBKDF2_ITERATIONS);
  }

  const nameBytes = clipName(name);
  const headLen = 8 + nameBytes.length + 20 + (cryptoBlock ? 32 : 0);
  const out = new Uint8Array(headLen + payload.length);
  const view = new DataView(out.buffer);
  out.set(MAGIC, 0);
  out[4] = VERSION;
  out[5] = flags;
  view.setUint16(6, nameBytes.length);
  out.set(nameBytes, 8);
  let p = 8 + nameBytes.length;
  view.setBigUint64(p, BigInt(data.length)); p += 8;
  view.setBigUint64(p, BigInt(payload.length)); p += 8;
  view.setUint32(p, crc32(payload)); p += 4;
  if (cryptoBlock) { out.set(cryptoBlock, p); p += 32; }
  out.set(payload, p);
  return out;
}

function clipName(name) {
  let bytes = new TextEncoder().encode(name || "");
  if (bytes.length > 1024) {
    bytes = new TextEncoder().encode(new TextDecoder().decode(bytes.slice(0, 1024)).replace(/�+$/, ""));
  }
  return bytes;
}

function parseHeader(buf) {
  if (buf.length < 8 || MAGIC.some((m, i) => buf[i] !== m)) throw new Error("This isn't a ReelVault video.");
  if (buf[4] !== VERSION) throw new Error(`Made with a newer ReelVault (format v${buf[4]}).`);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const flags = buf[5];
  const nameLen = view.getUint16(6);
  const name = new TextDecoder().decode(buf.subarray(8, 8 + nameLen));
  let p = 8 + nameLen;
  const origSize = Number(view.getBigUint64(p)); p += 8;
  const payloadLen = Number(view.getBigUint64(p)); p += 8;
  const crc = view.getUint32(p); p += 4;
  let salt = null, nonce = null, iterations = 0;
  if (flags & FLAG_ENCRYPTED) {
    salt = buf.slice(p, p + 16); nonce = buf.slice(p + 16, p + 28);
    iterations = view.getUint32(p + 28); p += 32;
  }
  return { flags, name, origSize, payloadLen, crc, salt, nonce, iterations, start: p };
}

async function openReel(buf, password) {
  const h = parseHeader(buf);
  let payload = buf.slice(h.start, h.start + h.payloadLen);
  if (payload.length < h.payloadLen) throw new Error("The video ended before all the data was read.");
  if (crc32(payload) !== h.crc) throw new Error("Checksum mismatch: the video is damaged or was compressed too hard.");

  if (h.flags & FLAG_ENCRYPTED) {
    if (!password) throw new Error("This video is encrypted. Enter its password and try again.");
    const key = await deriveKey(password, h.salt, h.iterations);
    try {
      payload = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: h.nonce }, key, payload));
    } catch {
      throw new Error("Wrong password.");
    }
  }
  if (h.flags & FLAG_DEFLATE) payload = await inflateRaw(payload);
  if (payload.length !== h.origSize) throw new Error("Recovered size doesn't match the header.");
  const name = (h.flags & FLAG_FOLDER) ? `${h.name || "folder"}.zip` : (h.name || "reel_output");
  return { name, data: payload };
}

// ================================================================
// UI plumbing
// ================================================================
const $ = (id) => document.getElementById(id);

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
  return `${n.toFixed(1)} ${units[i]}`;
}

function toast(message, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = message;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", on);
      $(t.getAttribute("aria-controls")).hidden = !on;
    });
  });
});

// Drop zones: returns a getter for the chosen file
function dropZone(kind) {
  let current = null;
  const drop = $(`${kind}-drop`), input = $(`${kind}-input`), go = $(`${kind}-go`);
  const choose = (file) => {
    if (!file) return;
    current = file;
    $(`${kind}-name`).textContent = file.name;
    $(`${kind}-size`).textContent = formatBytes(file.size);
    drop.hidden = true;
    $(`${kind}-chosen`).hidden = false;
    go.disabled = false;
  };
  input.addEventListener("change", () => choose(input.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    choose(e.dataTransfer.files[0]);
  });
  $(`${kind}-clear`).addEventListener("click", () => {
    current = null;
    input.value = "";
    drop.hidden = false;
    $(`${kind}-chosen`).hidden = true;
    $(`${kind}-work`).hidden = true;
    go.disabled = true;
  });
  return () => current;
}

const encodeFile = dropZone("encode");
const decodeFile = dropZone("decode");

// ================================================================
// Robust frame codec (matches reelvault/codecs/robust.py)
// ================================================================
const GRID = 128, CELLS = GRID * GRID;
const INDEX_BITS = 32, COUNT_BITS = 32, LEN_BITS = 16;
const HEADER_BITS = INDEX_BITS + COUNT_BITS + LEN_BITS;
const PAYLOAD_BITS = CELLS - HEADER_BITS; // 16,304
const BLOCK = 4, SIDE = GRID * BLOCK;      // 512 x 512 frames
const COPIES = 3;                          // recorded copies of each frame
const COPY_GAP_MS = 45;

function writeBits(cells, offset, value, width) {
  for (let i = 0; i < width; i++) cells[offset + i] = Math.floor(value / 2 ** (width - 1 - i)) % 2;
}

function frameCells(reelBits, idx, total) {
  const cells = new Uint8Array(CELLS);
  const start = idx * PAYLOAD_BITS;
  const len = Math.min(PAYLOAD_BITS, reelBits.length - start);
  writeBits(cells, 0, idx, INDEX_BITS);
  writeBits(cells, INDEX_BITS, total, COUNT_BITS);
  writeBits(cells, INDEX_BITS + COUNT_BITS, len, LEN_BITS);
  cells.set(reelBits.subarray(start, start + len), HEADER_BITS);
  return cells;
}

function toBits(bytes) {
  const bits = new Uint8Array(bytes.length * 8);
  for (let i = 0; i < bytes.length; i++) {
    for (let b = 0; b < 8; b++) bits[i * 8 + b] = (bytes[i] >> (7 - b)) & 1;
  }
  return bits;
}

function paintCells(ctx, cells) {
  const img = ctx.createImageData(SIDE, SIDE);
  const px = img.data;
  for (let y = 0; y < SIDE; y++) {
    const row = ((y / BLOCK) | 0) * GRID;
    for (let x = 0; x < SIDE; x++) {
      const v = cells[row + ((x / BLOCK) | 0)] ? 255 : 0;
      const i = (y * SIDE + x) * 4;
      px[i] = px[i + 1] = px[i + 2] = v;
      px[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

function pickRecorderType() {
  const types = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"];
  return types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ================================================================
// Encode
// ================================================================
$("encode-go").addEventListener("click", async () => {
  const file = encodeFile();
  if (!file) return;
  const go = $("encode-go"), status = $("encode-status"), meter = $("encode-meter");
  const canvas = $("encode-canvas"), ctx = canvas.getContext("2d");
  go.disabled = true;
  $("encode-work").hidden = false;
  meter.style.width = "0%";

  try {
    const mimeType = pickRecorderType();
    if (!mimeType) throw new Error("This browser can't record video. Try Chrome, Edge or Firefox.");

    status.textContent = "Reading and packing the file…";
    const data = new Uint8Array(await file.arrayBuffer());
    const reel = await buildReel(data, file.name, {
      compress: $("encode-compress").checked,
      password: $("encode-password").value,
    });
    const bits = toBits(reel);
    const total = Math.max(1, Math.ceil(bits.length / PAYLOAD_BITS));

    // captureStream(0) only emits a frame when we call requestFrame(), so every copy is deliberate
    const stream = canvas.captureStream(0);
    const track = stream.getVideoTracks()[0];
    const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 8_000_000 });
    const chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const stopped = new Promise((r) => (recorder.onstop = r));
    recorder.start();

    const started = performance.now();
    for (let idx = 0; idx < total; idx++) {
      paintCells(ctx, frameCells(bits, idx, total));
      for (let c = 0; c < COPIES; c++) {
        track.requestFrame();
        await sleep(COPY_GAP_MS);
      }
      meter.style.width = `${((idx + 1) / total) * 100}%`;
      const left = ((performance.now() - started) / (idx + 1)) * (total - idx - 1) / 1000;
      status.textContent = `Recording frame ${idx + 1} of ${total}` + (total > 3 ? ` · about ${Math.ceil(left)} s left` : "");
    }

    recorder.stop();
    await stopped;
    const ext = mimeType.startsWith("video/mp4") ? "mp4" : "webm";
    const video = new Blob(chunks, { type: mimeType.split(";")[0] });
    saveBlob(video, `${file.name}.${ext}`);
    status.textContent = `Done: ${formatBytes(data.length)} stored in a ${formatBytes(video.size)} video (${total} frames).`;
    toast("Video saved. Keep this tab in front while recording longer files.");
  } catch (err) {
    console.error(err);
    status.textContent = "Encoding failed.";
    toast(err.message, true);
  } finally {
    go.disabled = false;
  }
});

// ================================================================
// Decode
// ================================================================
function cellLevels(ctx) {
  // Mean grey level of each cell (same weights as OpenCV's BGR2GRAY)
  const px = ctx.getImageData(0, 0, SIDE, SIDE).data;
  const levels = new Float32Array(CELLS);
  for (let y = 0; y < SIDE; y++) {
    const row = ((y / BLOCK) | 0) * GRID;
    for (let x = 0; x < SIDE; x++) {
      const i = (y * SIDE + x) * 4;
      levels[row + ((x / BLOCK) | 0)] += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    }
  }
  for (let c = 0; c < CELLS; c++) levels[c] /= BLOCK * BLOCK;
  return levels;
}

function readBits(levels, offset, width) {
  let v = 0;
  for (let i = 0; i < width; i++) v = v * 2 + (levels[offset + i] > 127 ? 1 : 0);
  return v;
}

function frameHeader(levels) {
  return {
    idx: readBits(levels, 0, INDEX_BITS),
    total: readBits(levels, INDEX_BITS, COUNT_BITS),
    len: readBits(levels, INDEX_BITS + COUNT_BITS, LEN_BITS),
  };
}

function assemble(sums, seen, totals) {
  if (!sums.size) throw new Error("No ReelVault frames found in this video.");
  // Majority vote on the frame count, in case a damaged frame reported a wrong one
  const total = [...totals.entries()].sort((a, b) => b[1] - a[1])[0][0];
  const missing = [];
  for (let i = 0; i < total; i++) if (!sums.has(i)) missing.push(i);
  if (missing.length) {
    throw new Error(`${missing.length} of ${total} frames were missed (index ${missing.slice(0, 5).join(", ")}${missing.length > 5 ? "…" : ""}). ` +
      "Keep this tab in front and try again.");
  }
  const bits = [];
  for (let i = 0; i < total; i++) {
    const n = seen.get(i);
    const levels = sums.get(i).map((v) => v / n);
    const { len } = frameHeader(levels);
    for (let j = 0; j < len; j++) bits.push(levels[HEADER_BITS + j] > 127 ? 1 : 0);
  }
  const bytes = new Uint8Array(bits.length >> 3);
  for (let i = 0; i < bytes.length; i++) {
    let b = 0;
    for (let k = 0; k < 8; k++) b = (b << 1) | bits[i * 8 + k];
    bytes[i] = b;
  }
  return bytes;
}

$("decode-go").addEventListener("click", async () => {
  const file = decodeFile();
  if (!file) return;
  const go = $("decode-go"), status = $("decode-status"), meter = $("decode-meter");
  const canvas = $("decode-canvas"), ctx = canvas.getContext("2d", { willReadFrequently: true });
  const video = $("decode-video");
  go.disabled = true;
  $("decode-work").hidden = false;
  meter.style.width = "0%";
  status.textContent = "Opening the video…";

  // Every copy of a frame adds its cell levels; the average decides each bit
  const sums = new Map(), seen = new Map(), totals = new Map();
  const url = URL.createObjectURL(file);
  let finished = false;

  const finish = async (error) => {
    if (finished) return;
    finished = true;
    video.pause();
    URL.revokeObjectURL(url);
    try {
      if (error) throw error;
      status.textContent = "Checking and unpacking…";
      const reel = assemble(sums, seen, totals);
      const { name, data } = await openReel(reel, $("decode-password").value);
      saveBlob(new Blob([data]), name);
      meter.style.width = "100%";
      status.textContent = `Recovered ${name} (${formatBytes(data.length)}). Checksum OK.`;
      toast(`Saved ${name}`);
    } catch (err) {
      console.error(err);
      status.textContent = "Decoding failed.";
      toast(err.message, true);
    } finally {
      go.disabled = false;
    }
  };

  const onFrame = () => {
    if (finished) return;
    ctx.drawImage(video, 0, 0, SIDE, SIDE);
    const levels = cellLevels(ctx);
    const { idx, total, len } = frameHeader(levels);
    if (len <= PAYLOAD_BITS && total > 0 && idx < total && total < 2 ** 24) {
      totals.set(total, (totals.get(total) || 0) + 1);
      if (sums.has(idx)) {
        const acc = sums.get(idx);
        for (let c = 0; c < CELLS; c++) acc[c] += levels[c];
        seen.set(idx, seen.get(idx) + 1);
      } else {
        sums.set(idx, levels);
        seen.set(idx, 1);
      }
    }
    if (video.duration) meter.style.width = `${Math.min(99, (video.currentTime / video.duration) * 100)}%`;
    status.textContent = `Reading frames… ${sums.size} found`;
    if (!video.ended) video.requestVideoFrameCallback(onFrame);
  };

  video.onerror = () => finish(new Error("This browser can't play that video file."));
  // The last frame's callback can come before 'ended' or not at all, so 'ended' also finishes
  video.onended = () => setTimeout(() => finish(), 100);
  video.src = url;
  video.requestVideoFrameCallback(onFrame);
  try {
    await video.play();
  } catch (err) {
    finish(new Error("Couldn't play the video: " + err.message));
  }
});
