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
