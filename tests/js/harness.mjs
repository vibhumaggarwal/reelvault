// Runs the browser app's format code under Node (which has CompressionStream and WebCrypto)
// so the Python tests can check both implementations agree. Everything above the
// "UI plumbing" marker in app.js is DOM-free.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const app = fs.readFileSync(path.join(here, "../../src/reelvault/web/app.js"), "utf8");
const core = app.split("// UI plumbing")[0];
const robust = app.split("// Robust frame codec")[1].split("function paintCells")[0];
const m = {};
new Function("m", core + "\n//" + robust + "\nObject.assign(m, { buildReel, openReel, toBits, frameCells, PAYLOAD_BITS });")(m);

const [cmd, ...args] = process.argv.slice(2);

if (cmd === "build") {
  // build <input> <name> <password|-> <out-cells>: writes the robust frames' cells, one byte per cell
  const [input, name, password, out] = args;
  const reel = await m.buildReel(new Uint8Array(fs.readFileSync(input)), name, {
    compress: true, password: password === "-" ? "" : password,
  });
  const bits = m.toBits(reel);
  const total = Math.max(1, Math.ceil(bits.length / m.PAYLOAD_BITS));
  const frames = [];
  for (let i = 0; i < total; i++) frames.push(m.frameCells(bits, i, total));
  fs.writeFileSync(out, Buffer.concat(frames.map((f) => Buffer.from(f))));
} else if (cmd === "open") {
  // open <reel-buffer> <password|-> <out>
  const [input, password, out] = args;
  const { name, data } = await m.openReel(new Uint8Array(fs.readFileSync(input)), password === "-" ? "" : password);
  fs.writeFileSync(out, data);
  console.log(name);
} else {
  console.error("usage: harness.mjs build|open ...");
  process.exit(2);
}
