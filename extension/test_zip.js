const AdmZip = require('adm-zip');
const path = require('path');
const fs = require('fs');

console.log('--- Validating Extension ZIP ---');

const zipPath = path.join(__dirname, 'release', 'gitreview-ai-extension.zip');
if (!fs.existsSync(zipPath)) {
  console.error('[ERROR] ZIP file not found at', zipPath);
  process.exit(1);
}

const zip = new AdmZip(zipPath);
const entries = zip.getEntries();
let hasBackslash = false;
let missingFiles = [];
const expectedFiles = [
  'manifest.json',
  'popup.html',
  'popup.js',
  'background.js'
];
const entryNames = entries.map(e => e.entryName);

// 1. Check for backslashes in paths
for (const entry of entryNames) {
  if (entry.includes('\\')) {
    console.error(`[FAIL] Entry contains backslash: ${entry}`);
    hasBackslash = true;
  }
}

// 2. Check for expected files
for (const expected of expectedFiles) {
  if (!entryNames.includes(expected)) {
    missingFiles.push(expected);
  }
}

// 3. Check for forbidden files
const forbiddenPatterns = ['node_modules', '.env', 'package.json'];
let hasForbidden = false;
for (const entry of entryNames) {
  for (const pattern of forbiddenPatterns) {
    if (entry.includes(pattern)) {
      console.error(`[FAIL] Forbidden file found: ${entry}`);
      hasForbidden = true;
    }
  }
}

if (hasBackslash || missingFiles.length > 0 || hasForbidden) {
  if (missingFiles.length > 0) console.error('[FAIL] Missing expected files:', missingFiles);
  console.error('[ERROR] ZIP validation failed!');
  process.exit(1);
}

console.log('✅ ZIP validation passed. Contains', entries.length, 'files. No backslashes found.');
