const chalk = require('chalk');
const ora = require('ora');
const { setApiKey, setApiUrl, getApiUrl } = require('../config');

module.exports = function(program) {
  program
    .command('login')
    .description('Authenticate with DropItX API key')
    .option('-k, --api-key <key>', 'API key to save')
    .option('-u, --api-url <url>', 'API URL (default: https://dropitx-api.onrender.com)')
    .action(async (options) => {
      const readline = require('readline');
      const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
      });
      
      const question = (query) => new Promise((resolve) => rl.question(query, resolve));
      
      try {
        let apiKey = options.apiKey;
        let apiUrl = options.apiUrl;
        
        if (!apiKey) {
          apiKey = await question(chalk.cyan('Enter your API key: '));
        }
        
        if (!apiKey.trim()) {
          console.error(chalk.red('Error: API key is required'));
          process.exit(1);
        }
        
        if (apiUrl) {
          setApiUrl(apiUrl);
          console.log(chalk.green(`✓ API URL set to: ${apiUrl}`));
        }
        
        setApiKey(apiKey.trim());
        console.log(chalk.green('✓ API key saved successfully'));
        console.log(chalk.gray(`  Config location: ~/.config/dropitx/config.json`));
        console.log(chalk.gray(`  API URL: ${getApiUrl()}`));
      } catch (error) {
        console.error(chalk.red(`Error: ${error.message}`));
        process.exit(1);
      } finally {
        rl.close();
      }
    });
};
