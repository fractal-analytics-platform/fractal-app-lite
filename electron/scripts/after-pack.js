const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

module.exports = async function (context) {
  // FIXME: remove once we sign with an Apple Developer ID certificate.
  if (context.electronPlatformName === 'darwin') return adHocSignMac(context)
  if (context.electronPlatformName !== 'linux') return

  const execName = context.packager.executableName
  const bin = path.join(context.appOutDir, execName)
  const realBin = path.join(context.appOutDir, execName + '.bin')

  if (!fs.existsSync(bin)) return

  fs.renameSync(bin, realBin)

  fs.writeFileSync(
    bin,
    `#!/bin/bash\nexec "$(dirname "$0")/${execName}.bin" --no-sandbox "$@"\n`
  )
  fs.chmodSync(bin, '0755')
}

// FIXME: remove this function once we sign with an Apple Developer ID
// certificate (electron-builder then signs the bundle itself).
//
// electron-builder modifies Electron's prebuilt (ad-hoc signed) app bundle —
// renames the executable, rewrites Info.plist, adds our resources — and with
// no Developer ID identity it skips signing, leaving the bundle with a broken
// signature. Intel Macs tolerate that, but on Apple Silicon, macOS treats a
// downloaded app with an invalid signature as tampered with ("Malware Blocked
// and Moved to Trash", no Open Anyway). Re-signing ad-hoc gives a valid
// signature, so Gatekeeper falls back to the usual "Not Opened" → Open Anyway
// flow for unnotarized apps.
function adHocSignMac(context) {
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' })
}
