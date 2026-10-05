'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { UV_ASSETS, UV_RELEASE_BASE, UV_VERSION, UnsupportedPlatformError, assetFor } = require('../lib/platform');

const SUPPORTED = [
  ['win32', 'x64', undefined, 'x86_64-pc-windows-msvc', 'uv-x86_64-pc-windows-msvc.zip', 'uv.exe', 'zip'],
  ['win32', 'arm64', undefined, 'aarch64-pc-windows-msvc', 'uv-aarch64-pc-windows-msvc.zip', 'uv.exe', 'zip'],
  ['darwin', 'x64', undefined, 'x86_64-apple-darwin', 'uv-x86_64-apple-darwin.tar.gz', 'uv', 'tar.gz'],
  ['darwin', 'arm64', undefined, 'aarch64-apple-darwin', 'uv-aarch64-apple-darwin.tar.gz', 'uv', 'tar.gz'],
  ['linux', 'x64', 'gnu', 'x86_64-unknown-linux-gnu', 'uv-x86_64-unknown-linux-gnu.tar.gz', 'uv', 'tar.gz'],
  ['linux', 'arm64', 'gnu', 'aarch64-unknown-linux-gnu', 'uv-aarch64-unknown-linux-gnu.tar.gz', 'uv', 'tar.gz'],
  ['linux', 'x64', 'musl', 'x86_64-unknown-linux-musl', 'uv-x86_64-unknown-linux-musl.tar.gz', 'uv', 'tar.gz'],
  ['linux', 'arm64', 'musl', 'aarch64-unknown-linux-musl', 'uv-aarch64-unknown-linux-musl.tar.gz', 'uv', 'tar.gz'],
];

for (const [platform, arch, libc, target, file, binary, format] of SUPPORTED) {
  test(`maps ${platform}/${arch}${libc ? `/${libc}` : ''} to ${file}`, () => {
    const asset = assetFor({ platform, arch, libc });
    assert.equal(asset.target, target);
    assert.equal(asset.file, file);
    assert.equal(asset.binary, binary);
    assert.equal(asset.format, format);
    assert.equal(asset.url, `${UV_RELEASE_BASE}/${file}`);
    assert.equal(asset.sha256, UV_ASSETS[target].sha256);
  });
}

test('downloads come from the official uv GitHub release of the pinned version', () => {
  assert.match(UV_VERSION, /^\d+\.\d+\.\d+$/);
  assert.equal(UV_RELEASE_BASE, `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}`);
});

test('every pinned asset has a file name that matches its target and a SHA-256 digest', () => {
  for (const [target, entry] of Object.entries(UV_ASSETS)) {
    assert.equal(entry.file, `uv-${target}.${target.includes('windows') ? 'zip' : 'tar.gz'}`);
    assert.match(entry.sha256, /^[0-9a-f]{64}$/, target);
  }
  const digests = Object.values(UV_ASSETS).map((entry) => entry.sha256);
  assert.equal(new Set(digests).size, digests.length, 'digests are distinct');
});

test('an unsupported platform or architecture fails with a clear message', () => {
  for (const [platform, arch] of [
    ['freebsd', 'x64'],
    ['win32', 'ia32'],
    ['linux', 'ppc64'],
    ['darwin', 'arm'],
    ['aix', 'ppc64'],
  ]) {
    assert.throws(
      () => assetFor({ platform, arch }),
      (error) => {
        assert.ok(error instanceof UnsupportedPlatformError);
        assert.equal(error.code, 'PRISM_UNSUPPORTED_PLATFORM');
        assert.ok(error.message.includes(`${platform}/${arch}`), error.message);
        assert.ok(error.message.includes('PRISM_UV'), error.message);
        return true;
      },
      `${platform}/${arch}`
    );
  }
});

test('the running platform is mapped without arguments, or reported as unsupported', () => {
  try {
    const asset = assetFor();
    assert.ok(asset.url.startsWith(UV_RELEASE_BASE));
  } catch (error) {
    assert.ok(error instanceof UnsupportedPlatformError);
  }
});
