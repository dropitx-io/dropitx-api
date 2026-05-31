const chalk = require('chalk');
const ora = require('ora');
const fs = require('fs');
const path = require('path');
const { uploadFile, uploadFromStdin } = require('../api');

module.exports = function(program) {
  program
    .command('upload [file]')
    .description('Upload a file and get share URL')
    .option('-p, --password <password>', 'Set password for download')
    .option('-b, --burn', 'Burn after reading (delete after first download)')
    .option('-e, --expires <time>', 'Expiration time (1h, 6h, 24h, 7d, 30d)')
    .option('-m, --max-downloads <n>', 'Maximum number of downloads')
    .option('-j, --json', 'Output as JSON')
    .action(async (file, options) => {
      const spinner = ora('Uploading...').start();
      
      try {
        let result;
        
        // Check if stdin has data (pipe mode)
        if (!file && !process.stdin.isTTY) {
          spinner.text = 'Reading from stdin...';
          result = await uploadFromStdin({
            burnAfterReading: options.burn,
            expiresIn: options.expires,
            maxDownloads: options.maxDownloads ? parseInt(options.maxDownloads) : undefined,
          });
        } else if (file) {
          // Check if file exists
          if (!fs.existsSync(file)) {
            spinner.fail(chalk.red(`File not found: ${file}`));
            process.exit(1);
          }
          
          spinner.text = `Uploading ${path.basename(file)}...`;
          result = await uploadFile(file, {
            burnAfterReading: options.burn,
            expiresIn: options.expires,
            maxDownloads: options.maxDownloads ? parseInt(options.maxDownloads) : undefined,
          });
        } else {
          spinner.fail(chalk.red('No file specified. Use: dropitx upload <file> or pipe input'));
          process.exit(1);
        }
        
        spinner.succeed(chalk.green('Upload successful!'));
        
        if (options.json) {
          console.log(JSON.stringify(result, null, 2));
        } else {
          console.log('');
          console.log(chalk.cyan('URL:'), result.url);
          console.log(chalk.cyan('Slug:'), result.slug);
          console.log(chalk.cyan('Filename:'), result.filename);
          if (result.burn_after_reading) {
            console.log(chalk.yellow('⚠ Burn after reading: file will be deleted after first download'));
          }
          if (result.expires_at) {
            console.log(chalk.gray(`Expires: ${result.expires_at}`));
          }
          console.log('');
          console.log(chalk.gray('Delete token (save this to delete later):'));
          console.log(chalk.gray(result.deleteToken));
        }
      } catch (error) {
        spinner.fail(chalk.red(`Upload failed: ${error.message}`));
        process.exit(1);
      }
    });
};
