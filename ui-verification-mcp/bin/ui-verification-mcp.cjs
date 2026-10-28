#!/usr/bin/env node

const { spawn } = require('node:child_process');
const path = require('node:path');

const target = path.resolve(__dirname, '..', 'dist', 'uiVerification.mjs');

const child = spawn(process.execPath, [target, ...process.argv.slice(2)], {
  stdio: 'inherit',
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

child.on('error', (err) => {
  console.error(err);
  process.exit(1);
});
