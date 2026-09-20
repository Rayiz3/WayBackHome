const { withAndroidManifest, withDangerousMod } = require('expo/config-plugins');
const fs = require('node:fs/promises');
const path = require('node:path');

const networkXml = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">127.0.0.1</domain>
    <domain includeSubdomains="false">localhost</domain>
  </domain-config>
</network-security-config>
`;

module.exports = config => {
  config = withAndroidManifest(config, result => {
    const application = result.modResults.manifest.application[0];
    const existing = application.$['android:networkSecurityConfig'];
    if (existing && existing !== '@xml/waybackhome_network_security')
      throw new Error('An existing network security configuration must be merged explicitly.');
    application.$['android:networkSecurityConfig'] = '@xml/waybackhome_network_security';
    return result;
  });
  return withDangerousMod(config, ['android', async result => {
    const directory = path.join(result.modRequest.platformProjectRoot, 'app/src/main/res/xml');
    await fs.mkdir(directory, { recursive: true });
    await fs.writeFile(path.join(directory, 'waybackhome_network_security.xml'), networkXml);
    return result;
  }]);
};
module.exports.networkXml = networkXml;

