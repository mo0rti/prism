'use strict';

// Loaded into a copy of the Node executable that the tests use in place of uv (see helpers.js).
// Node resolves the first argument ("tool") into the script path, so its base name is the first argument.

const fs = require('node:fs');
const path = require('node:path');

const args = [path.basename(process.argv[1]), ...process.argv.slice(2)];
fs.writeFileSync(
  process.env.STUB_OUT,
  JSON.stringify({ args, packageSpecSeen: process.env.PRISM_PACKAGE_SPEC || null, marker: process.env.STUB_MARKER || null })
);
process.exit(Number(process.env.STUB_EXIT || 0));
