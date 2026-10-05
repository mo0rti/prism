'use strict';

// The uv release the launcher downloads when uv is not already available.
// The SHA-256 values are the ones uv publishes in the release's `sha256.sum`
// (https://github.com/astral-sh/uv/releases/download/<version>/sha256.sum).
// To move to another uv release, replace the version and every digest from
// that file; docs/cli-release.md describes the steps.
const UV_VERSION = '0.12.23';
const UV_RELEASE_BASE = `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}`;

const UV_ASSETS = {
  'aarch64-apple-darwin': {
    file: 'uv-aarch64-apple-darwin.tar.gz',
    sha256: '50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544',
  },
  'x86_64-apple-darwin': {
    file: 'uv-x86_64-apple-darwin.tar.gz',
    sha256: '960da44cb4b73685206ddd250b19e0a117fa41095710c1038f081f5cb613efb4',
  },
  'aarch64-pc-windows-msvc': {
    file: 'uv-aarch64-pc-windows-msvc.zip',
    sha256: '13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5',
  },
  'x86_64-pc-windows-msvc': {
    file: 'uv-x86_64-pc-windows-msvc.zip',
    sha256: '75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90',
  },
  'aarch64-unknown-linux-gnu': {
    file: 'uv-aarch64-unknown-linux-gnu.tar.gz',
    sha256: '6524bd338177ed50d035d39354e12545e993bbeba2ecbddf0480c5b3a81d313f',
  },
  'aarch64-unknown-linux-musl': {
    file: 'uv-aarch64-unknown-linux-musl.tar.gz',
    sha256: 'b536543cc4d50661986b165c76ee8aa9056e4fa332edcd153ff2e98760f9359b',
  },
  'x86_64-unknown-linux-gnu': {
    file: 'uv-x86_64-unknown-linux-gnu.tar.gz',
    sha256: '9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6',
  },
  'x86_64-unknown-linux-musl': {
    file: 'uv-x86_64-unknown-linux-musl.tar.gz',
    sha256: '1cff8783850e794470aadb73f54b749542a511fc57b0ce6468b64bd3852e0ade',
  },
};

const SUPPORTED = [
  'Windows x64 and arm64',
  'macOS x64 and arm64',
  'Linux x64 and arm64',
];

class UnsupportedPlatformError extends Error {
  constructor(platform, arch) {
    super(
      `uv has no download for ${platform}/${arch}. Supported platforms: ${SUPPORTED.join(', ')}. ` +
        'Install uv yourself (https://docs.astral.sh/uv/) and put it on PATH, or set PRISM_UV to its path.'
    );
    this.name = 'UnsupportedPlatformError';
    this.code = 'PRISM_UNSUPPORTED_PLATFORM';
  }
}

// Linux builds that link glibc use the gnu target; others (Alpine and similar) use the static musl one.
function detectLibc() {
  try {
    const report = process.report;
    if (report && typeof report.getReport === 'function') {
      const previous = report.excludeNetwork;
      report.excludeNetwork = true;
      try {
        const header = report.getReport().header;
        return header && header.glibcVersionRuntime ? 'gnu' : 'musl';
      } finally {
        report.excludeNetwork = previous;
      }
    }
  } catch (_error) {
    // Fall through to the default below.
  }
  return 'gnu';
}

function targetFor(platform, arch, libc) {
  const cpu = arch === 'x64' ? 'x86_64' : arch === 'arm64' ? 'aarch64' : null;
  if (!cpu) {
    return null;
  }
  if (platform === 'win32') {
    return `${cpu}-pc-windows-msvc`;
  }
  if (platform === 'darwin') {
    return `${cpu}-apple-darwin`;
  }
  if (platform === 'linux') {
    return `${cpu}-unknown-linux-${libc === 'musl' ? 'musl' : 'gnu'}`;
  }
  return null;
}

// Maps a Node platform and architecture to the uv release asset for it.
function assetFor({ platform = process.platform, arch = process.arch, libc } = {}) {
  const resolvedLibc = platform === 'linux' ? libc || detectLibc() : undefined;
  const target = targetFor(platform, arch, resolvedLibc);
  const entry = target ? UV_ASSETS[target] : undefined;
  if (!entry) {
    throw new UnsupportedPlatformError(platform, arch);
  }
  return {
    target,
    file: entry.file,
    sha256: entry.sha256,
    url: `${UV_RELEASE_BASE}/${entry.file}`,
    format: entry.file.endsWith('.zip') ? 'zip' : 'tar.gz',
    binary: platform === 'win32' ? 'uv.exe' : 'uv',
  };
}

module.exports = {
  UV_VERSION,
  UV_RELEASE_BASE,
  UV_ASSETS,
  UnsupportedPlatformError,
  assetFor,
  detectLibc,
};
