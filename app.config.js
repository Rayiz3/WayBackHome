const fs = require('node:fs');
const path = require('node:path');

module.exports = ({ config }) => {
  const projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID;
  const googleServicesFile = './google-services.json';
  return {
    ...config,
    plugins: [...(config.plugins || []), '@react-native-community/datetimepicker', 'expo-secure-store',
      ...(process.env.WAYBACKHOME_USB_TEST === '1' ? ['./plugins/withLoopbackNetwork'] : [])],
    android: {
      ...config.android,
      ...(fs.existsSync(path.join(__dirname, googleServicesFile)) ? { googleServicesFile } : {}),
    },
    extra: {
      ...config.extra,
      ...(projectId ? { eas: { projectId } } : {}),
    },
  };
};
