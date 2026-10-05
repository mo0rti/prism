'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { ChecksumError } = require('../lib/download');
const { PACKAGE_VERSION, cacheRoot, findOnPath, main, packageSpec, resolveUv, uvArguments } = require('../lib/launcher');
const { UV_VERSION, assetFor } = require('../lib/platform');
const { sha256Hex } = require('../lib/download');
const { makeStubUv, makeTarGz, makeTempDir, makeZip, removeDir, stubEnvironment } = require('./helpers');

const HOST = { platform: process.platform, arch: process.arch };
const UV_NAME = process.platform === 'win32' ? 'uv.exe' : 'uv';

function memoryStream() {
  const chunks = [];
  return { write: (text) => chunks.push(String(text)), text: () => chunks.join('') };
}

// An asset that matches an archive the test builds, shaped like the host's real asset.
function craftedAsset(payload) {
  const real = process.platform === 'win32' ? { binary: 'uv.exe', format: 'zip', file: 'uv-test.zip' } : { binary: 'uv', format: 'tar.gz', file: 'uv-test.tar.gz' };
  const archive =
    real.format === 'zip'
      ? makeZip([{ name: 'uv.exe', data: payload }])
      : makeTarGz([{ name: 'uv-test/uv', data: payload }]);
  return { asset: { ...real, target: 'test-target', url: 'https://example.invalid/uv', sha256: sha256Hex(archive) }, archive };
}

test('the package version is the Prism version and selects the PyPI package', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  assert.equal(PACKAGE_VERSION, manifest.version);
  assert.equal(packageSpec({}), `prism-kit==${manifest.version}`);
  assert.deepEqual(uvArguments(['--version'], {}), ['tool', 'run', '--from', `prism-kit==${manifest.version}`, 'prism', '--version']);
});

test('the Python Prism version equals the launcher version', () => {
  const init = fs.readFileSync(path.join(__dirname, '..', '..', 'prism_cli', '__init__.py'), 'utf8');
  const match = /__version__\s*=\s*"([^"]+)"/.exec(init);
  assert.ok(match, 'prism_cli/__init__.py defines __version__');
  assert.equal(match[1], PACKAGE_VERSION);
});

test('PRISM_PACKAGE_SPEC replaces the package that uv runs', () => {
  assert.deepEqual(uvArguments(['doctor'], { PRISM_PACKAGE_SPEC: '/tmp/prism_kit-0.3.0-py3-none-any.whl' }), [
    'tool',
    'run',
    '--from',
    '/tmp/prism_kit-0.3.0-py3-none-any.whl',
    'prism',
    'doctor',
  ]);
});

test('the cache folder follows the platform conventions', () => {
  assert.equal(
    cacheRoot({ platform: 'win32', env: { LOCALAPPDATA: 'C:\\Users\\Example\\AppData\\Local' }, homedir: 'C:\\Users\\Example' }),
    'C:\\Users\\Example\\AppData\\Local\\prism\\uv'
  );
  assert.equal(cacheRoot({ platform: 'win32', env: {}, homedir: 'C:\\Users\\Example' }), 'C:\\Users\\Example\\AppData\\Local\\prism\\uv');
  assert.equal(cacheRoot({ platform: 'linux', env: {}, homedir: '/home/example' }), '/home/example/.cache/prism/uv');
  assert.equal(cacheRoot({ platform: 'darwin', env: {}, homedir: '/Users/example' }), '/Users/example/.cache/prism/uv');
  assert.equal(cacheRoot({ platform: 'linux', env: { XDG_CACHE_HOME: '/var/cache/example' }, homedir: '/home/example' }), '/var/cache/example/prism/uv');
  assert.equal(cacheRoot({ platform: 'linux', env: { XDG_CACHE_HOME: 'relative' }, homedir: '/home/example' }), '/home/example/.cache/prism/uv');
});

test('PRISM_UV wins over uv on the PATH', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const onPath = path.join(dir, 'bin');
  fs.mkdirSync(onPath);
  fs.writeFileSync(path.join(onPath, UV_NAME), 'x');
  const override = path.join(dir, 'custom-uv');
  fs.writeFileSync(override, 'x');
  const result = await resolveUv({ ...HOST, env: { PATH: onPath, PRISM_UV: override }, homedir: dir });
  assert.deepEqual(result, { path: override, source: 'PRISM_UV' });
});

test('PRISM_UV that points nowhere is an error, not a silent fallback', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const onPath = path.join(dir, 'bin');
  fs.mkdirSync(onPath);
  fs.writeFileSync(path.join(onPath, UV_NAME), 'x');
  await assert.rejects(
    resolveUv({ ...HOST, env: { PATH: onPath, PRISM_UV: path.join(dir, 'missing-uv') }, homedir: dir }),
    /PRISM_UV is set but does not point to an existing file/
  );
});

test('uv on the PATH is used before the cache or a download', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const onPath = path.join(dir, 'bin');
  fs.mkdirSync(onPath);
  const uv = path.join(onPath, UV_NAME);
  fs.writeFileSync(uv, 'x');
  const fetchBuffer = async () => assert.fail('must not download');
  const result = await resolveUv({ ...HOST, env: { PATH: `${path.join(dir, 'empty')}${path.delimiter}${onPath}` }, homedir: dir, fetchBuffer });
  assert.deepEqual(result, { path: uv, source: 'PATH' });
  assert.equal(findOnPath({ PATH: path.join(dir, 'empty') }, process.platform), null);
});

test('first run downloads, verifies and caches uv; the second run reuses the cache', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const payload = Buffer.from('stand-in uv binary\n'.repeat(100));
  const { asset, archive } = craftedAsset(payload);
  const env = { PATH: '', LOCALAPPDATA: dir, XDG_CACHE_HOME: dir };
  const requests = [];
  const messages = [];
  const fetchBuffer = async (url) => {
    requests.push(url);
    return archive;
  };

  const first = await resolveUv({ ...HOST, env, homedir: dir, asset, fetchBuffer, log: (message) => messages.push(message) });
  assert.equal(first.source, 'download');
  assert.deepEqual(requests, [asset.url]);
  assert.ok(messages.some((message) => message.includes(`uv ${UV_VERSION}`)));
  const expectedPath = path.join(cacheRoot({ ...HOST, env, homedir: dir }), UV_VERSION, asset.binary);
  assert.equal(first.path, expectedPath);
  assert.deepEqual(fs.readFileSync(first.path), payload);
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(first.path).mode & 0o111, 0o111, 'the binary is executable');
  }
  const leftovers = fs.readdirSync(path.dirname(path.dirname(first.path))).filter((name) => name !== UV_VERSION);
  assert.deepEqual(leftovers, [], 'no staging folder remains');

  const second = await resolveUv({ ...HOST, env, homedir: dir, asset, fetchBuffer: async () => assert.fail('must not download again') });
  assert.deepEqual(second, { path: first.path, source: 'cache' });
});

test('a download that fails the SHA-256 check is discarded and nothing is cached', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const env = { PATH: '', LOCALAPPDATA: dir, XDG_CACHE_HOME: dir };
  const realAsset = assetFor(HOST);
  await assert.rejects(
    resolveUv({ ...HOST, env, homedir: dir, fetchBuffer: async () => Buffer.from('tampered archive') }),
    (error) => {
      assert.ok(error instanceof ChecksumError);
      assert.equal(error.expected, realAsset.sha256);
      return true;
    }
  );
  const root = cacheRoot({ ...HOST, env, homedir: dir });
  const entries = fs.existsSync(root) ? fs.readdirSync(root) : [];
  assert.deepEqual(entries, [], 'no cache or staging entries remain');
});

test('an unsupported platform stops with the supported list and exit code 1', async () => {
  const stderr = memoryStream();
  const code = await main(['--version'], { env: { PATH: '' }, platform: 'freebsd', arch: 'x64', stderr });
  assert.equal(code, 1);
  assert.match(stderr.text(), /^prism launcher: uv has no download for freebsd\/x64\./);
  assert.match(stderr.text(), /Windows x64 and arm64, macOS x64 and arm64, Linux x64 and arm64/);
});

test('a failed download is reported as a launcher error without environment values', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const stderr = memoryStream();
  const secret = 'proxy-token-should-never-appear';
  const code = await main(['--version'], {
    env: { PATH: '', LOCALAPPDATA: dir, XDG_CACHE_HOME: dir, HTTPS_PROXY: `http://user:${secret}@proxy.invalid:3128` },
    ...HOST,
    homedir: dir,
    stderr,
    fetchBuffer: async () => {
      throw new Error('Cannot download from github.com (ENOTFOUND).');
    },
  });
  assert.equal(code, 1);
  assert.match(stderr.text(), /prism launcher: Cannot download from github\.com/);
  assert.ok(!stderr.text().includes(secret));
});

test('arguments and exit code pass through to uv unchanged', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const uv = makeStubUv(dir);
  const output = path.join(dir, 'invocation.json');
  const argv = ['board', 'serve', '.', '--port', '8765', '--name', 'two words', '--flag=value with space', '-h'];

  for (const exitCode of [0, 3, 7]) {
    const stderr = memoryStream();
    const code = await main(argv, { env: stubEnvironment({ output, exitCode, extra: { PRISM_UV: uv, STUB_MARKER: 'visible-to-child' } }), stderr });
    assert.equal(code, exitCode);
    assert.equal(stderr.text(), '', 'a successful hand-off prints nothing of its own');
    const seen = JSON.parse(fs.readFileSync(output, 'utf8'));
    assert.deepEqual(seen.args, ['tool', 'run', '--from', `prism-kit==${PACKAGE_VERSION}`, 'prism', ...argv]);
    assert.equal(seen.marker, 'visible-to-child', 'the environment reaches uv');
    fs.rmSync(output);
  }
});

test('PRISM_PACKAGE_SPEC reaches uv as the --from value', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const uv = makeStubUv(dir);
  const output = path.join(dir, 'invocation.json');
  const spec = path.join(dir, 'prism_kit-0.3.0-py3-none-any.whl');
  const code = await main(['--version'], { env: stubEnvironment({ output, extra: { PRISM_UV: uv, PRISM_PACKAGE_SPEC: spec } }) });
  assert.equal(code, 0);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, 'utf8')).args, ['tool', 'run', '--from', spec, 'prism', '--version']);
});

test('PRISM_UV points the launcher at a chosen uv even when no other uv exists', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const uv = makeStubUv(dir);
  const output = path.join(dir, 'invocation.json');
  const code = await main([], {
    env: stubEnvironment({ output, exitCode: 5, extra: { PRISM_UV: uv, PATH: path.join(dir, 'nothing-here') } }),
  });
  assert.equal(code, 5);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, 'utf8')).args, ['tool', 'run', '--from', `prism-kit==${PACKAGE_VERSION}`, 'prism']);
});

test('a uv that cannot start is reported with its path and the exit code 1', async (t) => {
  const dir = makeTempDir();
  t.after(() => removeDir(dir));
  const notExecutable = path.join(dir, 'uv-not-executable');
  fs.writeFileSync(notExecutable, 'this is not a program');
  const stderr = memoryStream();
  const code = await main(['--version'], { env: { PRISM_UV: notExecutable, PATH: '' }, stderr });
  assert.equal(code, 1);
  assert.match(stderr.text(), /^prism launcher: Cannot start uv at /);
});
