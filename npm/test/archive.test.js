'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { ArchiveError, extractBinary } = require('../lib/archive');
const { makeTarGz, makeZip } = require('./helpers');

const PAYLOAD = Buffer.from('#!stand-in for the uv executable\n'.repeat(40));

test('reads uv from a tar.gz that nests it in a folder', () => {
  const archive = makeTarGz([
    { name: 'uv-x86_64-unknown-linux-gnu/', type: '5' },
    { name: 'uv-x86_64-unknown-linux-gnu/uv', data: PAYLOAD },
    { name: 'uv-x86_64-unknown-linux-gnu/uvx', data: Buffer.from('other') },
  ]);
  assert.deepEqual(extractBinary(archive, 'tar.gz', 'uv'), PAYLOAD);
});

test('reads a tar entry whose path is split across the ustar prefix', () => {
  const archive = makeTarGz([{ name: 'uv', prefix: 'uv-aarch64-apple-darwin', data: PAYLOAD }]);
  assert.deepEqual(extractBinary(archive, 'tar.gz', 'uv'), PAYLOAD);
});

test('reads a tar entry named by a pax path header', () => {
  const record = 'path=deep/nested/uv-folder/uv';
  let length = record.length + 3;
  while (String(length).length + 1 + record.length + 1 !== length) {
    length += 1;
  }
  const pax = `${length} ${record}\n`;
  assert.equal(pax.length, length);
  const archive = makeTarGz([
    { name: 'PaxHeader', type: 'x', data: Buffer.from(pax) },
    { name: 'ignored-short-name', data: PAYLOAD },
  ]);
  assert.deepEqual(extractBinary(archive, 'tar.gz', 'uv'), PAYLOAD);
});

test('does not mistake a directory or a similarly named file for uv', () => {
  const archive = makeTarGz([
    { name: 'folder/uv/', type: '5' },
    { name: 'folder/uvx', data: Buffer.from('x') },
    { name: 'folder/uv.txt', data: Buffer.from('x') },
  ]);
  assert.throws(() => extractBinary(archive, 'tar.gz', 'uv'), ArchiveError);
});

test('a tar.gz that is not gzip is rejected', () => {
  assert.throws(() => extractBinary(Buffer.from('not an archive'), 'tar.gz', 'uv'), ArchiveError);
});

test('a truncated tar is rejected', () => {
  const archive = makeTarGz([{ name: 'folder/uv', data: PAYLOAD }]);
  const zlib = require('node:zlib');
  const truncated = zlib.gzipSync(zlib.gunzipSync(archive).subarray(0, 600));
  assert.throws(() => extractBinary(truncated, 'tar.gz', 'uv'), /truncated/);
});

test('reads uv.exe from a zip, deflated or stored', () => {
  for (const deflate of [true, false]) {
    const archive = makeZip([
      { name: 'uvw.exe', data: Buffer.from('w'), deflate },
      { name: 'uv.exe', data: PAYLOAD, deflate },
      { name: 'uvx.exe', data: Buffer.from('x'), deflate },
    ]);
    assert.deepEqual(extractBinary(archive, 'zip', 'uv.exe'), PAYLOAD, `deflate=${deflate}`);
  }
});

test('a zip without the binary or a damaged zip is rejected', () => {
  assert.throws(() => extractBinary(makeZip([{ name: 'uvx.exe', data: Buffer.from('x') }]), 'zip', 'uv.exe'), /does not contain uv\.exe/);
  assert.throws(() => extractBinary(Buffer.from('definitely not a zip file at all'), 'zip', 'uv.exe'), ArchiveError);
});

test('an empty binary is rejected', () => {
  assert.throws(() => extractBinary(makeZip([{ name: 'uv.exe', data: Buffer.alloc(0) }]), 'zip', 'uv.exe'), ArchiveError);
});
