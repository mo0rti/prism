'use strict';

// Runs the Prism CLI through uv: `uv tool run --from prism-kit==<version> prism <args>`.
// uv comes from, in order: PRISM_UV, the PATH, the per-user cache, or a one-time verified download.

const childProcess = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { extractBinary } = require('./archive');
const { fetchBuffer: defaultFetchBuffer, verifySha256 } = require('./download');
const { UV_VERSION, assetFor } = require('./platform');

const PACKAGE_VERSION = require('../package.json').version;

class LauncherError extends Error {
  constructor(message) {
    super(message);
    this.name = 'LauncherError';
  }
}

function pathApi(platform) {
  return platform === 'win32' ? path.win32 : path.posix;
}

// %LOCALAPPDATA%\prism\uv on Windows, $XDG_CACHE_HOME or ~/.cache followed by prism/uv elsewhere.
function cacheRoot({ env = process.env, platform = process.platform, homedir = os.homedir() } = {}) {
  const api = pathApi(platform);
  if (platform === 'win32') {
    const base = env.LOCALAPPDATA || api.join(homedir, 'AppData', 'Local');
    return api.join(base, 'prism', 'uv');
  }
  const xdg = env.XDG_CACHE_HOME;
  const base = xdg && api.isAbsolute(xdg) ? xdg : api.join(homedir, '.cache');
  return api.join(base, 'prism', 'uv');
}

function isFile(candidate) {
  try {
    return fs.statSync(candidate).isFile();
  } catch (_error) {
    return false;
  }
}

function findOnPath(env, platform) {
  const api = pathApi(platform);
  const pathValue = env.PATH || env.Path || '';
  const name = platform === 'win32' ? 'uv.exe' : 'uv';
  for (const directory of pathValue.split(api.delimiter)) {
    if (!directory) {
      continue;
    }
    const candidate = api.join(directory.replace(/^"(.*)"$/, '$1'), name);
    if (isFile(candidate)) {
      return candidate;
    }
  }
  return null;
}

// Downloads, verifies and unpacks the pinned uv into the cache; returns the path of the binary.
async function installUv({ asset, root, fetchBuffer, env, log }) {
  const final = path.join(root, UV_VERSION);
  const binaryPath = path.join(final, asset.binary);
  log(`Prism: downloading uv ${UV_VERSION} (${asset.target}) from github.com. This happens once.`);
  const archive = await fetchBuffer(asset.url, { env });
  verifySha256(archive, asset.sha256, asset.file);
  const binary = extractBinary(archive, asset.format, asset.binary);

  fs.mkdirSync(root, { recursive: true });
  const staging = fs.mkdtempSync(path.join(root, '.staging-'));
  try {
    fs.writeFileSync(path.join(staging, asset.binary), binary, { mode: 0o755 });
    try {
      fs.renameSync(staging, final);
    } catch (error) {
      // Another launcher may have installed the same version meanwhile; its copy is as good.
      if (!isFile(binaryPath)) {
        throw error;
      }
    }
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
  return binaryPath;
}

async function resolveUv({
  env = process.env,
  platform = process.platform,
  arch = process.arch,
  libc,
  homedir,
  asset: assetOverride,
  fetchBuffer = defaultFetchBuffer,
  log = () => {},
} = {}) {
  if (env.PRISM_UV) {
    if (!isFile(env.PRISM_UV)) {
      throw new LauncherError('PRISM_UV is set but does not point to an existing file. Set it to the full path of the uv executable.');
    }
    return { path: env.PRISM_UV, source: 'PRISM_UV' };
  }

  const onPath = findOnPath(env, platform);
  if (onPath) {
    return { path: onPath, source: 'PATH' };
  }

  const asset = assetOverride || assetFor({ platform, arch, libc });
  const root = cacheRoot({ env, platform, homedir });
  const cached = path.join(root, UV_VERSION, asset.binary);
  if (isFile(cached)) {
    return { path: cached, source: 'cache' };
  }

  const installed = await installUv({ asset, root, fetchBuffer, env, log });
  return { path: installed, source: 'download' };
}

function packageSpec(env) {
  return env.PRISM_PACKAGE_SPEC || `prism-kit==${PACKAGE_VERSION}`;
}

function uvArguments(args, env) {
  return ['tool', 'run', '--from', packageSpec(env), 'prism', ...args];
}

// Starts uv with inherited stdio and resolves with the exit code to pass through.
function runUv(uv, args, env) {
  return new Promise((resolve, reject) => {
    const child = childProcess.spawn(uv, args, { stdio: 'inherit', env });
    // Ctrl+C reaches the child through the shared terminal; the launcher stays alive until the child has finished.
    const ignore = () => {};
    const forward = (signal) => () => {
      child.kill(signal);
    };
    const forwarded = { SIGTERM: forward('SIGTERM'), SIGHUP: forward('SIGHUP') };
    process.on('SIGINT', ignore);
    for (const [signal, handler] of Object.entries(forwarded)) {
      process.on(signal, handler);
    }
    const detach = () => {
      process.removeListener('SIGINT', ignore);
      for (const [signal, handler] of Object.entries(forwarded)) {
        process.removeListener(signal, handler);
      }
    };
    child.once('error', (error) => {
      detach();
      reject(new LauncherError(`Cannot start uv at ${uv} (${error.code || error.message}).`));
    });
    child.once('close', (code, signal) => {
      detach();
      if (code !== null) {
        resolve(code);
      } else {
        resolve(128 + ((signal && os.constants.signals[signal]) || 1));
      }
    });
  });
}

async function main(argv, options = {}) {
  const env = options.env || process.env;
  const stderr = options.stderr || process.stderr;
  const log = (message) => stderr.write(`${message}\n`);
  try {
    const uv = await resolveUv({
      env,
      platform: options.platform,
      arch: options.arch,
      libc: options.libc,
      homedir: options.homedir,
      fetchBuffer: options.fetchBuffer,
      log,
    });
    return await runUv(uv.path, uvArguments(argv, env), env);
  } catch (error) {
    log(`prism launcher: ${error.message}`);
    return 1;
  }
}

module.exports = {
  LauncherError,
  PACKAGE_VERSION,
  cacheRoot,
  findOnPath,
  installUv,
  main,
  packageSpec,
  resolveUv,
  runUv,
  uvArguments,
};
