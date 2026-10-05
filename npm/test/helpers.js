'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');

function makeTempDir(prefix = 'prism-launcher-test-') {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
}

function removeDir(directory) {
  fs.rmSync(directory, { recursive: true, force: true });
}

function tarHeader({ name, size, type = '0', prefix = '' }) {
  const header = Buffer.alloc(512);
  header.write(name, 0, 100, 'utf8');
  header.write('0000755\0', 100, 8, 'ascii');
  header.write('0000000\0', 108, 8, 'ascii');
  header.write('0000000\0', 116, 8, 'ascii');
  header.write(`${size.toString(8).padStart(11, '0')}\0`, 124, 12, 'ascii');
  header.write('00000000000\0', 136, 12, 'ascii');
  header.write('        ', 148, 8, 'ascii');
  header.write(type, 156, 1, 'ascii');
  header.write('ustar\0', 257, 6, 'ascii');
  header.write('00', 263, 2, 'ascii');
  if (prefix) {
    header.write(prefix, 345, 155, 'utf8');
  }
  let sum = 0;
  for (const byte of header) {
    sum += byte;
  }
  header.write(`${sum.toString(8).padStart(6, '0')}\0 `, 148, 8, 'ascii');
  return header;
}

// entries: [{ name, data, type?, prefix? }]. Returns a gzip-compressed tar archive.
function makeTarGz(entries) {
  const blocks = [];
  for (const entry of entries) {
    const data = Buffer.from(entry.data || '');
    blocks.push(tarHeader({ name: entry.name, size: data.length, type: entry.type, prefix: entry.prefix }));
    blocks.push(data);
    const padding = (512 - (data.length % 512)) % 512;
    blocks.push(Buffer.alloc(padding));
  }
  blocks.push(Buffer.alloc(1024));
  return zlib.gzipSync(Buffer.concat(blocks));
}

// entries: [{ name, data, deflate? }]. Returns a zip archive.
function makeZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8');
    const data = Buffer.from(entry.data || '');
    const deflate = entry.deflate !== false;
    const stored = deflate ? zlib.deflateRawSync(data) : data;
    const crc = typeof zlib.crc32 === 'function' ? zlib.crc32(data) : 0;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(deflate ? 8 : 0, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(stored.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, stored);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(deflate ? 8 : 0, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(stored.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += local.length + name.length + stored.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

// A stand-in for uv: a copy of the Node executable that loads test/stub-preload.js through NODE_OPTIONS.
// The preload records its arguments, exits with STUB_EXIT and never reaches Node's own argument handling.
function makeStubUv(directory) {
  const binary = path.join(directory, process.platform === 'win32' ? 'uv.exe' : 'uv');
  fs.copyFileSync(process.execPath, binary);
  fs.chmodSync(binary, 0o755);
  return binary;
}

function stubEnvironment({ output, exitCode = 0, extra = {} }) {
  const preload = path.join(__dirname, 'stub-preload.js').replace(/\\/g, '/');
  const base = { ...process.env };
  for (const name of ['NODE_TEST_CONTEXT', 'PRISM_UV', 'PRISM_PACKAGE_SPEC', 'HTTPS_PROXY', 'https_proxy']) {
    delete base[name];
  }
  return {
    ...base,
    NODE_OPTIONS: `--require "${preload}"`,
    STUB_OUT: output,
    STUB_EXIT: String(exitCode),
    ...extra,
  };
}

module.exports = { makeStubUv, makeTarGz, makeTempDir, makeZip, removeDir, stubEnvironment };
