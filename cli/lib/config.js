const Conf = require('conf');
const chalk = require('chalk');

const config = new Conf({
  projectName: 'dropitx',
  defaults: {
    apiUrl: 'https://dropitx-api.onrender.com',
    apiKey: null,
  },
});

function getApiUrl() {
  return config.get('apiUrl');
}

function getApiKey() {
  const key = config.get('apiKey');
  if (!key) {
    console.error(chalk.red('Error: Not logged in. Run `dropitx login` first.'));
    process.exit(1);
  }
  return key;
}

function setApiKey(key) {
  config.set('apiKey', key);
}

function setApiUrl(url) {
  config.set('apiUrl', url);
}

function isLoggedIn() {
  return !!config.get('apiKey');
}

module.exports = {
  config,
  getApiUrl,
  getApiKey,
  setApiKey,
  setApiUrl,
  isLoggedIn,
};
