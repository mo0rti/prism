'use strict';

// Downloads the real uv release. Skipped unless PRISM_LAUNCHER_NETWORK_TEST=1, so `npm test` works offline.

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const net = require('node:net');
const test = require('node:test');

const { cacheRoot, resolveUv } = require('../lib/launcher');
const { UV_VERSION } = require('../lib/platform');
const { makeTempDir, removeDir } = require('./helpers');

const enabled = process.env.PRISM_LAUNCHER_NETWORK_TEST === '1';
const skip = enabled ? false : 'set PRISM_LAUNCHER_NETWORK_TEST=1 to download the real uv release';

function isolatedEnvironment(dir, extra = {}) {
  return { PATH: '', LOCALAPPDATA: dir, XDG_CACHE_HOME: dir, ...extra };
}

function uvVersion(uvPath) {
  return childProcess.execFileSync(uvPath, ['--version'], { encoding: 'utf8' });
}

test('downloads the pinned uv, verifies it against the published checksum and runs it', { skip, timeout: 180_000 }, async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const env = isolatedEnvironment(dir);
  const result = await resolveUv({ env, homedir: dir });
  assert.equal(result.source, 'download');
  assert.ok(result.path.startsWith(cacheRoot({ env, homedir: dir })));
  assert.match(uvVersion(result.path), new RegExp(`^uv ${UV_VERSION.replace(/\./g, '\\.')}\\b`));
  assert.equal((await resolveUv({ env, homedir: dir })).source, 'cache');
});

test('downloads through an HTTPS_PROXY CONNECT tunnel', { skip, timeout: 180_000 }, async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const connects = [];
  const sockets = new Set();
  const track = (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
    return socket;
  };
  const proxy = net.createServer((client) => {
    track(client);
    client.once('data', (chunk) => {
      const line = chunk.toString('latin1').split('\r\n')[0];
      connects.push(line);
      const [, target] = line.split(' ');
      const [host, port] = target.split(':');
      const upstream = track(net.connect(Number(port), host, () => {
        client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        client.pipe(upstream);
        upstream.pipe(client);
      }));
      upstream.on('error', () => client.destroy());
      client.on('error', () => upstream.destroy());
    });
    client.on('error', () => {});
  });
  await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        for (const socket of sockets) {
          socket.destroy();
        }
        proxy.close(resolve);
      })
  );
  const env = isolatedEnvironment(dir, { HTTPS_PROXY: `http://127.0.0.1:${proxy.address().port}` });
  const result = await resolveUv({ env, homedir: dir });
  assert.equal(result.source, 'download');
  assert.ok(connects.length >= 1);
  assert.ok(connects.every((line) => /^CONNECT [a-z0-9.-]+:443 HTTP\/1\.1$/.test(line)), connects.join('\n'));
  assert.ok(connects.some((line) => line.startsWith('CONNECT github.com:443')));
  assert.match(uvVersion(result.path), /^uv /);
});
