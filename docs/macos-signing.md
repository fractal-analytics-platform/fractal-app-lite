# macOS signing: secrets setup

To sign and notarize the macOS app, the release workflow needs five GitHub
secrets. Creating them requires a Mac and the **Account Holder** role on the
Apple Developer team.

## 1. Signing certificate

1. In **Keychain Access**: **Keychain Access → Certificate Assistant → Request
   a Certificate From a Certificate Authority…**, enter your email, select
   **Saved to disk**, and save the file.
2. On <https://developer.apple.com/account/resources/certificates/list>, click
   **+**, choose **Developer ID Application**, upload the file from step 1 and
   download the certificate.
3. Double-click the downloaded certificate to add it to Keychain Access.
4. In Keychain Access → **My Certificates**, right-click **Developer ID
   Application: …** → **Export…** as a `.p12` file, choosing a password.
5. In Terminal: `base64 -i certificate.p12 | pbcopy` copies the file as text.

## 2. Notarization key

1. On <https://appstoreconnect.apple.com/access/integrations/api>, under **Team
   Keys**, click **+**, give it a name and the **Developer** access.
2. Note the **Key ID** and the **Issuer ID**, and download the `.p8` file (it
   can be downloaded only once).

## 3. GitHub secrets

In the repository: **Settings → Secrets and variables → Actions → New
repository secret**. Add:

| Name | Value |
|---|---|
| `MACOS_CERTIFICATE_P12_BASE64` | the text copied in step 1.5 |
| `MACOS_CERTIFICATE_PASSWORD` | the `.p12` password |
| `MACOS_NOTARY_API_KEY_P8` | the whole content of the `.p8` file |
| `MACOS_NOTARY_API_KEY_ID` | the Key ID |
| `MACOS_NOTARY_API_ISSUER_ID` | the Issuer ID |
