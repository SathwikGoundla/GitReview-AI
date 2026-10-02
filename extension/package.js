const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');

console.log('--- GitReview AI Extension Packager ---');

try {
  console.log('Building for production...');
  execSync('npm run build', { stdio: 'inherit' });
} catch (err) {
  console.error('\n[ERROR] Build failed! Please ensure VITE_BACKEND_URL is configured for production.\n');
  process.exit(1);
}

const outputDir = path.join(__dirname, 'release');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir);
}

const zipPath = path.join(outputDir, 'gitreview-ai-extension.zip');
const zip = new AdmZip();
zip.addLocalFolder(path.join(__dirname, 'dist'), '');
zip.writeZip(zipPath);

const stats = fs.statSync(zipPath);
const sizeMB = stats.size / (1024 * 1024);

console.log(`\n✅ Packaging complete: ${zipPath}`);
console.log(`Size: ${sizeMB.toFixed(2)} MB`);

if (sizeMB > 10) {
  console.warn('\n[WARNING] The extension zip exceeds 10MB! Please check for large assets or unnecessary dependencies.\n');
}
