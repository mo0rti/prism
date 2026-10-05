'use strict';

const assert = require('node:assert/strict');
const net = require('node:net');
const test = require('node:test');

const { ChecksumError, DownloadError, bypassesProxy, fetchBuffer, proxyFor, sha256Hex, verifySha256 } = require('../lib/download');

test('verifySha256 accepts the matching digest in any letter case', () => {
  const data = Buffer.from('uv archive bytes');
  const digest = sha256Hex(data);
  verifySha256(data, digest, 'uv.zip');
  verifySha256(data, digest.toUpperCase(), 'uv.zip');
});

test('verifySha256 rejects a different digest and names both values', () => {
  const data = Buffer.from('uv archive bytes');
  const wrong = '0'.repeat(64);
  assert.throws(
    () => verifySha256(data, wrong, 'uv.zip'),
    (error) => {
      assert.ok(error instanceof ChecksumError);
      assert.equal(error.expected, wrong);
      assert.equal(error.actual, sha256Hex(data));
      assert.match(error.message, /uv\.zip/);
      assert.match(error.message, /discarded/);
      return true;
    }
  );
});

test('no proxy is used without HTTPS_PROXY', () => {
  assert.equal(proxyFor('https://github.com/x', {}), null);
});

test('HTTPS_PROXY and https_proxy select an http proxy; a bare host:port gets http://', () => {
  assert.equal(proxyFor('https://github.com/x', { HTTPS_PROXY: 'http://proxy.example:3128' }).host, 'proxy.example:3128');
  assert.equal(proxyFor('https://github.com/x', { https_proxy: 'proxy.example:3128' }).host, 'proxy.example:3128');
});

test('an unsupported or malformed proxy value gives a clear error without echoing it', () => {
  assert.throws(() => proxyFor('https://github.com/x', { HTTPS_PROXY: 'socks5://user:secret@proxy.example:1080' }), (error) => {
    assert.ok(error instanceof DownloadError);
    assert.match(error.message, /socks5/);
    assert.ok(!error.message.includes('secret'));
    return true;
  });
  assert.throws(() => proxyFor('https://github.com/x', { HTTPS_PROXY: 'http://' }), DownloadError);
});

test('NO_PROXY exempts exact hosts, domain suffixes and *', () => {
  const env = (value) => ({ HTTPS_PROXY: 'http://proxy.example:3128', NO_PROXY: value });
  assert.equal(proxyFor('https://github.com/x', env('github.com')), null);
  assert.equal(proxyFor('https://objects.githubusercontent.com/x', env('.githubusercontent.com')), null);
  assert.equal(proxyFor('https://objects.githubusercontent.com/x', env('internal.example, githubusercontent.com:443')), null);
  assert.equal(proxyFor('https://github.com/x', env('*')), null);
  assert.notEqual(proxyFor('https://github.com/x', env('hub.com')), null);
  assert.equal(bypassesProxy('github.com', {}), false);
});

test('a download over plain http is refused', async () => {
  await assert.rejects(fetchBuffer('http://github.com/x', { env: {} }), /Refusing to download over http/);
});

test('a proxy that refuses CONNECT is reported by host and status, and its credentials stay out of the message', async () => {
  const seen = {};
  const server = net.createServer((socket) => {
    let received = '';
    socket.on('data', (chunk) => {
      received += chunk.toString('latin1');
      if (received.includes('\r\n\r\n')) {
        seen.request = received;
        socket.end('HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');
      }
    });
    socket.on('error', () => {});
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  try {
    await assert.rejects(
      fetchBuffer('https://github.com/astral-sh/uv/releases/download/0.0.0/uv.zip', {
        env: { HTTPS_PROXY: `http://proxy-user:proxy-secret@127.0.0.1:${port}` },
        timeoutMs: 5000,
      }),
      (error) => {
        assert.ok(error instanceof DownloadError);
        assert.match(error.message, /407/);
        assert.match(error.message, new RegExp(`127\\.0\\.0\\.1:${port}`));
        assert.ok(!error.message.includes('proxy-secret'));
        assert.ok(!error.message.includes('proxy-user'));
        return true;
      }
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
  assert.match(seen.request, /^CONNECT github\.com:443 HTTP\/1\.1\r\n/);
  const expected = Buffer.from('proxy-user:proxy-secret').toString('base64');
  assert.ok(seen.request.includes(`Proxy-Authorization: Basic ${expected}`));
});

test('an unreachable proxy is reported by host and port', async () => {
  const probe = net.createServer();
  await new Promise((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const { port } = probe.address();
  await new Promise((resolve) => probe.close(resolve));
  await assert.rejects(
    fetchBuffer('https://github.com/x', { env: { HTTPS_PROXY: `http://127.0.0.1:${port}` }, timeoutMs: 5000 }),
    (error) => {
      assert.ok(error instanceof DownloadError);
      assert.match(error.message, new RegExp(`Cannot reach the proxy 127\\.0\\.0\\.1:${port}`));
      return true;
    }
  );
});
