'use strict';

// Minimal readers for the two archive formats uv ships: .tar.gz (macOS, Linux) and .zip (Windows).
// Each returns the contents of the first regular file whose base name is `wanted`.
// Nothing is extracted by path, so an archive entry cannot write outside the folder the caller chooses.

const zlib = require('node:zlib');

class ArchiveError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ArchiveError';
  }
}

function baseName(entryName) {
  const parts = entryName.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1];
}

function readCString(buffer, start, length) {
  const slice = buffer.subarray(start, start + length);
  const end = slice.indexOf(0);
  return slice.toString('utf8', 0, end === -1 ? slice.length : end);
}

function readOctal(buffer, start, length) {
  const text = readCString(buffer, start, length).trim();
  if (text === '') {
    return 0;
  }
  if (!/^[0-7]+$/.test(text)) {
    throw new ArchiveError('The tar archive has a header field Prism cannot read.');
  }
  return parseInt(text, 8);
}

// pax extended headers carry "<length> <key>=<value>\n" records; only `path` matters here.
function paxPath(data) {
  const text = data.toString('utf8');
  let offset = 0;
  let found = null;
  while (offset < text.length) {
    const space = text.indexOf(' ', offset);
    if (space === -1) {
      break;
    }
    const length = parseInt(text.slice(offset, space), 10);
    if (!Number.isFinite(length) || length <= 0) {
      break;
    }
    const record = text.slice(space + 1, offset + length - 1);
    const eq = record.indexOf('=');
    if (eq !== -1 && record.slice(0, eq) === 'path') {
      found = record.slice(eq + 1);
    }
    offset += length;
  }
  return found;
}

function extractFromTarGz(archive, wanted) {
  let tar;
  try {
    tar = zlib.gunzipSync(archive);
  } catch (error) {
    throw new ArchiveError(`The downloaded file is not a valid gzip archive (${error.code || error.message}).`);
  }
  let offset = 0;
  let longName = null;
  while (offset + 512 <= tar.length) {
    const header = tar.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) {
      break;
    }
    const size = readOctal(header, 124, 12);
    const type = String.fromCharCode(header[156] || 48);
    let name = readCString(header, 0, 100);
    if (readCString(header, 257, 5) === 'ustar') {
      const prefix = readCString(header, 345, 155);
      if (prefix) {
        name = `${prefix}/${name}`;
      }
    }
    const dataStart = offset + 512;
    const dataEnd = dataStart + size;
    if (dataEnd > tar.length) {
      throw new ArchiveError('The tar archive is truncated.');
    }
    const data = tar.subarray(dataStart, dataEnd);
    if (type === 'x') {
      longName = paxPath(data) || longName;
    } else if (type === 'L') {
      longName = readCString(data, 0, data.length);
    } else if (type === 'g') {
      // Global pax headers apply to no single entry here.
    } else {
      const entryName = longName || name;
      longName = null;
      if ((type === '0' || type === '\0') && baseName(entryName) === wanted) {
        return Buffer.from(data);
      }
    }
    offset = dataStart + Math.ceil(size / 512) * 512;
  }
  return null;
}

function findEndOfCentralDirectory(zip) {
  const minimum = 22;
  const lowest = Math.max(0, zip.length - minimum - 0xffff);
  for (let index = zip.length - minimum; index >= lowest; index -= 1) {
    if (zip.readUInt32LE(index) === 0x06054b50) {
      return index;
    }
  }
  throw new ArchiveError('The downloaded file is not a valid zip archive.');
}

function extractFromZip(archive, wanted) {
  const eocd = findEndOfCentralDirectory(archive);
  const entryCount = archive.readUInt16LE(eocd + 10);
  let cursor = archive.readUInt32LE(eocd + 16);
  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > archive.length || archive.readUInt32LE(cursor) !== 0x02014b50) {
      throw new ArchiveError('The zip archive has a damaged directory.');
    }
    const method = archive.readUInt16LE(cursor + 10);
    const compressedSize = archive.readUInt32LE(cursor + 20);
    const size = archive.readUInt32LE(cursor + 24);
    const nameLength = archive.readUInt16LE(cursor + 28);
    const extraLength = archive.readUInt16LE(cursor + 30);
    const commentLength = archive.readUInt16LE(cursor + 32);
    const localOffset = archive.readUInt32LE(cursor + 42);
    const name = archive.toString('utf8', cursor + 46, cursor + 46 + nameLength);
    cursor += 46 + nameLength + extraLength + commentLength;
    if (name.endsWith('/') || baseName(name) !== wanted) {
      continue;
    }
    if (compressedSize === 0xffffffff || size === 0xffffffff || localOffset === 0xffffffff) {
      throw new ArchiveError('The zip archive uses zip64 entries, which Prism does not read.');
    }
    if (localOffset + 30 > archive.length || archive.readUInt32LE(localOffset) !== 0x04034b50) {
      throw new ArchiveError('The zip archive has a damaged entry.');
    }
    const dataStart = localOffset + 30 + archive.readUInt16LE(localOffset + 26) + archive.readUInt16LE(localOffset + 28);
    const raw = archive.subarray(dataStart, dataStart + compressedSize);
    if (raw.length !== compressedSize) {
      throw new ArchiveError('The zip archive is truncated.');
    }
    let data;
    if (method === 0) {
      data = Buffer.from(raw);
    } else if (method === 8) {
      data = zlib.inflateRawSync(raw);
    } else {
      throw new ArchiveError(`The zip archive uses compression method ${method}, which Prism does not read.`);
    }
    if (data.length !== size) {
      throw new ArchiveError('A zip entry has an unexpected size.');
    }
    return data;
  }
  return null;
}

function extractBinary(archive, format, wanted) {
  const data = format === 'zip' ? extractFromZip(archive, wanted) : extractFromTarGz(archive, wanted);
  if (!data || data.length === 0) {
    throw new ArchiveError(`The uv archive does not contain ${wanted}.`);
  }
  return data;
}

module.exports = { ArchiveError, extractBinary, extractFromTarGz, extractFromZip };
