// Validates a JSON file with the same parser n8n uses (JSON.parse), so
// ask-claude.ps1 and the workflow never disagree about what is valid.
//
// Prints "OK" or "ERR <message>" on stdout and always exits 0: the verdict
// must not ride on the exit code, or a failure to launch node would look
// like invalid JSON.
//
// Kept as a file rather than `node -e` because PowerShell strips embedded
// double quotes when handing arguments to a native command.
const fs = require('fs');
try {
  JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  process.stdout.write('OK');
} catch (e) {
  process.stdout.write('ERR ' + e.message);
}
