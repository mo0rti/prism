'use strict';

// HTTPS download with HTTPS_PROXY support, using only Node's standard library.
// Messages name hosts and status codes, never proxy credentials or environment values.

const crypto = require('node:crypto');
const http = require('node:http');
const https = require('node:https');
const tls = require('node:tls');

const DEFAULT_TIMEOUT_MS = 60_000;
const DEFAULT_MAX_BYTES = 200 * 1024 * 1024;
const MAX_REDIRECTS = 5;

class DownloadError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DownloadError';
  }
}

class ChecksumError extends Error {
  constructor(file, expected, actual) {
    super(
      `The downloaded ${file} does not match the published SHA-256 checksum, so it was discarded. ` +
        `Expected ${expected}, got ${actual}.`
    );
    this.name = 'ChecksumError';
    this.expected = expected;
    this.actual = actual;
  }
}

function sha256Hex(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function verifySha256(buffer, expected, file) {
  const actual = sha256Hex(buffer);
  if (actual !== expected.toLowerCase()) {
    throw new ChecksumError(file, expected.toLowerCase(), actual);
  }
}

function envValue(env, name) {
  return env[name] || env[name.toLowerCase()] || '';
}

// Whether NO_PROXY exempts the host: "*", an exact host, or a domain suffix with or without a leading dot.
function bypassesProxy(hostname, env) {
  const list = envValue(env, 'NO_PROXY');
  if (!list) {
    return false;
  }
  const host = hostname.toLowerCase();
  return list
    .split(',')
    .map((entry) => entry.trim().toLowerCase().replace(/:\d+$/, ''))
    .filter(Boolean)
    .some((entry) => {
      if (entry === '*') {
        return true;
      }
      const suffix = entry.startsWith('.') ? entry.slice(1) : entry;
      return host === suffix || host.endsWith(`.${suffix}`);
    });
}

// Returns the proxy URL to tunnel through for this target, or null for a direct connection.
function proxyFor(targetUrl, env) {
  const raw = envValue(env, 'HTTPS_PROXY');
  if (!raw) {
    return null;
  }
  const target = new URL(targetUrl);
  if (bypassesProxy(target.hostname, env)) {
    return null;
  }
  let proxy;
  try {
    proxy = new URL(raw.includes('://') ? raw : `http://${raw}`);
  } catch (_error) {
    throw new DownloadError('HTTPS_PROXY is not a valid URL. Use a value such as http://proxy.example:8080.');
  }
  if (proxy.protocol !== 'http:') {
    throw new DownloadError(
      `HTTPS_PROXY uses ${proxy.protocol.replace(':', '')}://, which the launcher does not support. Use an http:// proxy URL.`
    );
  }
  return proxy;
}

function proxyLabel(proxy) {
  return `${proxy.hostname}${proxy.port ? `:${proxy.port}` : ''}`;
}

// An https.Agent that reaches the target through an HTTP proxy's CONNECT tunnel.
class TunnelAgent extends https.Agent {
  constructor(proxy) {
    super({ keepAlive: false });
    this.proxy = proxy;
  }

  createConnection(options, callback) {
    const proxy = this.proxy;
    const port = options.port || 443;
    const host = options.host || options.hostname;
    const headers = { Host: `${host}:${port}` };
    if (proxy.username || proxy.password) {
      const credentials = `${decodeURIComponent(proxy.username)}:${decodeURIComponent(proxy.password)}`;
      headers['Proxy-Authorization'] = `Basic ${Buffer.from(credentials).toString('base64')}`;
    }
    const request = http.request({
      host: proxy.hostname,
      port: proxy.port || 80,
      method: 'CONNECT',
      path: `${host}:${port}`,
      headers,
    });
    request.setTimeout(DEFAULT_TIMEOUT_MS, () => {
      request.destroy(new DownloadError(`The proxy ${proxyLabel(proxy)} did not answer in time.`));
    });
    request.once('connect', (response, socket) => {
      if (response.statusCode !== 200) {
        socket.destroy();
        callback(new DownloadError(`The proxy ${proxyLabel(proxy)} refused the connection to ${host} (HTTP ${response.statusCode}).`));
        return;
      }
      const secure = tls.connect({ socket, servername: options.servername || host });
      secure.once('close', () => socket.destroy());
      callback(null, secure);
    });
    request.once('error', (error) => {
      callback(
        error instanceof DownloadError
          ? error
          : new DownloadError(`Cannot reach the proxy ${proxyLabel(proxy)} (${error.code || error.message}).`)
      );
    });
    request.end();
  }
}

function getOnce(url, { env, timeoutMs, maxBytes }) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    if (target.protocol !== 'https:') {
      reject(new DownloadError(`Refusing to download over ${target.protocol.replace(':', '')}: ${target.host}.`));
      return;
    }
    let agent;
    try {
      const proxy = proxyFor(url, env);
      // A fresh agent per request without keep-alive, so no socket outlives the download.
      agent = proxy ? new TunnelAgent(proxy) : false;
    } catch (error) {
      reject(error);
      return;
    }
    const request = https.get(
      target,
      { agent, headers: { 'User-Agent': 'mortitech-prism-launcher', Accept: 'application/octet-stream' } },
      (response) => {
        const status = response.statusCode;
        if ([301, 302, 303, 307, 308].includes(status) && response.headers.location) {
          response.resume();
          request.destroy();
          resolve({ redirect: new URL(response.headers.location, target).toString() });
          return;
        }
        if (status !== 200) {
          response.resume();
          reject(new DownloadError(`Download from ${target.host} failed (HTTP ${status}).`));
          return;
        }
        const chunks = [];
        let received = 0;
        response.on('data', (chunk) => {
          received += chunk.length;
          if (received > maxBytes) {
            request.destroy(new DownloadError(`The download from ${target.host} is larger than expected.`));
            return;
          }
          chunks.push(chunk);
        });
        response.on('end', () => {
          request.destroy();
          resolve({ body: Buffer.concat(chunks) });
        });
        response.on('error', (error) =>
          reject(new DownloadError(`Download from ${target.host} was interrupted (${error.code || error.message}).`))
        );
      }
    );
    request.setTimeout(timeoutMs, () => {
      request.destroy(new DownloadError(`Download from ${target.host} timed out.`));
    });
    request.on('error', (error) => {
      reject(
        error instanceof DownloadError
          ? error
          : new DownloadError(`Cannot download from ${target.host} (${error.code || error.message}).`)
      );
    });
  });
}

async function fetchBuffer(url, { env = process.env, timeoutMs = DEFAULT_TIMEOUT_MS, maxBytes = DEFAULT_MAX_BYTES } = {}) {
  let current = url;
  for (let hop = 0; hop <= MAX_REDIRECTS; hop += 1) {
    const result = await getOnce(current, { env, timeoutMs, maxBytes });
    if (result.body) {
      return result.body;
    }
    current = result.redirect;
  }
  throw new DownloadError(`Too many redirects while downloading from ${new URL(url).host}.`);
}

module.exports = {
  ChecksumError,
  DownloadError,
  bypassesProxy,
  fetchBuffer,
  proxyFor,
  sha256Hex,
  verifySha256,
};
